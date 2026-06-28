# ABOUTME: End-to-end tests for OutboundWebSocket using plugin_manager discovery and a real local server.
# ABOUTME: Validates plugin discovery, mixed-batch processing, and buffer-overflow semantics.

import asyncio
import json

import pytest
from aiohttp import web

# ---------------------------------------------------------------------------
# Sample CoT XML fixtures
# ---------------------------------------------------------------------------

FRIENDLY_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-e2e-ws-friendly"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="FRIENDLY-WS"/>
  </detail>
</event>"""

HOSTILE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-h-G" uid="hostile-e2e-ws"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="h-e">
  <point lat="39.0" lon="-76.0" hae="100" ce="50" le="50"/>
  <detail>
    <contact callsign="HOSTILE-WS"/>
  </detail>
</event>"""


def _make_cot_xml(uid: str, cot_type: str = "a-f-G-U-C") -> bytes:
    """Generate CoT XML bytes for a given UID and type."""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" type="{cot_type}" uid="{uid}"'
        f' time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"'
        f' stale="2026-04-11T12:05:00Z" how="m-g">'
        f'<point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>'
        f'<detail><contact callsign="{uid}"/></detail>'
        f"</event>"
    ).encode()


# ---------------------------------------------------------------------------
# Local WebSocket server helper (self-contained, no shared fixture dependency)
# ---------------------------------------------------------------------------


class _LocalWSServer:
    """Minimal aiohttp WebSocket server for E2E tests."""

    def __init__(self):
        self.messages = []
        self._app = None
        self._runner = None
        self._site = None
        self.port = None
        self._active_ws = []
        self.connected_event = asyncio.Event()

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._active_ws.append(ws)
        self.connected_event.set()
        async for msg in ws:
            from aiohttp import WSMsgType
            if msg.type == WSMsgType.TEXT:
                self.messages.append(("text", msg.data))
            elif msg.type == WSMsgType.BINARY:
                self.messages.append(("binary", msg.data))
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
        self._active_ws = [w for w in self._active_ws if w is not ws]
        return ws

    async def start(self):
        self._app = web.Application()
        self._app.router.add_get("/ws", self._ws_handler)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        self.port = self._site._server.sockets[0].getsockname()[1]

    async def stop(self):
        for ws in list(self._active_ws):
            try:
                await ws.close()
            except Exception:
                pass
        if self._runner:
            await self._runner.cleanup()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/ws"


