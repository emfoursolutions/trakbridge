# ABOUTME: Integration tests for OutboundHTTP using a real local aiohttp server.
# ABOUTME: Verifies round-trip delivery, headers on wire, and error handling without mocks.

import json

import pytest
from aiohttp import web

# ---------------------------------------------------------------------------
# Sample CoT XML
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-integration-test"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="INTEG-1"/>
  </detail>
</event>"""

MINIMAL_RULES = [
    {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": "{callsign}"},
]


# ---------------------------------------------------------------------------
# Real HTTP server fixture
# ---------------------------------------------------------------------------


class _CaptureServer:
    """Minimal aiohttp server that captures the last request."""

    def __init__(self):
        self.requests = []
        self._app = None
        self._runner = None
        self._site = None
        self.port = None

    async def _handler(self, request: web.Request) -> web.Response:
        body = await request.read()
        self.requests.append({
            "method": request.method,
            "headers": dict(request.headers),
            "body": body,
            "content_type": request.content_type,
        })
        return web.Response(status=200, text="ok")

    async def _error_handler(self, request: web.Request) -> web.Response:
        await request.read()
        return web.Response(status=500, text="server error")

    async def start(self, fail=False):
        self._app = web.Application()
        handler = self._error_handler if fail else self._handler
        self._app.router.add_route("*", "/{tail:.*}", handler)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        # Retrieve the bound port
        self.port = self._site._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/hook"


@pytest.fixture
async def capture_server():
    server = _CaptureServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def error_server():
    server = _CaptureServer()
    await server.start(fail=True)
    yield server
    await server.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_post_json_round_trip(capture_server):
    """POST with JSON output_format delivers valid JSON and correct Content-Type."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "http_method": "POST",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    assert len(capture_server.requests) == 1
    req = capture_server.requests[0]
    assert req["method"] == "POST"
    assert "application/json" in req["content_type"]
    body = json.loads(req["body"])
    assert body["source"] == "trakbridge"
    assert body["cot"]["uid"] == "ANDROID-integration-test"
    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1


@pytest.mark.asyncio
async def test_real_put_json_round_trip(capture_server):
    """PUT with JSON output_format reaches the server with PUT method."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "http_method": "PUT",
        "output_format": "json",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    assert len(capture_server.requests) == 1
    assert capture_server.requests[0]["method"] == "PUT"


@pytest.mark.asyncio
async def test_real_post_xml_round_trip(capture_server):
    """XML output_format sends the raw CoT bytes with application/xml Content-Type."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "output_format": "xml",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    assert len(capture_server.requests) == 1
    req = capture_server.requests[0]
    assert "application/xml" in req["content_type"]
    assert req["body"] == SAMPLE_COT_XML


@pytest.mark.asyncio
async def test_real_post_custom_template_round_trip(capture_server):
    """Custom template renders and is sent as text/plain."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "output_format": "custom_template",
        "custom_template": "ALERT: {callsign} at {lat},{lon}",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    assert len(capture_server.requests) == 1
    req = capture_server.requests[0]
    assert "text/plain" in req["content_type"]
    body_text = req["body"].decode()
    assert "INTEG-1" in body_text


@pytest.mark.asyncio
async def test_custom_headers_arrive_on_wire(capture_server):
    """Custom headers declared in config are actually present in the HTTP request."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "custom_headers": "X-Api-Key: supersecret\nX-Source: trakbridge",
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    assert len(capture_server.requests) == 1
    req_headers = capture_server.requests[0]["headers"]
    assert req_headers.get("X-Api-Key") == "supersecret"
    assert req_headers.get("X-Source") == "trakbridge"


@pytest.mark.asyncio
async def test_server_500_drops_event_no_crash(error_server):
    """When the server returns 500, the plugin logs and drops without crashing."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": error_server.url,
        "message_rules": MINIMAL_RULES,
    })
    # Must not raise
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 0
    assert stats["events_dropped"] == 1
    assert stats["last_error"] is not None


@pytest.mark.asyncio
async def test_timeout_respected(capture_server):
    """Plugin connects successfully within the timeout window."""
    from plugins.outbound_http import OutboundHTTP

    # With a generous timeout the connection should succeed normally
    plugin = OutboundHTTP({
        "endpoint_url": capture_server.url,
        "timeout_seconds": 5,
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    assert plugin.get_health_stats()["events_sent"] == 1


@pytest.mark.asyncio
async def test_short_timeout_to_unreachable_host_drops_event():
    """A very short timeout to an unreachable host results in events_dropped."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": "http://192.0.2.1:9999/hook",  # TEST-NET, unreachable
        "timeout_seconds": 1,
        "message_rules": MINIMAL_RULES,
    })
    await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
    stats = plugin.get_health_stats()
    assert stats["events_dropped"] == 1
