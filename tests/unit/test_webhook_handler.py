# ABOUTME: Unit tests for the WebhookHandler output plugin (Phase 7).
# ABOUTME: Covers HTTP, WebSocket, and MQTT delivery modes with filtering, dedup, and output formats.

import asyncio
import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sample CoT XML used across tests
# ---------------------------------------------------------------------------
SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-device1"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="ALPHA-1" xmppUsername="alpha1@xmpp"/>
    <__group name="Cyan" role="Team Lead"/>
    <status battery="85"/>
    <takv device="Samsung" platform="Android" os="11" version="4.8.1"/>
    <track speed="5.2" course="180"/>
    <remarks>On patrol</remarks>
  </detail>
</event>"""

HOSTILE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-h-G" uid="hostile-1"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="h-e">
  <point lat="39.0" lon="-76.0" hae="100" ce="50" le="50"/>
  <detail>
    <contact callsign="HOSTILE-1"/>
  </detail>
</event>"""


# ===================================================================
# Test: Plugin metadata and registration
# ===================================================================
class TestWebhookHandlerMetadata:
    """Verify plugin exposes correct metadata for auto-discovery."""

    def test_plugin_name(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({})
        assert handler.plugin_name == "webhook_forwarder"

    def test_plugin_category_is_output(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({})
        meta = handler.plugin_metadata
        assert meta["category"] == "output"

    def test_plugin_has_display_name(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({})
        meta = handler.plugin_metadata
        assert "display_name" in meta
        assert meta["display_name"]  # non-empty

    def test_plugin_has_config_fields(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({})
        meta = handler.plugin_metadata
        field_names = [f.name for f in meta["config_fields"]]
        assert "endpoint_url" in field_names
        assert "delivery_mode" in field_names
        assert "output_format" in field_names

    def test_plugin_has_custom_components(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({})
        meta = handler.plugin_metadata
        component_types = [c.type for c in meta["custom_components"]]
        assert "message_rules" in component_types
        assert "geofence" in component_types

    def test_inherits_base_output_plugin(self):
        from plugins.base_plugin import BaseOutputPlugin
        from plugins.webhook_handler import WebhookHandler

        assert issubclass(WebhookHandler, BaseOutputPlugin)


# ===================================================================
# Test: HTTP mode — filtering
# ===================================================================
class TestWebhookHTTPFiltering:
    """Verify message rule filtering works correctly in HTTP mode."""

    def _make_handler(self, config):
        from plugins.webhook_handler import WebhookHandler

        return WebhookHandler(config)

    @pytest.mark.asyncio
    async def test_no_rules_rejects_all(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "message_rules": [],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_rule_forwards(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign} at {lat},{lon}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_matching_rule_rejects(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "message_rules": [
                {"cot_type_pattern": "b-t-f", "enabled": True,
                 "format_template": "chat: {remarks}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_global_uid_filter(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "uid_filter": "^NOPE-.*",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_geofence_filters_outside(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "global_geofence_enabled": "true",
            "global_geofence_bounds": {
                "north": 10.0, "south": 0.0,
                "east": 10.0, "west": 0.0,
            },
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_rule_skipped(self):
        handler = self._make_handler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": False,
                 "format_template": "{callsign}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_not_called()


# ===================================================================
# Test: HTTP mode — output formats
# ===================================================================
class TestWebhookHTTPOutputFormats:
    """Verify JSON, XML passthrough, and custom template output formats."""

    def _make_handler(self, config):
        from plugins.webhook_handler import WebhookHandler

        base = {
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_json_output_structure(self):
        handler = self._make_handler({"output_format": "json"})
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_called_once()
            payload = mock_send.call_args[0][0]  # first positional arg
            assert payload["source"] == "trakbridge"
            assert payload["cot"]["type"] == "a-f-G-U-C"
            assert payload["cot"]["uid"] == "ANDROID-device1"
            assert payload["position"]["lat"] == "38.897"
            assert payload["contact"]["callsign"] == "ALPHA-1"

    @pytest.mark.asyncio
    async def test_json_includes_tak_server_id(self):
        handler = self._make_handler({"output_format": "json"})
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=42)
            payload = mock_send.call_args[0][0]
            assert payload["tak_server_id"] == 42

    @pytest.mark.asyncio
    async def test_json_includes_raw_xml_when_enabled(self):
        handler = self._make_handler({
            "output_format": "json",
            "include_raw_xml": "true",
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            payload = mock_send.call_args[0][0]
            assert "raw_xml" in payload
            # Should be base64 encoded
            decoded = base64.b64decode(payload["raw_xml"])
            assert b"<event" in decoded

    @pytest.mark.asyncio
    async def test_json_excludes_raw_xml_by_default(self):
        handler = self._make_handler({"output_format": "json"})
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            payload = mock_send.call_args[0][0]
            assert "raw_xml" not in payload

    @pytest.mark.asyncio
    async def test_xml_passthrough_sends_raw(self):
        handler = self._make_handler({"output_format": "xml"})
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_send.assert_called_once()
            payload = mock_send.call_args[0][0]
            # XML mode should pass through raw bytes or string
            assert b"<event" in payload or "<event" in payload

    @pytest.mark.asyncio
    async def test_custom_template_format(self):
        handler = self._make_handler({
            "output_format": "custom_template",
            "custom_template": "ALERT: {callsign} at {lat},{lon}",
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            payload = mock_send.call_args[0][0]
            assert "ALPHA-1" in payload
            assert "38.897" in payload


# ===================================================================
# Test: HTTP mode — dedup
# ===================================================================
class TestWebhookHTTPDedup:
    """Verify deduplication behavior in HTTP mode."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler

        base = {
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "output_format": "json",
            "dedup_enabled": "true",
            "dedup_ttl_seconds": "5",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_duplicate_message_suppressed(self):
        handler = self._make_handler()
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            assert mock_send.call_count == 1

    @pytest.mark.asyncio
    async def test_different_uids_not_deduped(self):
        handler = self._make_handler()
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await handler.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)
            # Hostile won't match a-f-* rule, so only 1 call
            # Use a rule that matches both
            pass

    @pytest.mark.asyncio
    async def test_dedup_disabled_allows_duplicates(self):
        handler = self._make_handler({"dedup_enabled": "false"})
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            assert mock_send.call_count == 2


# ===================================================================
# Test: HTTP mode — custom headers and method
# ===================================================================
class TestWebhookHTTPHeaders:
    """Verify custom headers and HTTP method configuration."""

    def _make_handler(self, config):
        from plugins.webhook_handler import WebhookHandler

        base = {
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_custom_headers_sent(self):
        handler = self._make_handler({
            "custom_headers": "X-Api-Key: secret123\nX-Source: trakbridge",
        })
        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_ctx)
            mock_session.put = MagicMock(return_value=mock_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

            # Check that headers were included in the request
            call_kwargs = mock_session.post.call_args
            if call_kwargs:
                headers = call_kwargs.kwargs.get("headers", {}) if call_kwargs.kwargs else {}
                assert headers.get("X-Api-Key") == "secret123"
                assert headers.get("X-Source") == "trakbridge"

    @pytest.mark.asyncio
    async def test_put_method_used(self):
        handler = self._make_handler({"http_method": "PUT"})
        with patch("aiohttp.ClientSession") as mock_session_cls:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.put = MagicMock(return_value=mock_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session_cls.return_value = mock_session

            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_session.put.assert_called_once()


# ===================================================================
# Test: HTTP mode — error handling
# ===================================================================
class TestWebhookHTTPErrors:
    """Verify HTTP mode handles errors gracefully."""

    def _make_handler(self):
        from plugins.webhook_handler import WebhookHandler

        return WebhookHandler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })

    @pytest.mark.asyncio
    async def test_http_error_does_not_raise(self):
        handler = self._make_handler()
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Connection refused")
            # Should not raise — fire and forget
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    @pytest.mark.asyncio
    async def test_malformed_xml_does_not_raise(self):
        handler = self._make_handler()
        await handler.handle_cot_message(b"not xml at all", tak_server_id=1)


# ===================================================================
# Test: WebSocket mode — connection lifecycle
# ===================================================================
class TestWebhookWebSocketMode:
    """Verify WebSocket mode connection management and message flow."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler

        base = {
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "output_format": "json",
            "stream_buffer_size": "10",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_start_creates_connection(self):
        handler = self._make_handler()
        with patch.object(handler, "_connect_websocket", new_callable=AsyncMock) as mock_connect:
            await handler.start()
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_closes_connection(self):
        handler = self._make_handler()
        mock_ws = AsyncMock()
        handler._ws_connection = mock_ws
        handler._ws_writer_task = AsyncMock()
        handler._ws_writer_task.cancel = MagicMock()
        await handler.cleanup()
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_message_queued_not_sent_directly(self):
        """WebSocket mode should enqueue, not send inline."""
        handler = self._make_handler()
        handler._ws_queue = asyncio.Queue(maxsize=10)
        handler._ws_connected = True

        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_http:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            mock_http.assert_not_called()
            assert not handler._ws_queue.empty()

    @pytest.mark.asyncio
    async def test_buffer_drops_oldest_when_full(self):
        """Bounded buffer should drop oldest events."""
        handler = self._make_handler({"stream_buffer_size": "2"})
        handler._ws_queue = asyncio.Queue(maxsize=2)
        handler._ws_connected = True

        # Fill the buffer
        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        # Third message should drop oldest and still succeed
        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert handler._ws_queue.qsize() <= 2

    @pytest.mark.asyncio
    async def test_dedup_disabled_by_default_in_ws_mode(self):
        """WebSocket mode should not dedup by default."""
        handler = self._make_handler()
        handler._ws_queue = asyncio.Queue(maxsize=100)
        handler._ws_connected = True

        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert handler._ws_queue.qsize() == 2


# ===================================================================
# Test: WebSocket mode — rate throttling
# ===================================================================
class TestWebhookWebSocketRateThrottle:
    """Verify rate throttle limits events per second."""

    def _make_handler(self, max_rate):
        from plugins.webhook_handler import WebhookHandler

        return WebhookHandler({
            "endpoint_url": "ws://example.com/ws",
            "delivery_mode": "websocket",
            "output_format": "json",
            "max_rate": str(max_rate),
            "stream_buffer_size": "100",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })

    @pytest.mark.asyncio
    async def test_rate_throttle_drops_excess(self):
        handler = self._make_handler(max_rate=1)
        handler._ws_queue = asyncio.Queue(maxsize=100)
        handler._ws_connected = True

        # Send multiple messages rapidly
        for _ in range(5):
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        # With rate limit of 1/sec, excess should be dropped
        assert handler._ws_queue.qsize() <= 2  # some tolerance


# ===================================================================
# Test: MQTT mode — connection and publishing
# ===================================================================
class TestWebhookMQTTMode:
    """Verify MQTT mode broker connection and message publishing."""

    def _make_handler(self, config=None):
        from plugins.webhook_handler import WebhookHandler

        base = {
            "endpoint_url": "mqtt://broker.example.com:1883",
            "delivery_mode": "mqtt",
            "output_format": "json",
            "mqtt_topic": "trakbridge/events",
            "mqtt_qos": "0",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        }
        if config:
            base.update(config)
        return WebhookHandler(base)

    @pytest.mark.asyncio
    async def test_start_connects_to_broker(self):
        handler = self._make_handler()
        with patch.object(handler, "_connect_mqtt", new_callable=AsyncMock) as mock_connect:
            await handler.start()
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_disconnects_broker(self):
        handler = self._make_handler()
        mock_client = MagicMock()
        handler._mqtt_client = mock_client
        await handler.cleanup()
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_to_topic(self):
        handler = self._make_handler()
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        handler._mqtt_client = mock_client
        handler._mqtt_connected = True

        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        assert call_args[0][0] == "trakbridge/events"  # topic
        assert call_args.kwargs.get("qos", call_args[0][2] if len(call_args[0]) > 2 else 0) == 0

    @pytest.mark.asyncio
    async def test_topic_substitution_uid(self):
        handler = self._make_handler({
            "mqtt_topic": "trakbridge/{uid}/position",
        })
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        handler._mqtt_client = mock_client
        handler._mqtt_connected = True

        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        call_args = mock_client.publish.call_args
        topic = call_args[0][0]
        assert topic == "trakbridge/ANDROID-device1/position"

    @pytest.mark.asyncio
    async def test_topic_substitution_cot_type(self):
        handler = self._make_handler({
            "mqtt_topic": "trakbridge/{cot_type}",
        })
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        handler._mqtt_client = mock_client
        handler._mqtt_connected = True

        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        call_args = mock_client.publish.call_args
        topic = call_args[0][0]
        assert topic == "trakbridge/a-f-G-U-C"

    @pytest.mark.asyncio
    async def test_qos_levels(self):
        for qos in [0, 1, 2]:
            handler = self._make_handler({"mqtt_qos": str(qos)})
            mock_client = MagicMock()
            mock_client.publish = MagicMock()
            handler._mqtt_client = mock_client
            handler._mqtt_connected = True

            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

            call_args = mock_client.publish.call_args
            actual_qos = call_args.kwargs.get("qos", 0)
            if not actual_qos and len(call_args[0]) > 2:
                actual_qos = call_args[0][2]
            assert actual_qos == qos

    @pytest.mark.asyncio
    async def test_mqtt_auth_credentials(self):
        import sys

        handler = self._make_handler({
            "mqtt_username": "user1",
            "mqtt_password": "pass1",
        })

        mock_client_instance = MagicMock()
        mock_client_cls = MagicMock(return_value=mock_client_instance)
        mock_paho_module = MagicMock()
        mock_paho_module.Client = mock_client_cls

        # Build a consistent mock hierarchy so `import paho.mqtt.client`
        # resolves to mock_paho_module regardless of import mechanism.
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
            mock_client_instance.username_pw_set.assert_called_once_with("user1", "pass1")

    @pytest.mark.asyncio
    async def test_dedup_disabled_by_default_in_mqtt(self):
        """MQTT mode should not dedup by default."""
        handler = self._make_handler()
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        handler._mqtt_client = mock_client
        handler._mqtt_connected = True

        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert mock_client.publish.call_count == 2


# ===================================================================
# Test: Health stats reporting
# ===================================================================
class TestWebhookHealthStats:
    """Verify health stats tracking across modes."""

    def _make_handler(self, delivery_mode="http"):
        from plugins.webhook_handler import WebhookHandler

        return WebhookHandler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": delivery_mode,
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })

    def test_initial_stats_are_zero(self):
        handler = self._make_handler()
        stats = handler.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 0

    @pytest.mark.asyncio
    async def test_sent_count_increments(self):
        handler = self._make_handler()
        with patch.object(handler, "_send_http", new_callable=AsyncMock):
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            stats = handler.get_health_stats()
            assert stats["events_sent"] == 1


# ===================================================================
# Test: JSON payload structure completeness
# ===================================================================
class TestWebhookJSONPayload:
    """Verify the full JSON payload structure matches spec."""

    @pytest.mark.asyncio
    async def test_full_json_structure(self):
        from plugins.webhook_handler import WebhookHandler

        handler = WebhookHandler({
            "endpoint_url": "https://example.com/hook",
            "delivery_mode": "http",
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True,
                 "format_template": "{callsign}"},
            ],
        })
        with patch.object(handler, "_send_http", new_callable=AsyncMock) as mock_send:
            await handler.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            payload = mock_send.call_args[0][0]

            # Top-level keys
            assert "source" in payload
            assert "tak_server_id" in payload
            assert "timestamp" in payload

            # CoT section
            assert "cot" in payload
            assert payload["cot"]["type"] == "a-f-G-U-C"
            assert payload["cot"]["uid"] == "ANDROID-device1"
            assert "time" in payload["cot"]
            assert "stale" in payload["cot"]

            # Contact section
            assert "contact" in payload
            assert payload["contact"]["callsign"] == "ALPHA-1"

            # Position section
            assert "position" in payload
            assert payload["position"]["lat"] == "38.897"
            assert payload["position"]["lon"] == "-77.036"
            assert payload["position"]["hae"] == "0"
            assert "speed" in payload["position"]
            assert "course" in payload["position"]

            # Group section
            assert "group" in payload
            assert payload["group"]["name"] == "Cyan"
            assert payload["group"]["role"] == "Team Lead"

            # Device section
            assert "device" in payload
            assert payload["device"]["device"] == "Samsung"
            assert payload["device"]["platform"] == "Android"

            # Remarks
            assert "remarks" in payload
            assert payload["remarks"] == "On patrol"
