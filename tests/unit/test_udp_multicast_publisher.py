# ABOUTME: Unit tests for the UdpMulticastPublisher output plugin.
# ABOUTME: Covers metadata, socket lifecycle, CoT publishing, takproto encoding,
# ABOUTME: and echo-loop prevention.

import socket
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Sample CoT XML used across tests
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = (
    b'<event version="2.0" uid="ANDROID-device1" type="a-f-G-U-C" how="m-g"'
    b' time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"'
    b' stale="2026-04-11T12:05:00Z">'
    b'<point lat="-27.47" lon="153.02" hae="0" ce="9999999" le="9999999"/>'
    b"</event>"
)

OVERSIZED_COT_XML = b"<event/>" + b"x" * 70000

MINIMAL_CONFIG = {
    "multicast_group": "239.2.3.1",
    "multicast_port": 6969,
    "multicast_ttl": 1,
    "bind_interface": "0.0.0.0",
    "output_format": "xml",
    "max_packet_bytes": 65535,
    "drop_own_uid": True,
}


def _make_plugin(overrides=None):
    from plugins.udp_multicast_publisher import UdpMulticastPublisher

    config = {**MINIMAL_CONFIG, **(overrides or {})}
    return UdpMulticastPublisher(config)


# ===========================================================================
# Metadata and registration
# ===========================================================================


