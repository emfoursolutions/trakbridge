# ABOUTME: Unit tests for the InboundActive plugin.
# ABOUTME: Covers metadata, URL parsing, message handling, and health stats.

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.inbound_active import InboundActive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(config: dict = None):
    return InboundActive(config or {})


def _make_stream(stream_id: int = 1):
    stream = MagicMock()
    stream.id = stream_id
    stream.ca_cert = None
    tak = MagicMock()
    tak.cert_p12 = None
    stream.tak_server = tak
    return stream


def _base_config():
    return {
        "lat_field": "lat",
        "lon_field": "lon",
        "uid_field": "uid",
        "callsign_field": "callsign",
        "cot_type": "a-f-G-U-C",
        "cot_stale_time": 300,
    }


def _run(coro):
    return asyncio.run(coro)


# ===================================================================
# Metadata
# ===================================================================

class TestInboundActiveMetadata:
    def test_plugin_name(self):
        assert _make_plugin().plugin_name == "inbound_active"

    def test_category_is_inbound(self):
        assert _make_plugin().plugin_metadata["category"] == "inbound"

    def test_has_display_name(self):
        assert "display_name" in _make_plugin().plugin_metadata

    def test_class_method_get_plugin_name(self):
        assert InboundActive.get_plugin_name() == "inbound_active"

    def test_config_fields_present(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        for name in (
            "source_url", "transport", "lat_field", "lon_field",
            "uid_field", "callsign_field", "cot_type", "cot_stale_time",
        ):
            assert name in names

    def test_mqtt_fields_have_depends_on(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        mqtt_only = [
            f for f in fields
            if getattr(f, "depends_on", None)
            and f.depends_on.get("field") == "transport"
        ]
        names = [f.name for f in mqtt_only]
        assert "mqtt_subscribe_topic" in names
        assert "mqtt_client_id" in names
        assert "mqtt_password" in names
        assert "ca_source" in names

    def test_transport_options(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        transport = next(f for f in fields if f.name == "transport")
        values = [o["value"] for o in transport.options]
        assert "mqtt" in values
        assert "websocket" in values

    def test_ca_source_no_custom_option(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        ca = next(f for f in fields if f.name == "ca_source")
        values = [o["value"] for o in ca.options]
        assert "upload" in values
        assert "custom" not in values

    def test_mqtt_password_is_sensitive(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        pw = next(f for f in fields if f.name == "mqtt_password")
        assert pw.sensitive is True
        assert pw.field_type == "password"


# ===================================================================
# transform_payload — not supported for active-connect plugins
# ===================================================================

class TestTransformPayloadNotSupported:
    def test_raises_not_implemented_error(self):
        plugin = _make_plugin()
        with pytest.raises(NotImplementedError):
            plugin.transform_payload(b"{}", "application/json", {})


# ===================================================================
# _parse_url
# ===================================================================

class TestParseUrl:
    def test_mqtt_plain(self):
        h, p, tls = _make_plugin()._parse_url("mqtt://broker.example.com:1883")
        assert h == "broker.example.com"
        assert p == 1883
        assert tls is False

    def test_mqtts_tls(self):
        h, p, tls = _make_plugin()._parse_url(
            "mqtts://broker.example.com:8883"
        )
        assert h == "broker.example.com"
        assert p == 8883
        assert tls is True

    def test_ws_plain(self):
        h, p, tls = _make_plugin()._parse_url("ws://rt.example.com:9001")
        assert h == "rt.example.com"
        assert p == 9001
        assert tls is False

    def test_wss_tls(self):
        h, p, tls = _make_plugin()._parse_url("wss://rt.example.com:443")
        assert h == "rt.example.com"
        assert p == 443
        assert tls is True

    def test_mqtt_default_port_when_omitted(self):
        _, p, tls = _make_plugin()._parse_url("mqtt://broker.example.com")
        assert p == 1883
        assert tls is False

    def test_mqtts_default_port_when_omitted(self):
        _, p, tls = _make_plugin()._parse_url("mqtts://broker.example.com")
        assert p == 8883
        assert tls is True


# ===================================================================
# _resolve_path
# ===================================================================

class TestResolvePath:
    def test_top_level_key(self):
        assert _make_plugin()._resolve_path({"lat": 38.9}, "lat") == 38.9

    def test_nested_path(self):
        data = {"position": {"latitude": 38.9}}
        assert _make_plugin()._resolve_path(data, "position.latitude") == 38.9

    def test_missing_key_returns_none(self):
        assert _make_plugin()._resolve_path({"lat": 38.9}, "lon") is None

    def test_non_dict_midpath_returns_none(self):
        assert _make_plugin()._resolve_path(
            {"position": "not-a-dict"}, "position.latitude"
        ) is None


# ===================================================================
# _handle_message
# ===================================================================

class TestHandleMessage:
    def test_valid_message_dispatches_to_inbound_service(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = _make_stream()

        mock_service = MagicMock()
        mock_service.process_inbound_locations = AsyncMock(
            return_value={"success": True, "events_created": 1}
        )

        raw = json.dumps(
            {"lat": 38.9, "lon": -77.0, "uid": "d1", "callsign": "A"}
        ).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert plugin._messages_received == 1
        assert plugin._messages_failed == 0

    def test_invalid_json_increments_failed(self):
        plugin = _make_plugin()
        _run(plugin._handle_message(b"not json {{{"))
        assert plugin._messages_failed == 1
        assert plugin._messages_received == 0

    def test_missing_lat_increments_failed(self):
        plugin = _make_plugin(_base_config())
        raw = json.dumps({"lon": -77.0, "uid": "d"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_missing_lon_increments_failed(self):
        plugin = _make_plugin(_base_config())
        raw = json.dumps({"lat": 38.9, "uid": "d"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_missing_uid_increments_failed(self):
        plugin = _make_plugin(_base_config())
        raw = json.dumps({"lat": 38.9, "lon": -77.0}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_lat_out_of_range_increments_failed(self):
        plugin = _make_plugin(_base_config())
        raw = json.dumps({"lat": 91.0, "lon": -77.0, "uid": "d"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_lon_out_of_range_increments_failed(self):
        plugin = _make_plugin(_base_config())
        raw = json.dumps({"lat": 38.9, "lon": 181.0, "uid": "d"}).encode()
        _run(plugin._handle_message(raw))
        assert plugin._messages_failed == 1

    def test_uid_used_as_callsign_fallback(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["callsign"] = locations[0]["callsign"]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

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
        config = {
            **_base_config(),
            "speed_field": "speed",
            "course_field": "hdg",
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "lat": 38.9, "lon": -77.0, "uid": "d",
            "callsign": "A", "speed": 5.5, "hdg": 90,
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert captured["loc"]["speed"] == 5.5
        assert captured["loc"]["course"] == 90

    def test_no_stream_context_skips_dispatch(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = None
        raw = json.dumps({"lat": 38.9, "lon": -77.0, "uid": "d"}).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as mock_cls:
            _run(plugin._handle_message(raw))
            mock_cls.assert_not_called()

    def test_remarks_field_included_when_present(self):
        config = {
            **_base_config(),
            "remarks_field": "status",
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "lat": 38.9, "lon": -77.0, "uid": "d",
            "callsign": "A", "status": "All systems nominal",
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert captured["loc"]["description"] == "All systems nominal"

    def test_remarks_field_nested_path(self):
        config = {
            **_base_config(),
            "remarks_field": "meta.note",
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "lat": 38.9, "lon": -77.0, "uid": "d",
            "meta": {"note": "sector cleared"},
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert captured["loc"]["description"] == "sector cleared"

    def test_remarks_field_absent_from_message_does_not_set_key(self):
        config = {
            **_base_config(),
            "remarks_field": "status",
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({"lat": 38.9, "lon": -77.0, "uid": "d"}).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert "description" not in captured["loc"]

    def test_no_remarks_field_configured_does_not_set_key(self):
        plugin = _make_plugin(_base_config())
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({"lat": 38.9, "lon": -77.0, "uid": "d"}).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert "description" not in captured["loc"]

    def test_nested_field_mapping(self):
        config = {
            "lat_field": "pos.lat",
            "lon_field": "pos.lon",
            "uid_field": "dev.id",
            "callsign_field": "dev.name",
            "cot_type": "a-f-G-U-C",
            "cot_stale_time": 300,
        }
        plugin = _make_plugin(config)
        plugin.stream = _make_stream()
        captured = {}

        async def fake_process(locations, stream, **kwargs):
            captured["loc"] = locations[0]
            return {"success": True, "events_created": 1}

        mock_service = MagicMock()
        mock_service.process_inbound_locations = fake_process

        raw = json.dumps({
            "pos": {"lat": 38.9, "lon": -77.0},
            "dev": {"id": "nested-1", "name": "NestUnit"},
        }).encode()
        with patch(
            "services.inbound_cot_service.InboundCOTService",
            return_value=mock_service,
        ):
            _run(plugin._handle_message(raw))

        assert captured["loc"]["lat"] == 38.9
        assert captured["loc"]["uid"] == "nested-1"
        assert captured["loc"]["callsign"] == "NestUnit"


# ===================================================================
# get_health_stats
# ===================================================================

class TestGetHealthStats:
    def test_mqtt_stats_shape(self):
        plugin = _make_plugin({"transport": "mqtt"})
        stats = plugin.get_health_stats()
        assert stats["transport"] == "mqtt"
        assert "connected" in stats
        assert "messages_received" in stats
        assert "messages_failed" in stats

    def test_websocket_stats_shape(self):
        plugin = _make_plugin({"transport": "websocket"})
        stats = plugin.get_health_stats()
        assert stats["transport"] == "websocket"
        assert "connected" in stats

    def test_initial_counters_zero(self):
        stats = _make_plugin({"transport": "mqtt"}).get_health_stats()
        assert stats["messages_received"] == 0
        assert stats["messages_failed"] == 0


# ===================================================================
# test_connection
# ===================================================================

class TestTestConnection:
    def test_success_when_url_provided(self):
        plugin = _make_plugin({
            "source_url": "mqtt://broker.example.com:1883",
            "transport": "mqtt",
        })
        result = _run(plugin.test_connection())
        assert result["success"] is True

    def test_failure_when_url_missing(self):
        result = _run(_make_plugin({"transport": "mqtt"}).test_connection())
        assert result["success"] is False
        assert "error" in result

    def test_message_mentions_transport(self):
        plugin = _make_plugin({
            "source_url": "ws://rt.example.com:9001",
            "transport": "websocket",
        })
        result = _run(plugin.test_connection())
        assert result["success"] is True
        assert "websocket" in result.get("message", "").lower()


# ===================================================================
# validate_config — source_url scheme enforcement
# ===================================================================

class TestValidateConfig:
    def test_mqtt_url_is_valid(self):
        plugin = _make_plugin({
            "source_url": "mqtt://broker.example.com:1883",
            "transport": "mqtt",
        })
        assert plugin.validate_config() is True

    def test_mqtts_url_is_valid(self):
        plugin = _make_plugin({
            "source_url": "mqtts://broker.example.com:8883",
            "transport": "mqtt",
        })
        assert plugin.validate_config() is True

    def test_ws_url_is_valid(self):
        plugin = _make_plugin({
            "source_url": "ws://rt.example.com:9001",
            "transport": "websocket",
        })
        assert plugin.validate_config() is True

    def test_wss_url_is_valid(self):
        plugin = _make_plugin({
            "source_url": "wss://rt.example.com:443",
            "transport": "websocket",
        })
        assert plugin.validate_config() is True

    def test_http_url_is_rejected(self):
        plugin = _make_plugin({
            "source_url": "http://broker.example.com:1883",
            "transport": "mqtt",
        })
        assert plugin.validate_config() is False

    def test_https_url_is_rejected(self):
        plugin = _make_plugin({
            "source_url": "https://broker.example.com:8883",
            "transport": "mqtt",
        })
        assert plugin.validate_config() is False

    def test_missing_source_url_is_rejected(self):
        plugin = _make_plugin({"transport": "mqtt"})
        assert plugin.validate_config() is False
