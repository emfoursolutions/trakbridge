"""
ABOUTME: Unit tests for UdpMulticastListener — passthrough bridge plugin that joins a
ABOUTME: multicast group and forwards raw CoT XML datagrams verbatim to TAK servers.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import takproto
from defusedxml import ElementTree as ET

from plugins.udp_multicast_listener import (
    UdpMulticastListener,
    _TokenBucket,
    _takproto_to_cot_xml,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


VALID_COT = (
    b'<event version="2.0" uid="test-1" type="a-f-G-U-C" how="m-g" '
    b'time="2026-06-29T00:00:00Z" start="2026-06-29T00:00:00Z" '
    b'stale="2026-06-29T00:05:00Z">'
    b'<point lat="-27.47" lon="153.02" hae="0" ce="9999999" le="9999999"/>'
    b"</event>"
)


def _make_plugin(overrides=None):
    config = {
        "multicast_group": "239.2.3.1",
        "multicast_port": 6969,
        "bind_interface": "0.0.0.0",
        "source_filter": "",
        "max_packet_bytes": 65535,
        "per_source_rate_limit": 200,
        "require_cot_event_root": True,
        "format": "auto",
    }
    if overrides:
        config.update(overrides)
    plugin = UdpMulticastListener(config)
    plugin.stream = MagicMock()
    plugin.stream.id = 1
    plugin.stream.name = "test-stream"
    # Two active TAK servers by default
    server_a = MagicMock(id=10, name="tak-a")
    server_b = MagicMock(id=20, name="tak-b")
    plugin.stream.get_active_tak_servers.return_value = [server_a, server_b]
    return plugin


# ---------------------------------------------------------------------------
# Plugin identity & metadata
# ---------------------------------------------------------------------------


class TestPluginIdentity:
    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "udp_multicast_listener"

    def test_class_level_plugin_name(self):
        assert UdpMulticastListener.get_plugin_name() == "udp_multicast_listener"

    def test_category_is_inbound(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "inbound"

    def test_transport_is_active(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata.get("inbound_transport") == "active"

    def test_accepted_content_types_includes_xml(self):
        plugin = _make_plugin()
        assert "application/xml" in plugin.get_accepted_content_types()

    def test_has_required_config_fields(self):
        plugin = _make_plugin()
        names = [f.name for f in plugin.get_config_fields()]
        for required in ("multicast_group", "multicast_port"):
            assert required in names

    def test_optional_config_fields_present(self):
        plugin = _make_plugin()
        names = [f.name for f in plugin.get_config_fields()]
        for optional in (
            "bind_interface",
            "source_filter",
            "max_packet_bytes",
            "per_source_rate_limit",
            "require_cot_event_root",
        ):
            assert optional in names

    def test_transform_payload_not_supported(self):
        plugin = _make_plugin()
        with pytest.raises(NotImplementedError):
            plugin.transform_payload(b"x", "application/xml", {})


# ---------------------------------------------------------------------------
# CoT validation helper
# ---------------------------------------------------------------------------


class TestIsCotEvent:
    def test_accepts_valid_event(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(VALID_COT) is True

    def test_accepts_event_with_xml_declaration(self):
        plugin = _make_plugin()
        buf = b'<?xml version="1.0"?>' + VALID_COT
        assert plugin._is_cot_event(buf) is True

    def test_rejects_non_event_root(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"<other><x/></other>") is False

    def test_rejects_malformed_xml(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"<event ") is False

    def test_rejects_empty(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"") is False

    def test_rejects_plain_text(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"hello world") is False

    def test_accepts_event_with_leading_nul_padding(self):
        plugin = _make_plugin()
        # Some senders pad datagrams to a fixed buffer with NULs.
        assert plugin._is_cot_event(b"\x00\x00" + VALID_COT + b"\x00\x00") is True

    def test_accepts_event_with_utf8_bom(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"\xef\xbb\xbf" + VALID_COT) is True

    def test_accepts_event_with_leading_whitespace(self):
        plugin = _make_plugin()
        assert plugin._is_cot_event(b"  \r\n" + VALID_COT) is True


# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


class TestTokenBucket:
    def test_take_until_empty(self):
        clock = [0.0]
        bucket = _TokenBucket(rate=5, now=lambda: clock[0])
        for _ in range(5):
            assert bucket.try_take() is True
        assert bucket.try_take() is False

    def test_refills_over_time(self):
        clock = [0.0]
        bucket = _TokenBucket(rate=10, now=lambda: clock[0])
        for _ in range(10):
            bucket.try_take()
        assert bucket.try_take() is False
        clock[0] = 0.5  # half a second → 5 tokens
        assert bucket.try_take() is True

    def test_capacity_capped(self):
        clock = [0.0]
        bucket = _TokenBucket(rate=4, now=lambda: clock[0])
        clock[0] = 1000.0  # huge gap; tokens must cap at capacity
        for _ in range(4):
            assert bucket.try_take() is True
        assert bucket.try_take() is False


# ---------------------------------------------------------------------------
# Datagram handling (happy path + drops)
# ---------------------------------------------------------------------------


class TestDatagramForwarding:
    async def test_forwards_to_each_tak_server(self):
        plugin = _make_plugin()
        cot_service = MagicMock()
        cot_service.enqueue_event = AsyncMock(return_value=True)
        plugin._cot_service = cot_service
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))

        assert cot_service.enqueue_event.await_count == 2
        first = cot_service.enqueue_event.await_args_list[0].args
        # Bytes forwarded verbatim — no re-serialisation
        assert first[0] == VALID_COT
        assert first[1] in (10, 20)
        assert plugin._forwarded == 2

    async def test_drops_malformed_xml(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock())
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(b"<event ", ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()
        assert plugin._dropped_validation == 1

    async def test_drops_non_event_root(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock())
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(b"<other><x/></other>", ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()
        assert plugin._dropped_validation == 1

    async def test_drops_oversize(self):
        plugin = _make_plugin({"max_packet_bytes": 100})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock())
        plugin._target_servers = plugin.stream.get_active_tak_servers()
        big = b"x" * 101

        await plugin._handle_datagram(big, ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()
        assert plugin._dropped_size == 1

    async def test_drops_when_rate_limit_exhausted(self):
        plugin = _make_plugin({"per_source_rate_limit": 2})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        for _ in range(2):
            await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))
        # third should be dropped
        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))

        # 2 accepted * 2 servers = 4 enqueues; rate-drop adds nothing
        assert plugin._cot_service.enqueue_event.await_count == 4
        assert plugin._dropped_rate == 1

    async def test_rate_limit_per_source(self):
        plugin = _make_plugin({"per_source_rate_limit": 1})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))
        # different source — has its own bucket
        await plugin._handle_datagram(VALID_COT, ("10.0.0.6", 6969))

        assert plugin._cot_service.enqueue_event.await_count == 4
        assert plugin._dropped_rate == 0

    async def test_validation_skipped_when_disabled(self):
        plugin = _make_plugin({"require_cot_event_root": False})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        # Non-CoT bytes — but validation off, so forwarded verbatim
        await plugin._handle_datagram(b"raw bytes", ("10.0.0.5", 6969))

        assert plugin._cot_service.enqueue_event.await_count == 2

    async def test_no_tak_servers_is_noop(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock())
        plugin._target_servers = []

        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()


# ---------------------------------------------------------------------------
# Socket setup (IGMP join, SSM)
# ---------------------------------------------------------------------------


class TestSocketSetup:
    def test_open_socket_uses_any_source_membership_by_default(self):
        plugin = _make_plugin()
        fake_sock = MagicMock()
        with patch("socket.socket", return_value=fake_sock):
            sock = plugin._open_socket(plugin.config)
        assert sock is fake_sock

        # IP_ADD_MEMBERSHIP with packed (group, interface)
        calls = [c.args for c in fake_sock.setsockopt.call_args_list]
        assert any(
            c[1] == socket.IP_ADD_MEMBERSHIP
            and c[2] == socket.inet_aton("239.2.3.1") + socket.inet_aton("0.0.0.0")
            for c in calls
        )
        fake_sock.bind.assert_called_once_with(("0.0.0.0", 6969))
        fake_sock.setblocking.assert_called_once_with(False)

    def test_open_socket_uses_source_membership_when_filter_set(self):
        plugin = _make_plugin({"source_filter": "10.0.0.5, 10.0.0.6"})
        fake_sock = MagicMock()
        with patch("socket.socket", return_value=fake_sock):
            plugin._open_socket(plugin.config)

        calls = [c.args for c in fake_sock.setsockopt.call_args_list]
        # Expect IP_ADD_SOURCE_MEMBERSHIP per source: 3 packed ip's
        expected_packed = [
            socket.inet_aton("239.2.3.1")
            + socket.inet_aton("0.0.0.0")
            + socket.inet_aton(src)
            for src in ("10.0.0.5", "10.0.0.6")
        ]
        # IP_ADD_SOURCE_MEMBERSHIP = 39 on Linux/macOS; we read it from socket
        ssm_opt = getattr(socket, "IP_ADD_SOURCE_MEMBERSHIP", 39)
        ssm_calls = [c for c in calls if c[1] == ssm_opt]
        assert len(ssm_calls) == 2
        for c in ssm_calls:
            assert c[2] in expected_packed

        # And IP_ADD_MEMBERSHIP should NOT have been issued
        assert not any(c[1] == socket.IP_ADD_MEMBERSHIP for c in calls)


# ---------------------------------------------------------------------------
# Lifecycle: start() / cleanup()
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_start_creates_endpoint_and_starts_workers(self):
        plugin = _make_plugin()

        fake_sock = MagicMock()
        fake_transport = MagicMock()
        fake_protocol = MagicMock()

        cot_service = MagicMock()
        cot_service.start_worker = AsyncMock(return_value=True)
        cot_service.enqueue_event = AsyncMock(return_value=True)

        async def fake_create_endpoint(protocol_factory, sock):
            return fake_transport, fake_protocol

        with (
            patch.object(plugin, "_open_socket", return_value=fake_sock),
            patch(
                "plugins.udp_multicast_listener.get_queued_cot_service",
                return_value=cot_service,
            ),
        ):
            loop_mock = MagicMock()
            loop_mock.create_datagram_endpoint = fake_create_endpoint
            with patch("asyncio.get_running_loop", return_value=loop_mock):
                await plugin.start()

        assert plugin._transport is fake_transport
        assert plugin._socket is fake_sock
        assert cot_service.start_worker.await_count == 2
        assert plugin._target_servers and len(plugin._target_servers) == 2

    async def test_start_with_no_tak_servers_is_safe(self):
        plugin = _make_plugin()
        plugin.stream.get_active_tak_servers.return_value = []

        fake_sock = MagicMock()
        fake_transport = MagicMock()

        async def fake_create_endpoint(protocol_factory, sock):
            return fake_transport, MagicMock()

        cot_service = MagicMock()
        cot_service.start_worker = AsyncMock(return_value=True)
        with (
            patch.object(plugin, "_open_socket", return_value=fake_sock),
            patch(
                "plugins.udp_multicast_listener.get_queued_cot_service",
                return_value=cot_service,
            ),
        ):
            loop_mock = MagicMock()
            loop_mock.create_datagram_endpoint = fake_create_endpoint
            with patch("asyncio.get_running_loop", return_value=loop_mock):
                await plugin.start()  # should not raise

        cot_service.start_worker.assert_not_awaited()

    async def test_cleanup_closes_transport(self):
        plugin = _make_plugin()
        transport = MagicMock()
        plugin._transport = transport
        plugin._socket = MagicMock()

        await plugin.cleanup()

        transport.close.assert_called_once()
        assert plugin._transport is None

    async def test_cleanup_is_idempotent(self):
        plugin = _make_plugin()
        # Nothing was started; cleanup should not raise
        await plugin.cleanup()
        await plugin.cleanup()


# ---------------------------------------------------------------------------
# TAK Protocol v1 (protobuf / Mesh SA) decode
# ---------------------------------------------------------------------------


def _build_takproto_datagram(
    uid="ANDROID-test-1",
    cot_type="a-f-G-U-C",
    callsign="Chaos1",
    lat=-27.47,
    lon=153.02,
    hae=100.5,
):
    """Encode a representative CoT as a TAK Mesh SA datagram (bf 01 bf...)."""
    xml = (
        f'<event version="2.0" uid="{uid}" type="{cot_type}" '
        f'how="m-g" time="2026-06-29T18:30:00Z" '
        f'start="2026-06-29T18:30:00Z" stale="2026-06-29T18:35:00Z">'
        f'<point lat="{lat}" lon="{lon}" hae="{hae}" ce="9.9" le="9.9"/>'
        f"<detail>"
        f'<contact callsign="{callsign}" endpoint="10.0.50.20:4242:tcp"/>'
        f'<__group name="Green" role="Team Member"/>'
        f'<takv device="Pixel" platform="ATAK" os="34" version="5.0"/>'
        f'<status battery="87"/>'
        f'<track course="180.0" speed="1.5"/>'
        f'<uid Droid="{callsign}"/>'
        f"</detail>"
        f"</event>"
    ).encode("utf-8")
    return bytes(takproto.xml2proto(xml, protover=takproto.TAKProtoVer.MESH))


class TestTakprotoDecode:
    def test_decoded_xml_has_event_root(self):
        datagram = _build_takproto_datagram()
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        assert root.tag == "event"

    def test_decoded_xml_preserves_core_attrs(self):
        datagram = _build_takproto_datagram(uid="ANDROID-abc", cot_type="a-f-G-U-C")
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        assert root.attrib["uid"] == "ANDROID-abc"
        assert root.attrib["type"] == "a-f-G-U-C"
        assert root.attrib["how"] == "m-g"
        assert root.attrib["version"] == "2.0"

    def test_decoded_xml_times_are_iso8601_utc(self):
        datagram = _build_takproto_datagram()
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        # Times must round-trip as Z-suffixed ISO 8601, not raw ms-since-epoch.
        for attr in ("time", "start", "stale"):
            v = root.attrib[attr]
            assert v.endswith("Z"), f"{attr}={v!r}"
            assert "T" in v

    def test_decoded_xml_preserves_point(self):
        datagram = _build_takproto_datagram(lat=-27.47, lon=153.02, hae=100.5)
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        point = root.find("point")
        assert point is not None
        assert abs(float(point.attrib["lat"]) - -27.47) < 1e-6
        assert abs(float(point.attrib["lon"]) - 153.02) < 1e-6
        assert abs(float(point.attrib["hae"]) - 100.5) < 1e-6

    def test_decoded_xml_preserves_named_detail_submessages(self):
        datagram = _build_takproto_datagram(callsign="Chaos1")
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        detail = root.find("detail")
        assert detail is not None

        contact = detail.find("contact")
        assert contact is not None
        assert contact.attrib["callsign"] == "Chaos1"
        assert contact.attrib["endpoint"] == "10.0.50.20:4242:tcp"

        group = detail.find("__group")
        assert group is not None
        assert group.attrib["name"] == "Green"
        assert group.attrib["role"] == "Team Member"

        takv = detail.find("takv")
        assert takv is not None
        assert takv.attrib["platform"] == "ATAK"

        status = detail.find("status")
        assert status is not None
        assert status.attrib["battery"] == "87"

        track = detail.find("track")
        assert track is not None
        # Speed and course should be present as numeric strings
        assert float(track.attrib["speed"]) == pytest.approx(1.5)
        assert float(track.attrib["course"]) == pytest.approx(180.0)

    def test_decoded_xml_preserves_xml_detail_children(self):
        # The Droid <uid/> child is carried by xmlDetail in the protobuf
        # and must survive the round-trip.
        datagram = _build_takproto_datagram(callsign="Chaos1")
        xml = _takproto_to_cot_xml(datagram)
        root = ET.fromstring(xml)
        droid = root.find("./detail/uid")
        assert droid is not None
        assert droid.attrib["Droid"] == "Chaos1"

    def test_decoded_xml_round_trips_through_validator(self):
        datagram = _build_takproto_datagram()
        plugin = _make_plugin()
        xml = _takproto_to_cot_xml(datagram)
        assert plugin._is_cot_event(xml) is True

    def test_decode_raises_on_garbage(self):
        with pytest.raises(ValueError):
            _takproto_to_cot_xml(b"\xbf\x01\xbfnot a protobuf")


# ---------------------------------------------------------------------------
# format config field and auto-detect routing
# ---------------------------------------------------------------------------


class TestFormatRouting:
    def test_format_field_present_in_metadata(self):
        plugin = _make_plugin()
        names = [f.name for f in plugin.get_config_fields()]
        assert "format" in names

    def test_format_field_options(self):
        plugin = _make_plugin()
        field = next(f for f in plugin.get_config_fields() if f.name == "format")
        assert field.field_type == "select"
        labels = {opt["value"] for opt in field.options}
        assert {"xml", "takproto", "auto"} <= labels

    async def test_auto_detects_xml(self):
        plugin = _make_plugin({"format": "auto"})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))

        # XML forwarded verbatim
        first = plugin._cot_service.enqueue_event.await_args_list[0].args
        assert first[0] == VALID_COT

    async def test_auto_detects_takproto_and_decodes(self):
        datagram = _build_takproto_datagram(uid="ANDROID-xyz")
        plugin = _make_plugin({"format": "auto"})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(datagram, ("10.0.0.5", 6969))

        # Two TAK servers; both get the decoded XML, not the raw protobuf
        assert plugin._cot_service.enqueue_event.await_count == 2
        sent_bytes = plugin._cot_service.enqueue_event.await_args_list[0].args[0]
        assert sent_bytes.startswith(b"<event")
        assert b"ANDROID-xyz" in sent_bytes
        assert plugin._forwarded == 2

    async def test_format_takproto_rejects_xml(self):
        plugin = _make_plugin({"format": "takproto"})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(VALID_COT, ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()
        assert plugin._dropped_validation == 1

    async def test_format_xml_rejects_takproto(self):
        datagram = _build_takproto_datagram()
        plugin = _make_plugin({"format": "xml"})
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(datagram, ("10.0.0.5", 6969))

        plugin._cot_service.enqueue_event.assert_not_awaited()
        assert plugin._dropped_validation == 1


# ---------------------------------------------------------------------------
# Per-UID forwarded counters (diagnostics for silent-drop investigation)
# ---------------------------------------------------------------------------


class TestPerUidCounters:
    async def test_increments_per_uid_on_successful_forward(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        # Two distinct UIDs, varying frequencies
        evt_a = VALID_COT  # uid="test-1"
        datagram_b = _build_takproto_datagram(uid="ANDROID-xyz")

        await plugin._handle_datagram(evt_a, ("10.0.0.5", 6969))
        await plugin._handle_datagram(evt_a, ("10.0.0.5", 6969))
        await plugin._handle_datagram(datagram_b, ("10.0.0.6", 6969))

        counts = plugin._forwarded_by_uid
        # Two TAK servers, so each forward increments by 2 per server
        assert counts.get("test-1") == 2 * 2
        assert counts.get("ANDROID-xyz") == 1 * 2

    async def test_no_uid_increment_for_dropped_validation(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        await plugin._handle_datagram(b"<event ", ("10.0.0.5", 6969))

        assert plugin._forwarded_by_uid == {}

    async def test_capped_at_soft_limit(self):
        plugin = _make_plugin()
        plugin._cot_service = MagicMock(enqueue_event=AsyncMock(return_value=True))
        plugin._target_servers = plugin.stream.get_active_tak_servers()

        # Soft cap protects memory under wide UID fan-out.
        cap = plugin._UID_COUNTER_SOFT_CAP
        for i in range(cap + 5):
            evt = (
                f'<event version="2.0" uid="dev-{i}" type="a-f-G-U-C" '
                f'how="m-g" time="2026-06-29T00:00:00Z" '
                f'start="2026-06-29T00:00:00Z" '
                f'stale="2026-06-29T00:05:00Z">'
                f'<point lat="0" lon="0" hae="0" ce="0" le="0"/>'
                f"</event>"
            ).encode()
            await plugin._handle_datagram(evt, ("10.0.0.5", 6969))

        # Dict size doesn't blow past the cap.
        assert len(plugin._forwarded_by_uid) <= cap