async def _wait_for(server: _LocalWSServer, count: int, timeout: float = 5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while len(server.messages) < count:
        if asyncio.get_event_loop().time() >= deadline:
            break
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Plugin discovery
# ---------------------------------------------------------------------------


def test_plugin_manager_discovers_outbound_websocket():
    """plugin_manager.load_plugins_from_directory must find outbound_websocket."""
    from plugins.plugin_manager import PluginManager

    manager = PluginManager()
    manager.load_plugins_from_directory("plugins")

    registered_names = list(manager.plugins.keys())
    assert "outbound_websocket" in registered_names, (
        f"outbound_websocket not found. Registered: {registered_names}"
    )


# ---------------------------------------------------------------------------
# Mixed-batch E2E tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_batch_only_matching_events_reach_server():
    """
    Batch of 20 events: friendly, hostile, duplicates.
    Verify only the expected subset arrives at the server.
    """
    from plugins.outbound_websocket import OutboundWebSocket

    server = _LocalWSServer()
    await server.start()

    try:
        plugin = OutboundWebSocket({
            "endpoint_url": server.url,
            "output_format": "json",
            "dedup_enabled": "true",
            "dedup_ttl_seconds": "60",
            "message_rules": [
                # Only forward friendly CoT types
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        await plugin.start()
        await asyncio.wait_for(server.connected_event.wait(), timeout=3.0)

        # 20-event batch:
        # 5 unique friendly → should pass (5)
        # 5 duplicate friendly → dedup drops (5)
        # 5 hostile → rules drop (5)
        # 5 drone uid (friendly type) → should pass (5)
        unique_friendly = [_make_cot_xml(f"ANDROID-ws-e2e-{i}") for i in range(5)]
        unique_drones = [
            _make_cot_xml(f"DRONE-ws-e2e-{i}", "a-f-A-M-F-U") for i in range(5)
        ]
        hostile_events = [
            _make_cot_xml(f"hostile-ws-e2e-{i}", "a-h-G") for i in range(5)
        ]

        for xml in unique_friendly:
            await plugin.handle_cot_message(xml, tak_server_id=1)
        for xml in unique_friendly:  # duplicates
            await plugin.handle_cot_message(xml, tak_server_id=1)
        for xml in hostile_events:
            await plugin.handle_cot_message(xml, tak_server_id=1)
        for xml in unique_drones:
            await plugin.handle_cot_message(xml, tak_server_id=1)

        await _wait_for(server, 10, timeout=5.0)
        await plugin.cleanup()

        stats = plugin.get_health_stats()
        # 10 messages sent (5 friendly + 5 drone)
        assert stats["events_sent"] == 10, f"Got stats: {stats}"
        # 10 dropped (5 duplicates + 5 hostile)
        assert stats["events_dropped"] == 10, f"Got stats: {stats}"
        assert len(server.messages) == 10
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_geofence_filters_outside_events():
    """Events outside the geofence are dropped; events inside pass."""
    from plugins.outbound_websocket import OutboundWebSocket

    server = _LocalWSServer()
    await server.start()

    try:
        # Tight box covering only the FRIENDLY position (~38.897, -77.036)
        # HOSTILE at 39.0, -76.0 is outside
        plugin = OutboundWebSocket({
            "endpoint_url": server.url,
            "output_format": "json",
            "dedup_enabled": "false",
            "global_geofence": {
                "enabled": True,
                "bounds": {
                    "north": 38.95,
                    "south": 38.85,
                    "east": -76.9,
                    "west": -77.1,
                },
            },
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
                {"cot_type_pattern": "a-h-*", "enabled": True, "format_template": ""},
            ],
        })
        await plugin.start()
        await asyncio.wait_for(server.connected_event.wait(), timeout=3.0)

        await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # inside
        await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)   # outside

        await _wait_for(server, 1, timeout=3.0)
        await plugin.cleanup()

        assert len(server.messages) == 1
        body = json.loads(server.messages[0][1])
        assert body["cot"]["uid"] == "ANDROID-e2e-ws-friendly"

        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 1
        assert stats["events_dropped"] == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_rate_limiter_throttles_delivery():
    """With max_rate=1, a rapid burst drops all but the first event."""
    from plugins.outbound_websocket import OutboundWebSocket

    server = _LocalWSServer()
    await server.start()

    try:
        plugin = OutboundWebSocket({
            "endpoint_url": server.url,
            "output_format": "json",
            "max_rate": "1",
            "dedup_enabled": "false",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        await plugin.start()
        await asyncio.wait_for(server.connected_event.wait(), timeout=3.0)

        # Send 5 events instantly — only 1 should pass rate limiter
        for i in range(5):
            xml = _make_cot_xml(f"ANDROID-ws-rate-{i}")
            await plugin.handle_cot_message(xml, tak_server_id=1)

        await _wait_for(server, 1, timeout=3.0)
        await plugin.cleanup()

        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 1, f"Got stats: {stats}"
        assert stats["events_dropped"] == 4, f"Got stats: {stats}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_buffer_overflow_drops_oldest():
    """
    Buffer overflow scenario: queue is filled to capacity, then more events
    are pushed via handle_cot_message. Verify oldest-drop semantics and
    that events_dropped increments for each evicted item.

    This test uses an unreachable endpoint so the writer stays in the
    reconnect-backoff loop and never drains the queue, ensuring the queue
    stays full for the duration of the overflow assertions.
    """
    from plugins.outbound_websocket import OutboundWebSocket

    buffer_size = 3
    plugin = OutboundWebSocket({
        # Unreachable endpoint: writer stays in backoff, never drains queue.
        "endpoint_url": "ws://127.0.0.1:19997/ws",
        "output_format": "json",
        "stream_buffer_size": str(buffer_size),
        "dedup_enabled": "false",
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })

    # Initialise queue and rate limiter directly — no start() so we keep
    # the writer task out of the picture and the queue stays full.
    plugin._queue = asyncio.Queue(maxsize=buffer_size)
    from services.output_plugin_helpers import RateLimiter
    plugin._rate_limiter = RateLimiter(None)

    # Fill the queue to capacity with directly-placed payloads.
    for i in range(buffer_size):
        plugin._queue.put_nowait(f"early-payload-{i}")

    assert plugin._queue.full()

    # Push buffer_size more events via handle_cot_message; each should
    # evict the oldest item (with task_done) and count it as dropped.
    drops_before = plugin._events_dropped
    for i in range(buffer_size):
        xml = _make_cot_xml(f"ANDROID-ws-overflow-{i}")
        await plugin.handle_cot_message(xml, tak_server_id=1)

    stats = plugin.get_health_stats()
    # Each handle_cot_message on a full queue drops one oldest item.
    assert stats["events_dropped"] >= drops_before + buffer_size, (
        f"Expected at least {drops_before + buffer_size} drops, got: {stats}"
    )
    # Queue should still be at capacity (old items replaced by new)
    assert plugin._queue.qsize() == buffer_size
