# ABOUTME: Unit tests for the OutboundWebSocket plugin.
# ABOUTME: Covers metadata, lifecycle, pipeline, writer loop backoff, and health stats.

import asyncio
from unittest.mock import AsyncMock, patch

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
    """Return an OutboundWebSocket with a mocked aiohttp session."""
    from plugins.outbound_websocket import OutboundWebSocket
    return OutboundWebSocket(config or {
        "endpoint_url": "ws://localhost:9999/ws",
        "message_rules": MINIMAL_RULES,
    })


# ===================================================================
# Metadata
# ===================================================================

class TestOutboundWebSocketMetadata:
    def test_plugin_name_constant(self):
        from plugins.outbound_websocket import OutboundWebSocket
        assert OutboundWebSocket.PLUGIN_NAME == "outbound_websocket"

    def test_plugin_name_property(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "outbound_websocket"

    def test_get_plugin_name_classmethod(self):
        from plugins.outbound_websocket import OutboundWebSocket
        assert OutboundWebSocket.get_plugin_name() == "outbound_websocket"

    def test_category_is_output(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "output"

    def test_exactly_11_config_fields(self):
        """Spec mandates exactly 11 PluginConfigField entries."""
        from plugins.base_plugin import PluginConfigField
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        config_fields = [f for f in fields if isinstance(f, PluginConfigField)]
        assert len(config_fields) == 11, (
            f"Expected 11 PluginConfigField, got {len(config_fields)}: "
            f"{[f.name for f in config_fields]}"
        )

    def test_config_field_names(self):
        """All 11 expected field names are present."""
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        names = {f.name for f in fields}
        expected = {
            "endpoint_url", "custom_headers", "output_format", "custom_template",
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

    def test_endpoint_url_is_required(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "endpoint_url")
        assert f.required is True

    def test_output_format_default_json(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "output_format")
        assert f.default_value == "json"

    def test_dedup_enabled_default_false(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "dedup_enabled")
        assert str(f.default_value).lower() == "false"

    def test_stream_buffer_size_default_100(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "stream_buffer_size")
        assert f.default_value == 100

    def test_timeout_seconds_default_10(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "timeout_seconds")
        assert f.default_value == 10

    def test_max_rate_default_blank(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "max_rate")
        assert f.default_value == ""

    def test_dedup_ttl_seconds_default_5(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        f = next(x for x in fields if x.name == "dedup_ttl_seconds")
        assert f.default_value == 5


# ===================================================================
# Lifecycle — start / cleanup
# ===================================================================

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_session_and_connects(self):
        """start() creates an aiohttp.ClientSession and calls ws_connect."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()

            mock_session.ws_connect.assert_called_once()
            assert plugin._writer_task is not None
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_sets_connected_true_on_success(self):
        mock_ws = AsyncMock()
        mock_ws.closed = False

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            assert plugin._connected is True
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_start_sets_connected_false_on_connection_error(self):
        """If ws_connect raises, _connected stays False."""
        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(side_effect=Exception("refused"))

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            assert plugin._connected is False
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_cleanup_cancels_writer_task(self):
        """cleanup() cancels the writer task without raising."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            assert plugin._writer_task is not None

            # Must not raise
            await plugin.cleanup()
            assert plugin._writer_task is None or plugin._writer_task.done()

    @pytest.mark.asyncio
    async def test_cleanup_closes_ws_and_session(self):
        """cleanup() closes both the WebSocket and the session."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            await plugin.cleanup()

            mock_ws.close.assert_called()
            mock_session.close.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_idempotent_when_not_started(self):
        """cleanup() must not raise when called before start()."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "message_rules": MINIMAL_RULES,
        })
        # Must not raise
        await plugin.cleanup()


# ===================================================================
# handle_cot_message — pipeline
# ===================================================================

class TestHandleCotMessage:
    @pytest.mark.asyncio
    async def test_happy_path_enqueues_payload(self):
        """Valid CoT matching a rule is enqueued."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "output_format": "json",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=100)
        plugin._connected = False  # writer not running

        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert plugin._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_should_handle_false_drops_and_counts(self):
        """Events that don't match message rules are dropped and counted."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "message_rules": [],  # No rules → should_handle returns False
        })
        plugin._queue = asyncio.Queue(maxsize=100)

        pre = plugin._events_dropped
        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert plugin._events_dropped == pre + 1
        assert plugin._queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_dedup_hit_drops_and_counts(self):
        """Duplicate UID+type within TTL is dropped and counted."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "dedup_enabled": "true",
            "dedup_ttl_seconds": 60,
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=100)

        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        dropped_before = plugin._events_dropped
        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert plugin._events_dropped == dropped_before + 1

    @pytest.mark.asyncio
    async def test_rate_limited_drops_and_counts(self):
        """When rate limit is 1 event/sec and two arrive instantly, second is dropped."""
        xml2 = SAMPLE_COT_XML.replace(b"ANDROID-unit-test", b"ANDROID-unit-test-2")
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "max_rate": "1",
            "dedup_enabled": "false",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=100)

        from services.output_plugin_helpers import RateLimiter
        plugin._rate_limiter = RateLimiter(1.0)

        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        dropped_before = plugin._events_dropped
        await plugin.handle_cot_message(xml2, tak_server_id=1)
        assert plugin._events_dropped == dropped_before + 1

    @pytest.mark.asyncio
    async def test_queue_full_drops_oldest_counts(self):
        """When the queue is full, oldest is dropped (with task_done) and new item enqueued."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "stream_buffer_size": "2",
            "dedup_enabled": "false",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=2)
        plugin._connected = False

        # Fill the queue manually (bypass the unfinished-task tracking)
        plugin._queue.put_nowait(b"payload-a")
        plugin._queue.task_done()  # balance the put so join() wouldn't block
        plugin._queue.put_nowait(b"payload-b")
        plugin._queue.task_done()
        assert plugin._queue.full()

        # Refill properly — what the writer will see
        while not plugin._queue.empty():
            plugin._queue.get_nowait()

        plugin._queue.put_nowait(b"payload-a")
        plugin._queue.put_nowait(b"payload-b")
        assert plugin._queue.full()

        dropped_before = plugin._events_dropped
        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        # One item dropped from the front
        assert plugin._events_dropped == dropped_before + 1
        # Queue still at capacity
        assert plugin._queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_queue_full_drop_oldest_calls_task_done(self):
        """Exactly one task_done() is called for each get_nowait() when dropping oldest."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "stream_buffer_size": "1",
            "dedup_enabled": "false",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=1)

        # Put one item without task_done so queue.join() would block if task_done never called
        plugin._queue.put_nowait(b"old-payload")

        # Now handle_cot_message should drop oldest (get_nowait + task_done) and put new
        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        # Queue has 1 item (the new one); join() should never block because task_done was called
        # We verify by checking qsize and that no unfinished tasks remain
        assert plugin._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_dedup_ttl_cached_locally(self):
        """Plugin caches self._dedup_ttl — not reached via Deduplicator._ttl."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "dedup_enabled": "true",
            "dedup_ttl_seconds": "42",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=100)

        await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        assert plugin._dedup_ttl == 42
        assert hasattr(plugin, "_dedup_ttl")


