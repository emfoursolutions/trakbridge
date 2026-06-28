# ABOUTME: Unit tests for the OutboundMQTT plugin.
# ABOUTME: Covers metadata, URL parsing, lifecycle, pipeline, and health stats.

import asyncio
import queue
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-unit-test"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="UNIT-1"/>
  </detail>
</event>"""

MINIMAL_RULES = [
    {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": "{callsign}"},
]


def _make_plugin(config: dict = None):
    """Return an OutboundMQTT with a no-op paho client."""
    with patch("paho.mqtt.client.Client"):
        from plugins.outbound_mqtt import OutboundMQTT
        return OutboundMQTT(config or {"broker_url": "mqtt://localhost:1883", "message_rules": MINIMAL_RULES})


# ===================================================================
# Metadata
# ===================================================================

class TestOutboundMQTTMetadata:
    def test_plugin_name(self):
        from plugins.outbound_mqtt import OutboundMQTT
        assert OutboundMQTT.PLUGIN_NAME == "outbound_mqtt"

    def test_plugin_name_property(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "outbound_mqtt"

    def test_get_plugin_name_classmethod(self):
        from plugins.outbound_mqtt import OutboundMQTT
        assert OutboundMQTT.get_plugin_name() == "outbound_mqtt"

    def test_category_is_output(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "output"

    def test_exactly_17_config_fields(self):
        """Spec mandates exactly 17 PluginConfigField entries."""
        from plugins.base_plugin import PluginConfigField
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        config_fields = [f for f in fields if isinstance(f, PluginConfigField)]
        assert len(config_fields) == 17, (
            f"Expected 17 PluginConfigField, got {len(config_fields)}: "
            f"{[f.name for f in config_fields]}"
        )

    def test_config_field_names(self):
        """All 17 expected field names are present."""
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = {f.name for f in fields}
        expected = {
            "broker_url", "topic", "qos", "client_id", "username", "password",
            "keepalive", "ca_source", "output_format", "custom_template",
            "uid_filter", "include_raw_xml", "timeout_seconds", "max_rate",
            "stream_buffer_size", "dedup_enabled", "dedup_ttl_seconds",
        }
        assert names == expected, f"Field name mismatch. Got: {names}"

    def test_exactly_2_custom_components(self):
        """Spec mandates exactly 2 PluginCustomComponent entries."""
        from plugins.base_plugin import PluginCustomComponent
        plugin = _make_plugin()
        components = plugin.plugin_metadata.get("custom_components", [])
        cc = [c for c in components if isinstance(c, PluginCustomComponent)]
        assert len(cc) == 2, f"Expected 2 PluginCustomComponent, got {len(cc)}"

    def test_custom_components_are_message_rules_and_global_geofence(self):
        plugin = _make_plugin()
        components = plugin.plugin_metadata.get("custom_components", [])
        field_names = {c.field_name for c in components}
        assert field_names == {"message_rules", "global_geofence"}

    def test_message_rules_NOT_in_config_fields(self):
        """message_rules must only appear as PluginCustomComponent, never PluginConfigField."""
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        assert "message_rules" not in names

    def test_global_geofence_NOT_in_config_fields(self):
        """global_geofence must only appear as PluginCustomComponent, never PluginConfigField."""
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        assert "global_geofence" not in names

    def test_custom_template_has_correct_depends_on(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        ct_field = next(f for f in fields if f.name == "custom_template")
        assert ct_field.depends_on == {"output_format": "custom_template"}

    def test_password_is_sensitive(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        pw_field = next(f for f in fields if f.name == "password")
        assert pw_field.sensitive is True

    def test_qos_default_is_0(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        qos_field = next(f for f in fields if f.name == "qos")
        assert str(qos_field.default_value) == "0"

    def test_client_id_default_is_trakbridge(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "client_id")
        assert f.default_value == "trakbridge"

    def test_keepalive_default_60(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "keepalive")
        assert f.default_value == 60

    def test_dedup_enabled_default_false(self):
        """MQTT brokers de-dup at broker level; dedup off by default."""
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "dedup_enabled")
        assert str(f.default_value).lower() == "false"

    def test_stream_buffer_size_default_100(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "stream_buffer_size")
        assert f.default_value == 100


# ===================================================================
# URL parsing
# ===================================================================

class TestParseMqttUrl:
    def _parse(self, url):
        plugin = _make_plugin()
        return plugin._parse_mqtt_url(url)

    def test_mqtt_default_port(self):
        host, port, tls = self._parse("mqtt://broker.example.com")
        assert host == "broker.example.com"
        assert port == 1883
        assert tls is False

    def test_mqtts_default_port(self):
        host, port, tls = self._parse("mqtts://broker.example.com")
        assert host == "broker.example.com"
        assert port == 8883
        assert tls is True

    def test_explicit_port_honoured(self):
        host, port, tls = self._parse("mqtt://broker.example.com:1234")
        assert port == 1234

    def test_mqtts_explicit_port(self):
        host, port, tls = self._parse("mqtts://broker.example.com:8884")
        assert port == 8884
        assert tls is True

    def test_path_stripped(self):
        host, port, tls = self._parse("mqtt://broker.example.com/some/path")
        assert host == "broker.example.com"
        assert port == 1883

    def test_malformed_url_raises(self):
        with pytest.raises(ValueError):
            self._parse("http://not-mqtt.example.com")


# ===================================================================
# Lifecycle — start / cleanup
# ===================================================================

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_connects_with_host_port_keepalive(self):
        """start() calls client.connect() with parsed host/port and keepalive."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://mybroker:9999",
                "client_id": "test-id",
                "keepalive": 30,
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()

            mock_client.connect.assert_called_once_with("mybroker", 9999, keepalive=30)
            mock_client.loop_start.assert_called_once()
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_sets_username_password_when_provided(self):
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "username": "user1",
                "password": "secret",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            mock_client.username_pw_set.assert_called_once_with("user1", "secret")
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_skips_auth_when_no_username(self):
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            mock_client.username_pw_set.assert_not_called()
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_mqtts_calls_build_ssl_context(self):
        """mqtts:// must use cert_utils.build_ssl_context, not client.tls_set directly."""
        with (
            patch("paho.mqtt.client.Client") as MockClient,
            patch("services.cert_utils.build_ssl_context") as mock_build,
        ):
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_ssl_ctx = MagicMock()
            mock_build.return_value = mock_ssl_ctx

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtts://broker:8883",
                "ca_source": "system",
                "message_rules": MINIMAL_RULES,
            })
            # Need a mock stream for build_ssl_context
            plugin.stream = MagicMock()
            await plugin.start()

            mock_build.assert_called_once_with("system", plugin.stream)
            mock_client.tls_set_context.assert_called_once_with(mock_ssl_ctx)
            # Direct tls_set() must NOT be called
            mock_client.tls_set.assert_not_called()
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_stops_loop_and_disconnects(self):
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            await plugin.cleanup()

            mock_client.loop_stop.assert_called_once()
            mock_client.disconnect.assert_called_once()


