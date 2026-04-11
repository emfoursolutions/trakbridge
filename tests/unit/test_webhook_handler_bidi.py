# ABOUTME: Unit tests for bidirectional mode of the WebhookHandler plugin (Phase 8).
# ABOUTME: Covers WebSocket and MQTT inbound receive paths, field mapping, and error isolation.

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sample inbound JSON payloads from external systems
# ---------------------------------------------------------------------------
SAMPLE_INBOUND_JSON = json.dumps({
    "uid": "drone-1",
    "callsign": "UAS-ALPHA",
    "lat": 38.897,
    "lon": -77.036,
    "speed": 15.5,
    "course": 270,
}).encode("utf-8")

NESTED_INBOUND_JSON = json.dumps({
    "device": {"id": "sensor-42", "name": "BRAVO"},
    "position": {"latitude": 39.1, "longitude": -76.5, "altitude": 100},
}).encode("utf-8")

INVALID_INBOUND_JSON = b"not valid json at all"

# Location outside valid coordinate bounds
BAD_COORDS_JSON = json.dumps({
    "uid": "bad-1",
    "callsign": "BAD",
    "lat": 999.0,
    "lon": -77.0,
}).encode("utf-8")


# ===================================================================
# Test: Bidi config fields
# ===================================================================
class TestBidiConfigFields:
    """Verify bidirectional config fields appear in metadata."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler
        return WebhookHandler(config or {})

    def test_bidi_field_exists_in_metadata(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "bidirectional" in field_names

    def test_inbound_format_field_exists(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "inbound_format" in field_names

    def test_inbound_field_mapping_fields_exist(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "inbound_lat_field" in field_names
        assert "inbound_lon_field" in field_names
        assert "inbound_uid_field" in field_names

    def test_mqtt_subscribe_topic_field_exists(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "mqtt_subscribe_topic" in field_names

    def test_inbound_cot_type_field_exists(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "inbound_cot_type" in field_names

    def test_inbound_cot_stale_time_field_exists(self):
        handler = self._make_handler()
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "inbound_cot_stale_time" in field_names


# ===================================================================
# Test: Inbound field mapping / parsing
# ===================================================================
class TestBidiFieldMapping:
    """Verify JSON field mapping for inbound messages."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler
        base = {
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "bidirectional": "true",
            "inbound_format": "json",
            "inbound_lat_field": "lat",
            "inbound_lon_field": "lon",
            "inbound_uid_field": "uid",
            "inbound_callsign_field": "callsign",
            "inbound_cot_type": "a-f-G-U-C",
            "inbound_cot_stale_time": "300",
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    def test_parse_flat_json(self):
        handler = self._make_handler()
        locations = handler._parse_inbound_message(SAMPLE_INBOUND_JSON)
        assert len(locations) == 1
        loc = locations[0]
        assert loc["lat"] == 38.897
        assert loc["lon"] == -77.036
        assert loc["uid"] == "drone-1"
        assert loc["callsign"] == "UAS-ALPHA"

    def test_parse_nested_json_with_dot_notation(self):
        handler = self._make_handler({
            "inbound_lat_field": "position.latitude",
            "inbound_lon_field": "position.longitude",
            "inbound_uid_field": "device.id",
            "inbound_callsign_field": "device.name",
        })
        locations = handler._parse_inbound_message(NESTED_INBOUND_JSON)
        assert len(locations) == 1
        loc = locations[0]
        assert loc["lat"] == 39.1
        assert loc["lon"] == -76.5
        assert loc["uid"] == "sensor-42"
        assert loc["callsign"] == "BRAVO"

    def test_parse_invalid_json_returns_empty(self):
        handler = self._make_handler()
        locations = handler._parse_inbound_message(INVALID_INBOUND_JSON)
        assert locations == []

    def test_parse_missing_required_fields_returns_empty(self):
        handler = self._make_handler()
        # JSON missing lat/lon
        msg = json.dumps({"uid": "x", "callsign": "X"}).encode("utf-8")
        locations = handler._parse_inbound_message(msg)
        assert locations == []

    def test_coordinate_validation_rejects_out_of_range(self):
        handler = self._make_handler()
        locations = handler._parse_inbound_message(BAD_COORDS_JSON)
        assert locations == []

    def test_optional_speed_and_course_extracted(self):
        handler = self._make_handler({
            "inbound_speed_field": "speed",
            "inbound_course_field": "course",
        })
        locations = handler._parse_inbound_message(SAMPLE_INBOUND_JSON)
        assert len(locations) == 1
        loc = locations[0]
        assert loc.get("speed") == 15.5
        assert loc.get("course") == 270


# ===================================================================
# Test: WebSocket bidirectional mode
# ===================================================================
class TestWebSocketBidi:
    """Verify WebSocket mode reads inbound messages and processes them."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler
        base = {
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "bidirectional": "true",
            "inbound_format": "json",
            "inbound_lat_field": "lat",
            "inbound_lon_field": "lon",
            "inbound_uid_field": "uid",
            "inbound_callsign_field": "callsign",
            "inbound_cot_type": "a-f-G-U-C",
            "inbound_cot_stale_time": "300",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_bidi_start_creates_reader_task(self):
        handler = self._make_handler()
        with patch.object(
            handler, "_connect_websocket", new_callable=AsyncMock
        ):
            await handler.start()
            assert handler._ws_reader_task is not None

    @pytest.mark.asyncio
    async def test_process_inbound_called_on_valid_message(self):
        handler = self._make_handler()
        handler.stream = MagicMock()
        handler.stream.cot_type = "a-f-G-U-C"
        handler.stream.cot_stale_time = 300
        handler.stream.cot_type_mode = "fixed"

        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.process_inbound_locations = AsyncMock(
                return_value={"success": True, "events_created": 1}
            )
            MockService.return_value = mock_svc

            await handler._handle_inbound_message(SAMPLE_INBOUND_JSON)
            mock_svc.process_inbound_locations.assert_called_once()

            # Check locations passed correctly
            call_args = mock_svc.process_inbound_locations.call_args
            locations = call_args[0][0]
            assert len(locations) == 1
            assert locations[0]["uid"] == "drone-1"

    @pytest.mark.asyncio
    async def test_invalid_inbound_does_not_call_service(self):
        handler = self._make_handler()
        handler.stream = MagicMock()

        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as MockService:
            mock_svc = AsyncMock()
            MockService.return_value = mock_svc

            await handler._handle_inbound_message(INVALID_INBOUND_JSON)
            mock_svc.process_inbound_locations.assert_not_called()

    @pytest.mark.asyncio
    async def test_outbound_still_works_when_bidi_enabled(self):
        """Bidi mode should not break outbound forwarding."""
        handler = self._make_handler()

        sample_cot = b"""<?xml version="1.0" encoding="UTF-8"?>
        <event version="2.0" type="a-f-G-U-C" uid="ANDROID-device1"
               time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
               stale="2026-04-11T12:05:00Z" how="m-g">
          <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
          <detail>
            <contact callsign="ALPHA-1"/>
          </detail>
        </event>"""

        handler._ws_queue = asyncio.Queue(maxsize=100)
        handler._ws_connected = True

        await handler.handle_cot_message(sample_cot, tak_server_id=1)
        assert not handler._ws_queue.empty()


# ===================================================================
# Test: WebSocket bidi error isolation
# ===================================================================
class TestWebSocketBidiErrorIsolation:
    """Verify inbound parse errors don't affect outbound."""

    def _make_handler(self):
        from plugins.webhook_handler import WebhookHandler
        return WebhookHandler({
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "bidirectional": "true",
            "inbound_format": "json",
            "inbound_lat_field": "lat",
            "inbound_lon_field": "lon",
            "inbound_uid_field": "uid",
            "inbound_callsign_field": "callsign",
            "inbound_cot_type": "a-f-G-U-C",
            "inbound_cot_stale_time": "300",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })

    @pytest.mark.asyncio
    async def test_inbound_error_does_not_raise(self):
        handler = self._make_handler()
        handler.stream = MagicMock()

        # Process bad inbound data — should not raise
        await handler._handle_inbound_message(b"garbage data")

    @pytest.mark.asyncio
    async def test_inbound_service_error_isolated(self):
        handler = self._make_handler()
        handler.stream = MagicMock()
        handler.stream.cot_type = "a-f-G-U-C"
        handler.stream.cot_stale_time = 300
        handler.stream.cot_type_mode = "fixed"

        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.process_inbound_locations = AsyncMock(
                side_effect=Exception("TAK server down")
            )
            MockService.return_value = mock_svc

            # Should not raise despite service error
            await handler._handle_inbound_message(SAMPLE_INBOUND_JSON)


# ===================================================================
# Test: MQTT bidirectional mode
# ===================================================================
class TestMQTTBidi:
    """Verify MQTT mode subscribes and processes inbound messages."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler
        base = {
            "endpoint_url": "mqtt://broker.example.com:1883",
            "delivery_mode": "mqtt",
            "bidirectional": "true",
            "inbound_format": "json",
            "inbound_lat_field": "lat",
            "inbound_lon_field": "lon",
            "inbound_uid_field": "uid",
            "inbound_callsign_field": "callsign",
            "inbound_cot_type": "a-f-G-U-C",
            "inbound_cot_stale_time": "300",
            "mqtt_topic": "trakbridge/outbound",
            "mqtt_subscribe_topic": "trakbridge/inbound",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_mqtt_bidi_subscribes_on_connect(self):
        import sys

        handler = self._make_handler()

        mock_client_instance = MagicMock()
        mock_client_cls = MagicMock(return_value=mock_client_instance)
        mock_paho_module = MagicMock()
        mock_paho_module.Client = mock_client_cls

        mock_paho = MagicMock()
        mock_paho_mqtt = MagicMock()
        mock_paho.mqtt = mock_paho_mqtt
        mock_paho_mqtt.client = mock_paho_module

        with patch.dict(sys.modules, {
            "paho": mock_paho,
            "paho.mqtt": mock_paho_mqtt,
            "paho.mqtt.client": mock_paho_module,
        }):
            await handler._connect_mqtt()

            # Simulate on_connect callback
            on_connect = mock_client_instance.on_connect
            on_connect(mock_client_instance, None, {}, 0)

            # Should subscribe to the inbound topic
            mock_client_instance.subscribe.assert_called_once_with(
                "trakbridge/inbound"
            )

    @pytest.mark.asyncio
    async def test_mqtt_on_message_processes_inbound(self):
        handler = self._make_handler()
        handler.stream = MagicMock()
        handler.stream.cot_type = "a-f-G-U-C"
        handler.stream.cot_stale_time = 300
        handler.stream.cot_type_mode = "fixed"

        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.process_inbound_locations = AsyncMock(
                return_value={"success": True, "events_created": 1}
            )
            MockService.return_value = mock_svc

            # Simulate MQTT message
            mock_msg = MagicMock()
            mock_msg.payload = SAMPLE_INBOUND_JSON
            mock_msg.topic = "trakbridge/inbound"

            await handler._handle_inbound_message(mock_msg.payload)
            mock_svc.process_inbound_locations.assert_called_once()

    @pytest.mark.asyncio
    async def test_mqtt_outbound_still_works_with_bidi(self):
        handler = self._make_handler()
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        handler._mqtt_client = mock_client
        handler._mqtt_connected = True

        sample_cot = b"""<?xml version="1.0" encoding="UTF-8"?>
        <event version="2.0" type="a-f-G-U-C" uid="device-1"
               time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
               stale="2026-04-11T12:05:00Z" how="m-g">
          <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
          <detail><contact callsign="ALPHA-1"/></detail>
        </event>"""

        await handler.handle_cot_message(sample_cot, tak_server_id=1)
        mock_client.publish.assert_called_once()


# ===================================================================
# Test: Bidi health stats
# ===================================================================
class TestBidiHealthStats:
    """Verify health stats include inbound metrics."""

    def _make_handler(self):
        from plugins.webhook_handler import WebhookHandler
        return WebhookHandler({
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "bidirectional": "true",
        })

    def test_health_stats_include_inbound_received(self):
        handler = self._make_handler()
        stats = handler.get_health_stats()
        assert "inbound_received" in stats
        assert stats["inbound_received"] == 0

    @pytest.mark.asyncio
    async def test_inbound_received_increments(self):
        handler = self._make_handler()
        handler.stream = MagicMock()
        handler.stream.cot_type = "a-f-G-U-C"
        handler.stream.cot_stale_time = 300
        handler.stream.cot_type_mode = "fixed"

        handler.config.update({
            "inbound_lat_field": "lat",
            "inbound_lon_field": "lon",
            "inbound_uid_field": "uid",
            "inbound_callsign_field": "callsign",
            "inbound_cot_type": "a-f-G-U-C",
            "inbound_cot_stale_time": "300",
        })

        with patch(
            "services.inbound_cot_service.InboundCOTService"
        ) as MockService:
            mock_svc = AsyncMock()
            mock_svc.process_inbound_locations = AsyncMock(
                return_value={"success": True, "events_created": 1}
            )
            MockService.return_value = mock_svc

            await handler._handle_inbound_message(SAMPLE_INBOUND_JSON)

            stats = handler.get_health_stats()
            assert stats["inbound_received"] == 1