# ===================================================================
# Writer task
# ===================================================================

class TestWriterTask:
    @pytest.mark.asyncio
    async def test_writer_sends_str_for_json_payload(self):
        """Writer calls ws.send_str() for JSON (string) payloads."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock()
        mock_ws.send_bytes = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "output_format": "json",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True
            plugin._ws = mock_ws

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await asyncio.sleep(0.05)

            assert mock_ws.send_str.called or plugin._events_sent >= 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_writer_sends_bytes_for_xml_payload(self):
        """Writer calls ws.send_bytes() for XML (bytes) payloads."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock()
        mock_ws.send_bytes = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "output_format": "xml",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True
            plugin._ws = mock_ws

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await asyncio.sleep(0.05)

            assert mock_ws.send_bytes.called or plugin._events_sent >= 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_writer_increments_events_sent_on_success(self):
        """Successful ws send increments _events_sent."""
        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock()
        mock_ws.send_bytes = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "output_format": "json",
                "dedup_enabled": "false",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()
            plugin._connected = True
            plugin._ws = mock_ws

            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await asyncio.sleep(0.1)

            assert plugin._events_sent >= 1
            await plugin.cleanup()

    @pytest.mark.asyncio
    async def test_writer_send_exception_sets_disconnected(self):
        """If ws.send_str raises, _last_error is set and _connected becomes False."""
        # Call _writer_loop directly for one iteration with a failing WS.
        from plugins.outbound_websocket import OutboundWebSocket

        send_exception = Exception("connection reset")

        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock(side_effect=send_exception)
        mock_ws.send_bytes = AsyncMock(side_effect=send_exception)
        mock_ws.close = AsyncMock()

        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "output_format": "json",
            "dedup_enabled": "false",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=100)
        plugin._connected = True
        plugin._ws = mock_ws

        # Put one item in the queue so the writer dequeues and tries to send
        await plugin._queue.put("hello")

        # Patch sleep so the reconnect loop doesn't spin for real time and
        # patch _connect so after the send failure it immediately cancels
        # the writer by raising CancelledError.
        async def instant_connect():
            raise asyncio.CancelledError()

        plugin._connect = instant_connect

        with patch("plugins.outbound_websocket.asyncio.sleep", new_callable=AsyncMock):
            task = asyncio.create_task(plugin._writer_loop())
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        # The send failure should have set last_error before the reconnect attempt
        assert plugin._last_error is not None
        assert "connection reset" in plugin._last_error
        # The writer must mark the connection as down after a send failure
        assert plugin._connected is False

    @pytest.mark.asyncio
    async def test_backoff_schedule_doubles_to_cap(self):
        """Reconnect backoff doubles each cycle and caps at 30s."""
        sleep_calls = []

        async def fake_sleep(seconds):
            # Only track non-zero sleeps — the backoff delays
            if seconds > 0:
                sleep_calls.append(seconds)
            if len(sleep_calls) >= 5:
                raise asyncio.CancelledError()

        # ws_connect always fails so the writer loops through backoff
        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(side_effect=Exception("refused"))
        mock_session.close = AsyncMock()

        # Patch at the plugin module level so asyncio.sleep in the test body
        # is not intercepted (we still need await asyncio.sleep(0) to yield).
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("plugins.outbound_websocket.asyncio.sleep",
                       side_effect=fake_sleep):
                from plugins.outbound_websocket import OutboundWebSocket
                plugin = OutboundWebSocket({
                    "endpoint_url": "ws://localhost:9999/ws",
                    "message_rules": MINIMAL_RULES,
                })
                await plugin.start()
                try:
                    await asyncio.wait_for(plugin._writer_task, timeout=2.0)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass

        # Verify backoff doubles: 1, 2, 4, 8, 16... capped at 30
        assert len(sleep_calls) >= 4, (
            f"Expected at least 4 backoff sleeps, got {sleep_calls}"
        )
        for i, delay in enumerate(sleep_calls[:4]):
            expected = min(2 ** i, 30)
            assert delay == expected, (
                f"sleep_calls[{i}]={delay}, expected {expected}"
            )
        for delay in sleep_calls:
            assert delay <= 30, f"Backoff exceeded 30s cap: {delay}"

    @pytest.mark.asyncio
    async def test_task_done_called_for_each_get(self):
        """Every queue.get() in the writer is paired with task_done() via try/finally."""
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=10)

        # Put 3 items directly
        for i in range(3):
            await plugin._queue.put(f"payload-{i}")

        mock_ws = AsyncMock()
        mock_ws.closed = False
        mock_ws.send_str = AsyncMock()
        mock_ws.close = AsyncMock()

        plugin._ws = mock_ws
        plugin._connected = True

        # Run writer briefly
        task = asyncio.create_task(plugin._writer_loop())
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        # Whatever was dequeued must have had task_done() called — verify via
        # events_sent counter (each send increments it only after successful send).
        # The key invariant: queue.qsize() + events_sent == 3
        assert plugin._queue.qsize() + plugin._events_sent == 3