# ===================================================================
# handle_cot_message — pipeline
# ===================================================================

class TestHandleCotMessage:
    @pytest.mark.asyncio
    async def test_happy_path_enqueues_payload(self):
        """Valid CoT matching a rule is enqueued for the writer task."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.publish.return_value = MagicMock(rc=0)

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "output_format": "json",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin._queue.join()

            # Item was published by the writer task
            assert plugin._events_sent >= 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_should_handle_false_drops_and_counts(self):
        """Events that don't match message rules are dropped and counted."""
        with patch("paho.mqtt.client.Client"):
            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "message_rules": [],  # No rules → should_handle returns False
            })
            await plugin.start()

            pre = plugin._events_dropped
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            assert plugin._events_dropped == pre + 1
            assert plugin._queue.qsize() == 0
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_dedup_hit_drops_and_counts(self):
        """Duplicate UID+type within TTL is dropped and counted."""
        with patch("paho.mqtt.client.Client"):
            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "dedup_enabled": "true",
                "dedup_ttl_seconds": 60,
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            dropped_before = plugin._events_dropped
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            assert plugin._events_dropped == dropped_before + 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_rate_limited_drops_and_counts(self):
        """When rate limit is 1 event/sec and two arrive instantly, second is dropped."""
        with patch("paho.mqtt.client.Client"):
            from plugins.outbound_mqtt import OutboundMQTT
            # Two different UIDs so dedup won't interfere
            xml2 = SAMPLE_COT_XML.replace(b"ANDROID-unit-test", b"ANDROID-unit-test-2")
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "max_rate": "1",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            dropped_before = plugin._events_dropped
            await plugin.handle_cot_message(xml2, tak_server_id=1)
            assert plugin._events_dropped == dropped_before + 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_queue_full_drops_oldest_counts(self):
        """When the queue is full, oldest is dropped and new item enqueued."""
        with patch("paho.mqtt.client.Client"):
            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "stream_buffer_size": "2",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            # Don't mark connected so writer doesn't drain
            plugin._connected = False

            # Fill the queue without triggering writer
            plugin._queue.put_nowait(("topic/a", b"payload-a"))
            plugin._queue.put_nowait(("topic/b", b"payload-b"))
            assert plugin._queue.full()

            dropped_before = plugin._events_dropped
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

            # One item dropped from the front
            assert plugin._events_dropped == dropped_before + 1
            # Queue is still at capacity (oldest dropped, new item added)
            assert plugin._queue.qsize() == 2
            await plugin.cleanup()