class TestMetadata:
    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "udp_multicast_publisher"

    def test_get_plugin_name_classmethod(self):
        from plugins.udp_multicast_publisher import UdpMulticastPublisher

        assert (
            UdpMulticastPublisher.get_plugin_name() == "udp_multicast_publisher"
        )

    def test_category_is_output(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "forwarding"

    def test_has_display_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata.get("display_name")

    def test_config_fields_present(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = {f.name for f in fields}
        required = {
            "multicast_group",
            "multicast_port",
            "multicast_ttl",
            "bind_interface",
            "output_format",
            "max_packet_bytes",
            "drop_own_uid",
        }
        assert required.issubset(names), f"Missing fields: {required - names}"


# ===========================================================================
# Socket lifecycle — start() / cleanup()
# ===========================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_opens_socket_with_ttl(self):
        plugin = _make_plugin({"multicast_ttl": 3})
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()

        # TTL setsockopt called with correct value
        ttl_call = call(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 3)
        assert ttl_call in mock_sock.setsockopt.call_args_list

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_sets_multicast_if_when_bind_interface_not_default(
        self,
    ):
        plugin = _make_plugin({"bind_interface": "10.0.30.65"})
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()

        packed_if = socket.inet_aton("10.0.30.65")
        iface_call = call(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, packed_if)
        assert iface_call in mock_sock.setsockopt.call_args_list

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_does_not_set_multicast_if_when_default(self):
        plugin = _make_plugin({"bind_interface": "0.0.0.0"})
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()

        call_args = [c[0] for c in mock_sock.setsockopt.call_args_list]
        assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF) not in [
            (a[0], a[1]) for a in call_args
        ]

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_closes_socket(self):
        plugin = _make_plugin()
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.cleanup()

        mock_sock.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_is_idempotent(self):
        plugin = _make_plugin()
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.cleanup()
            await plugin.cleanup()  # second cleanup should not raise

        assert mock_sock.close.call_count == 1


# ===========================================================================
# handle_cot_message — happy path
# ===========================================================================


class TestHandleCotPublishes:
    @pytest.mark.asyncio
    async def test_publishes_xml_to_group(self):
        plugin = _make_plugin()
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        mock_sock.sendto.assert_called_once_with(
            SAMPLE_COT_XML, ("239.2.3.1", 6969)
        )

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_publishes_to_configured_group_and_port(self):
        plugin = _make_plugin(
            {"multicast_group": "239.1.2.3", "multicast_port": 4242}
        )
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        mock_sock.sendto.assert_called_once_with(
            SAMPLE_COT_XML, ("239.1.2.3", 4242)
        )

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_events_sent_counter_incremented(self):
        plugin = _make_plugin()
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        assert plugin._events_sent == 1

        await plugin.cleanup()


# ===========================================================================
# handle_cot_message — drop own UID (echo-loop prevention)
# ===========================================================================


class TestDropOwnUid:
    @pytest.mark.asyncio
    async def test_drops_event_with_matching_own_uid(self):
        plugin = _make_plugin({"drop_own_uid": True})
        plugin._own_uids.add("ANDROID-device1")
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        mock_sock.sendto.assert_not_called()
        assert plugin._events_dropped == 1

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_forwards_event_when_drop_own_uid_disabled(self):
        plugin = _make_plugin({"drop_own_uid": False})
        plugin._own_uids.add("ANDROID-device1")
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        mock_sock.sendto.assert_called_once()

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_registers_own_uid_from_tak_server(self):
        """start() registers identity UID from the TAK server if available."""
        plugin = _make_plugin()
        mock_sock = MagicMock()
        mock_stream = MagicMock()
        mock_server = MagicMock()
        mock_server.id = 1
        mock_server.uid = "TB-IDENTITY-001"
        mock_stream.get_active_tak_servers.return_value = [mock_server]
        plugin.stream = mock_stream

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()

        assert "TB-IDENTITY-001" in plugin._own_uids

        await plugin.cleanup()


# ===========================================================================
# handle_cot_message — oversized drop
# ===========================================================================


class TestOversizedDrop:
    @pytest.mark.asyncio
    async def test_drops_oversized_payload(self):
        plugin = _make_plugin({"max_packet_bytes": 100})
        big_xml = b"<event/>" + b"x" * 200
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(big_xml, tak_server_id=1)

        mock_sock.sendto.assert_not_called()
        assert plugin._events_dropped == 1

        await plugin.cleanup()


# ===========================================================================
# TAK Protocol v1 encoding
# ===========================================================================


class TestTakprotoEncoding:
    @pytest.mark.asyncio
    async def test_encodes_to_takproto_when_format_takproto(self):
        plugin = _make_plugin({"output_format": "takproto"})
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        assert mock_sock.sendto.called
        sent_payload = mock_sock.sendto.call_args[0][0]
        # TAK Protocol v1 magic prefix
        assert sent_payload[:3] == b"\xbf\x01\xbf"

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_sends_xml_verbatim_when_format_xml(self):
        plugin = _make_plugin({"output_format": "xml"})
        mock_sock = MagicMock()

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        sent_payload = mock_sock.sendto.call_args[0][0]
        assert sent_payload == SAMPLE_COT_XML

        await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_drops_and_logs_warn_when_takproto_encode_fails(self):
        plugin = _make_plugin({"output_format": "takproto"})
        mock_sock = MagicMock()
        # xml2proto raises ParseError on non-XML input
        malformed = b"not xml at all !!!"

        with patch("socket.socket", return_value=mock_sock):
            await plugin.start()
            await plugin.handle_cot_message(malformed, tak_server_id=1)

        # Malformed XML cannot be encoded to takproto; event should be dropped
        mock_sock.sendto.assert_not_called()
        assert plugin._events_dropped == 1

        await plugin.cleanup()


# ===========================================================================
# No-socket guard — handle_cot_message before start()
# ===========================================================================


class TestNoSocketGuard:
    @pytest.mark.asyncio
    async def test_handle_cot_before_start_does_not_raise(self):
        plugin = _make_plugin()
        # Should silently do nothing — no socket yet
        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert plugin._events_dropped == 0
        assert plugin._events_sent == 0


# ===========================================================================
# Discovery
# ===========================================================================


class TestDiscovery:
    def test_plugin_is_discoverable(self):
        """Plugin class must be importable and expose PLUGIN_NAME."""
        from plugins.udp_multicast_publisher import UdpMulticastPublisher

        assert UdpMulticastPublisher.PLUGIN_NAME == "udp_multicast_publisher"