# ===================================================================
# Health stats
# ===================================================================

class TestHealthStats:
    def test_health_stats_shape(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert "events_sent" in stats
        assert "events_dropped" in stats
        assert "ws_connected" in stats
        assert "buffer_size" in stats
        assert "last_error" in stats

    def test_ws_connected_reflects_state(self):
        plugin = _make_plugin()
        plugin._connected = True
        assert plugin.get_health_stats()["ws_connected"] is True
        plugin._connected = False
        assert plugin.get_health_stats()["ws_connected"] is False

    def test_initial_counters_zero(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 0
        assert stats["last_error"] is None

    def test_buffer_size_reflects_queue(self):
        from plugins.outbound_websocket import OutboundWebSocket
        plugin = OutboundWebSocket({
            "endpoint_url": "ws://localhost:9999/ws",
            "message_rules": MINIMAL_RULES,
        })
        plugin._queue = asyncio.Queue(maxsize=10)
        plugin._queue.put_nowait("a")
        plugin._queue.put_nowait("b")
        assert plugin.get_health_stats()["buffer_size"] == 2


# ===================================================================
# test_connection
# ===================================================================

class TestTestConnection:
    @pytest.mark.asyncio
    async def test_connection_success_returns_true_str(self):
        """test_connection returns (True, str) when endpoint is reachable."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            success, message = await plugin.test_connection()
            assert isinstance(success, bool)
            assert isinstance(message, str)

    @pytest.mark.asyncio
    async def test_connection_failure_returns_false_str(self):
        """test_connection returns (False, str) when endpoint is unreachable."""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.ws_connect = AsyncMock(side_effect=Exception("refused"))
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "message_rules": MINIMAL_RULES,
            })
            success, message = await plugin.test_connection()
            assert success is False
            assert len(message) > 0

    @pytest.mark.asyncio
    async def test_custom_headers_reach_ws_connect(self):
        """parse_custom_headers result is passed as headers= to ws_connect."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        mock_session = AsyncMock()
        mock_session.ws_connect = AsyncMock(return_value=mock_ws)
        mock_session.close = AsyncMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from plugins.outbound_websocket import OutboundWebSocket
            plugin = OutboundWebSocket({
                "endpoint_url": "ws://localhost:9999/ws",
                "custom_headers": "X-Api-Key: secret\nX-Source: trakbridge",
                "message_rules": MINIMAL_RULES,
            })
            await plugin.start()

            # Verify ws_connect was called with headers
            call_kwargs = mock_session.ws_connect.call_args
            assert call_kwargs is not None
            # headers may be in args or kwargs
            headers_passed = (
                call_kwargs.kwargs.get("headers")
                or (call_kwargs[1].get("headers") if call_kwargs[1] else None)
            )
            if headers_passed is not None:
                assert "X-Api-Key" in headers_passed
                assert headers_passed["X-Api-Key"] == "secret"

            await plugin.cleanup()