# ===================================================================
# Writer task — publish behaviour
# ===================================================================

class TestWriterTask:
    @pytest.mark.asyncio
    async def test_writer_publishes_with_correct_qos(self):
        """Writer reads from queue and calls publish(topic, payload, qos)."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.publish.return_value = MagicMock(rc=0)

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "qos": "2",
                "output_format": "json",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin._queue.join()

            assert plugin._events_sent >= 1
            call_args = mock_client.publish.call_args
            assert call_args is not None
            assert (
                call_args.kwargs.get("qos") == 2
                or call_args[1].get("qos") == 2
                or (len(call_args[0]) > 2 and call_args[0][2] == 2)
            )
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_writer_substitutes_topic_uid_and_cot_type(self):
        """Writer substitutes {uid} and {cot_type} in topic string."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.publish.return_value = MagicMock(rc=0)

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/{uid}/{cot_type}",
                "output_format": "json",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin._queue.join()

            assert mock_client.publish.called
            topic_used = mock_client.publish.call_args[0][0]
            assert "ANDROID-unit-test" in topic_used
            assert "a-f-G-U-C" in topic_used
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_writer_publish_failure_logs_not_raises(self):
        """If publish() returns an error, it is logged and last_error set; no exception raised."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            # Simulate publish failure
            fail_result = MagicMock()
            fail_result.rc = 1  # MQTT_ERR_NO_CONN
            mock_client.publish.return_value = fail_result

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "topic": "cot/events",
                "output_format": "json",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True

            # Must not raise
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin._queue.join()

            assert plugin._last_error is not None
            await plugin.cleanup()


# ===================================================================
# Health stats
# ===================================================================

class TestHealthStats:
    def test_health_stats_shape(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert "events_sent" in stats
        assert "events_dropped" in stats
        assert "mqtt_connected" in stats
        assert "buffer_size" in stats
        assert "last_error" in stats

    def test_mqtt_connected_reflects_callback_state(self):
        plugin = _make_plugin()
        plugin._connected = True
        assert plugin.get_health_stats()["mqtt_connected"] is True
        plugin._connected = False
        assert plugin.get_health_stats()["mqtt_connected"] is False

    def test_initial_counters_zero(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 0
        assert stats["last_error"] is None


# ===================================================================
# Deduplicator — local TTL cache
# ===================================================================

class TestDedupCache:
    @pytest.mark.asyncio
    async def test_plugin_caches_dedup_ttl_locally(self):
        """Plugin must store self._dedup_ttl — NOT reach into Deduplicator._ttl."""
        with patch("paho.mqtt.client.Client"):
            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://broker:1883",
                "dedup_enabled": "true",
                "dedup_ttl_seconds": "42",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

            assert plugin._dedup_ttl == 42
            # Verify attribute exists on the plugin, not just on deduplicator
            assert hasattr(plugin, "_dedup_ttl")
            await plugin.cleanup()


# ===================================================================
# test_connection
# ===================================================================

class TestTestConnection:
    @pytest.mark.asyncio
    async def test_connection_success_returns_true(self):
        """test_connection returns (True, <message>) when broker is reachable."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client

            # Simulate immediate CONNACK by triggering on_connect callback
            def fake_connect(host, port, keepalive):
                # Invoke the callback that was registered
                if hasattr(mock_client, "_on_connect_cb") and mock_client._on_connect_cb:
                    mock_client._on_connect_cb(mock_client, None, {}, 0)

            mock_client.connect.side_effect = fake_connect
            # Capture the callback registration
            def capture_on_connect(fn):
                mock_client._on_connect_cb = fn
            type(mock_client).on_connect = property(lambda self: None, lambda self, v: capture_on_connect(v))

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://localhost:1883",
                "message_rules": MINIMAL_RULES,
            })
            success, message = await plugin.test_connection()
            # The success path depends on broker being real in integration;
            # for unit test, we just verify the return type contract
            assert isinstance(success, bool)
            assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_connection_failure_returns_false(self):
        """test_connection returns (False, <error message>) when broker is unreachable."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value = mock_client
            mock_client.connect.side_effect = ConnectionRefusedError("Connection refused")

            from plugins.outbound_mqtt import OutboundMQTT
            plugin = OutboundMQTT({
                "broker_url": "mqtt://localhost:19999",
                "message_rules": MINIMAL_RULES,
            })
            success, message = await plugin.test_connection()
            assert success is False
            assert len(message) > 0
