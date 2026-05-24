# ABOUTME: Unit tests for the InboundReceiver plugin.
# ABOUTME: Covers metadata, URL parsing, message handling, field mapping, health stats.

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(config: dict = None):
    from plugins.inbound_receiver import InboundReceiver

    return InboundReceiver(config or {})


def _make_stream(stream_id: int = 1):
    stream = MagicMock()
    stream.id = stream_id
    stream.ca_cert = None
    tak = MagicMock()
    tak.cert_p12 = None
    stream.tak_server = tak
    return stream


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===================================================================
# Metadata
# ===================================================================

class TestInboundReceiverMetadata:
    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "inbound_receiver"

    def test_plugin_category_is_output(self):
        plugin = _make_plugin()
        meta = plugin.plugin_metadata
        assert meta["category"] == "output"

    def test_plugin_has_display_name(self):
        plugin = _make_plugin()
        assert "display_name" in plugin.plugin_metadata

    def test_plugin_has_description(self):
        plugin = _make_plugin()
        assert "description" in plugin.plugin_metadata

    def test_plugin_has_help_sections(self):
        plugin = _make_plugin()
        sections = plugin.plugin_metadata.get("help_sections", [])
        assert len(sections) >= 1
        titles = [s["title"] for s in sections]
        assert "Overview" in titles

    def test_config_fields_present(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        assert "source_url" in names
        assert "transport" in names
        assert "lat_field" in names
        assert "lon_field" in names
        assert "uid_field" in names
        assert "callsign_field" in names
        assert "cot_type" in names
        assert "cot_stale_time" in names

    def test_mqtt_fields_have_depends_on_transport(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        mqtt_only = [
            f for f in fields
            if getattr(f, "depends_on", None)
            and f.depends_on.get("field") == "transport"
        ]
        mqtt_names = [f.name for f in mqtt_only]
        assert "mqtt_subscribe_topic" in mqtt_names
        assert "mqtt_client_id" in mqtt_names
        assert "mqtt_username" in mqtt_names
        assert "mqtt_password" in mqtt_names
        assert "ca_source" in mqtt_names

    def test_transport_field_options(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        transport_field = next(
            f for f in fields if f.name == "transport"
        )
        values = [o["value"] for o in transport_field.options]
        assert "mqtt" in values
        assert "websocket" in values

    def test_ca_source_options(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        ca_field = next(f for f in fields if f.name == "ca_source")
        values = [o["value"] for o in ca_field.options]
        assert "system" in values
        assert "tak_server" in values
        assert "upload" in values
        assert "custom" not in values

    def test_mqtt_password_is_password_type(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        pw_field = next(
            f for f in fields if f.name == "mqtt_password"
        )
        assert pw_field.field_type == "password"

    def test_mqtt_password_is_sensitive(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        pw_field = next(
            f for f in fields if f.name == "mqtt_password"
        )
        assert pw_field.sensitive is True

    def test_default_cot_type(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        cot_field = next(f for f in fields if f.name == "cot_type")
        assert cot_field.default_value == "a-f-G-U-C"

    def test_default_cot_stale_time(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        stale_field = next(
            f for f in fields if f.name == "cot_stale_time"
        )
        assert int(stale_field.default_value) == 300


# ===================================================================
# handle_cot_message — receive-only no-op
# ===================================================================

class TestHandleCotMessage:
    async def test_handle_cot_message_returns_none(self):
        plugin = _make_plugin()
        result = await plugin.handle_cot_message(b"<event/>", 1)
        assert result is None


# ===================================================================
# _parse_url
# ===================================================================

class TestParseUrl:
    def test_mqtt_plain(self):
        plugin = _make_plugin()
        host, port, tls = plugin._parse_url(
            "mqtt://broker.example.com:1883"
        )
        assert host == "broker.example.com"
        assert port == 1883
        assert tls is False

    def test_mqtts_tls(self):
        plugin = _make_plugin()
        host, port, tls = plugin._parse_url(
            "mqtts://broker.example.com:8883"
        )
        assert host == "broker.example.com"
        assert port == 8883
        assert tls is True

    def test_ws_plain(self):
        plugin = _make_plugin()
        host, port, tls = plugin._parse_url(
            "ws://realtime.example.com:9001"
        )
        assert host == "realtime.example.com"
        assert port == 9001
        assert tls is False

    def test_wss_tls(self):
        plugin = _make_plugin()
        host, port, tls = plugin._parse_url(
            "wss://realtime.example.com:443"
        )
        assert host == "realtime.example.com"
        assert port == 443
        assert tls is True

    def test_mqtt_default_port_when_omitted(self):
        plugin = _make_plugin()
        _, port, tls = plugin._parse_url("mqtt://broker.example.com")
        assert port == 1883
        assert tls is False

    def test_mqtts_default_port_when_omitted(self):
        plugin = _make_plugin()
        _, port, tls = plugin._parse_url("mqtts://broker.example.com")
        assert port == 8883
        assert tls is True


# ===================================================================
# _resolve_path
# ===================================================================

class TestResolvePath:
    def test_top_level_key(self):
        plugin = _make_plugin()
        data = {"lat": 38.9, "lon": -77.0}
        assert plugin._resolve_path(data, "lat") == 38.9

    def test_nested_path(self):
        plugin = _make_plugin()
        data = {"position": {"latitude": 38.9, "longitude": -77.0}}
        assert plugin._resolve_path(data, "position.latitude") == 38.9

    def test_deeply_nested(self):
        plugin = _make_plugin()
        data = {"a": {"b": {"c": 42}}}
        assert plugin._resolve_path(data, "a.b.c") == 42

    def test_missing_key_returns_none(self):
        plugin = _make_plugin()
        data = {"lat": 38.9}
        assert plugin._resolve_path(data, "lon") is None

    def test_missing_nested_key_returns_none(self):
        plugin = _make_plugin()
        data = {"position": {}}
        assert plugin._resolve_path(data, "position.latitude") is None

    def test_non_dict_midpath_returns_none(self):
        plugin = _make_plugin()
        data = {"position": "not-a-dict"}
        assert plugin._resolve_path(data, "position.latitude") is None


# ===================================================================
# _handle_message
# ===================================================================

def _base_config():
    return {
        "lat_field": "lat",
        "lon_field": "lon",
        "uid_field": "uid",
        "callsign_field": "callsign",
        "cot_type": "a-f-G-U-C",
        "cot_stale_time": 300,
    }


def _location_payload(**overrides):
    data = {"lat": 38.9, "lon": -77.0, "uid": "device-1", "callsign": "ALPHA"}
    data.update(overrides)
    return json.dumps(data).encode()


class TestHandleMessage:
    def test_valid_message_dispatches_to_inbound_service(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = _make_stream()

        mock_service = MagicMock()
        mock_service.process_inbound_locations = AsyncMock(
            return_value={"success": True, "events_created": 1}
        )

        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(_location_payload()))

        assert plugin._messages_received == 1
        assert plugin._messages_failed == 0

    def test_invalid_json_increments_failed(self):
        plugin = _make_plugin()
        _run(plugin._handle_message(b"not json at all {{{"))
        assert plugin._messages_failed == 1
        assert plugin._messages_received == 0

    def test_missing_lat_field_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps({"lon": -77.0, "uid": "dev-1"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_missing_lon_field_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps({"lat": 38.9, "uid": "dev-1"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_missing_uid_field_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps({"lat": 38.9, "lon": -77.0}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_non_numeric_lat_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps(
            {"lat": "bad", "lon": -77.0, "uid": "dev-1"}
        ).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_lat_out_of_range_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps(
            {"lat": 91.0, "lon": -77.0, "uid": "dev-1"}
        ).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_lon_out_of_range_increments_failed(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        raw = json.dumps(
            {"lat": 38.9, "lon": 181.0, "uid": "dev-1"}
        ).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_uid_fallback_used_as_callsign(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = _make_stream()

        captured = {}

        async def fake_process(locations, stream):
            captured["callsign"] = locations[0]["callsign"]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        # No callsign in payload — should fall back to uid
        raw = json.dumps(
            {"lat": 38.9, "lon": -77.0, "uid": "device-99"}
        ).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert captured.get("callsign") == "device-99"

    def test_speed_and_course_included_when_present(self):
        config = {**_base_config(), "speed_field": "speed", "course_field": "course"}
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()

        captured = {}

        async def fake_process(locations, stream):
            captured["location"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "lat": 38.9, "lon": -77.0, "uid": "dev-1",
            "callsign": "ALPHA", "speed": 5.5, "course": 90,
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        loc = captured.get("location", {})
        assert loc.get("speed") == 5.5
        assert loc.get("course") == 90

    def test_no_stream_context_skips_dispatch(self):
        cfg = {"lat_field": "lat", "lon_field": "lon", "uid_field": "uid"}
        plugin = _make_plugin(cfg)
        plugin.stream = None

        raw = json.dumps({"lat": 38.9, "lon": -77.0, "uid": "dev-1"}).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as mock_cls:
            _run(plugin._handle_message(raw))
            mock_cls.assert_not_called()

    def test_nested_field_mapping(self):
        config = {
            "lat_field": "position.latitude",
            "lon_field": "position.longitude",
            "uid_field": "device.id",
            "callsign_field": "device.name",
            "cot_type": "a-f-G-U-C",
            "cot_stale_time": 300,
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()

        captured = {}

        async def fake_process(locations, stream):
            captured["location"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "position": {"latitude": 38.9, "longitude": -77.0},
            "device": {"id": "nested-dev", "name": "NestUnit"},
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        loc = captured.get("location", {})
        assert loc.get("lat") == 38.9
        assert loc.get("uid") == "nested-dev"
        assert loc.get("callsign") == "NestUnit"


# ===================================================================
# get_health_stats
# ===================================================================

class TestGetHealthStats:
    def test_mqtt_transport_stats(self):
        plugin = _make_plugin({"transport": "mqtt"})
        stats = plugin.get_health_stats()
        assert stats["transport"] == "mqtt"
        assert "connected" in stats
        assert "messages_received" in stats
        assert "messages_failed" in stats

    def test_websocket_transport_stats(self):
        plugin = _make_plugin({"transport": "websocket"})
        stats = plugin.get_health_stats()
        assert stats["transport"] == "websocket"
        assert "connected" in stats

    def test_initial_counters_zero(self):
        plugin = _make_plugin({"transport": "mqtt"})
        stats = plugin.get_health_stats()
        assert stats["messages_received"] == 0
        assert stats["messages_failed"] == 0


# ===================================================================
# test_connection
# ===================================================================

class TestTestConnection:
    def test_returns_success_when_url_provided(self):
        plugin = _make_plugin({
            "source_url": "mqtt://broker.example.com:1883",
            "transport": "mqtt",
        })
        result = _run(plugin.test_connection())
        assert result["success"] is True

    def test_returns_failure_when_url_missing(self):
        plugin = _make_plugin({"transport": "mqtt"})
        result = _run(plugin.test_connection())
        assert result["success"] is False
        assert "error" in result

    def test_message_mentions_transport(self):
        plugin = _make_plugin({
            "source_url": "ws://realtime.example.com:9001",
            "transport": "websocket",
        })
        result = _run(plugin.test_connection())
        assert result["success"] is True
        assert "websocket" in result.get("message", "").lower()
