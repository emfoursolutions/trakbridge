# ABOUTME: Integration tests for OutboundWebSocket using a real local aiohttp WebSocket server.
# ABOUTME: Verifies round-trip delivery, all output formats, custom headers, and reconnect behaviour.

import asyncio
import json

import pytest
from aiohttp import web

# ---------------------------------------------------------------------------
# Sample CoT XML
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-ws-integration"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="WS-INTEG-1"/>
  </detail>
</event>"""

MINIMAL_RULES = [
    {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": "{callsign}"},
]


# ---------------------------------------------------------------------------
# Real WebSocket server fixture
# ---------------------------------------------------------------------------


class _CaptureWSServer:
    """Minimal aiohttp WebSocket server that captures received messages and
    connection headers."""

    def __init__(self):
        self.messages = []
        self.connect_headers = {}
        self._app = None
        self._runner = None
        self._site = None
        self.port = None
        self._active_ws = []
        # Event set when at least one WS connection is established
        self.connected_event = asyncio.Event()

    async def _ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        self.connect_headers = dict(request.headers)
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

    async def close_all_connections(self):
        """Force-close all active WebSocket connections to trigger reconnect."""
        for ws in list(self._active_ws):
            try:
                await ws.close()
            except Exception:
                pass
        self._active_ws = []
        self.connected_event.clear()

    async def start(self):
        self._app = web.Application()
        self._app.router.add_get("/ws", self._ws_handler)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        self.port = self._site._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/ws"


@pytest.fixture
async def ws_server():
    server = _CaptureWSServer()
    await server.start()
    yield server
    await server.stop()


async def _wait_for_messages(server: _CaptureWSServer, count: int,
                              timeout: float = 4.0):
    """Wait until at least `count` messages have arrived."""
    deadline = asyncio.get_event_loop().time() + timeout
    while len(server.messages) < count:
        if asyncio.get_event_loop().time() >= deadline:
            break
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plugin_connects_to_real_ws_server(ws_server):
    """Plugin connects to a real WebSocket server and reports connected state."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    # Give aiohttp time to complete the WS handshake
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    assert plugin._connected is True
    await plugin.cleanup()


@pytest.mark.asyncio
async def test_json_format_round_trip(ws_server):
    """JSON output_format delivers valid JSON to the server."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)

    await plugin.cleanup()

    assert len(ws_server.messages) == 1
    msg_type, payload = ws_server.messages[0]
    assert msg_type == "text"
    body = json.loads(payload)
    assert body["source"] == "trakbridge"
    assert body["cot"]["uid"] == "ANDROID-ws-integration"
    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1


@pytest.mark.asyncio
async def test_xml_format_round_trip(ws_server):
    """XML passthrough sends raw CoT bytes to the server as a binary frame."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "xml",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)

    await plugin.cleanup()

    assert len(ws_server.messages) == 1
    msg_type, payload = ws_server.messages[0]
    assert msg_type == "binary"
    assert b"ANDROID-ws-integration" in payload


@pytest.mark.asyncio
async def test_custom_template_format_round_trip(ws_server):
    """Custom template is rendered and sent as a text frame."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "custom_template",
        "custom_template": "ALERT: {callsign} at {lat},{lon}",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)

    await plugin.cleanup()

    assert len(ws_server.messages) == 1
    msg_type, payload = ws_server.messages[0]
    assert msg_type == "text"
    assert "WS-INTEG-1" in payload


@pytest.mark.asyncio
async def test_custom_headers_reach_server_on_handshake(ws_server):
    """Headers in custom_headers config are present in the WS upgrade request."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "custom_headers": "X-Api-Key: secret-ws\nX-Source: trakbridge",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)

    await plugin.cleanup()

    assert ws_server.connect_headers.get("X-Api-Key") == "secret-ws"
    assert ws_server.connect_headers.get("X-Source") == "trakbridge"


@pytest.mark.asyncio
async def test_server_close_triggers_reconnect(ws_server):
    """When the server closes the WS, the plugin reconnects and resumes delivery."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "json",
        "dedup_enabled": "false",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    # Send first message successfully
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)
    assert plugin._events_sent >= 1

    # Server forcibly closes the connection
    await ws_server.close_all_connections()

    # The writer detects server-side close within ~1s (queue.get timeout)
    # and reconnects with 1s backoff. Allow up to 5s for reconnect.
    try:
        await asyncio.wait_for(ws_server.connected_event.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    # Send a second message after reconnect
    xml2 = SAMPLE_COT_XML.replace(b"ANDROID-ws-integration", b"ANDROID-ws-integration-2")
    await plugin.handle_cot_message(xml2, tak_server_id=1)
    await _wait_for_messages(ws_server, 2, timeout=5.0)

    await plugin.cleanup()

    # At least 2 messages delivered across the reconnect
    assert len(ws_server.messages) >= 2


@pytest.mark.asyncio
async def test_unreachable_endpoint_connected_stays_false():
    """When endpoint is unreachable, _connected stays False and events are dropped."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": "ws://127.0.0.1:19998/ws",  # nothing listening
        "output_format": "json",
        "dedup_enabled": "false",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.sleep(0.3)

    assert plugin._connected is False

    # Events fed to a disconnected plugin are enqueued (not dropped immediately)
    # but the writer cannot deliver them.
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    assert plugin._events_sent == 0

    await plugin.cleanup()


@pytest.mark.asyncio
async def test_include_raw_xml_in_json_payload(ws_server):
    """include_raw_xml=true embeds base64-encoded CoT XML in the JSON payload."""
    from plugins.outbound_websocket import OutboundWebSocket

    plugin = OutboundWebSocket({
        "endpoint_url": ws_server.url,
        "output_format": "json",
        "include_raw_xml": "true",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.start()
    await asyncio.wait_for(ws_server.connected_event.wait(), timeout=3.0)

    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    await _wait_for_messages(ws_server, 1)

    await plugin.cleanup()

    assert len(ws_server.messages) == 1
    body = json.loads(ws_server.messages[0][1])
    assert "raw_xml" in body
    import base64
    decoded = base64.b64decode(body["raw_xml"])
    assert b"ANDROID-ws-integration" in decoded
