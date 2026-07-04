# ABOUTME: End-to-end tests for OutboundHTTP using real helpers and a real aiohttp server.
# ABOUTME: Validates plugin discovery, mixed-batch processing, and health counters.

import json

import pytest
from aiohttp import web

# ---------------------------------------------------------------------------
# Sample CoT XML fixtures
# ---------------------------------------------------------------------------

FRIENDLY_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-e2e-friendly"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="FRIENDLY-E2E"/>
  </detail>
</event>"""

HOSTILE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-h-G" uid="hostile-e2e"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="h-e">
  <point lat="39.0" lon="-76.0" hae="100" ce="50" le="50"/>
  <detail>
    <contact callsign="HOSTILE-E2E"/>
  </detail>
</event>"""

DRONE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-A-M-F-U" uid="DRONE-e2e-001"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.9" lon="-77.0" hae="100" ce="5" le="5"/>
  <detail>
    <contact callsign="DRONE-E2E"/>
  </detail>
</event>"""


# ---------------------------------------------------------------------------
# Local capture server fixture
# ---------------------------------------------------------------------------


class _E2EServer:
    """Captures all requests received during the E2E test."""

    def __init__(self):
        self.requests = []
        self._runner = None
        self._site = None
        self.port = None

    async def _handler(self, request: web.Request) -> web.Response:
        body = await request.read()
        self.requests.append({
            "method": request.method,
            "body": body,
            "content_type": request.content_type,
        })
        return web.Response(status=200, text="ok")

    async def start(self):
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        self.port = self._site._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/events"


@pytest.fixture
async def e2e_server():
    server = _E2EServer()
    await server.start()
    yield server
    await server.stop()


# ---------------------------------------------------------------------------
# Plugin discovery test
# ---------------------------------------------------------------------------


def test_plugin_manager_discovers_outbound_http():
    """plugin_manager must find and register the outbound_http plugin."""
    from plugins.plugin_manager import PluginManager

    manager = PluginManager()
    manager.load_plugins_from_directory("plugins")

    registered_names = list(manager.plugins.keys())
    assert "outbound_http" in registered_names, (
        f"outbound_http not found. Registered: {registered_names}"
    )


# ---------------------------------------------------------------------------
# Mixed-batch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_batch_only_matching_events_reach_server(e2e_server):
    """
    Batch: 1 friendly (passes), 1 hostile (dropped by rules), 1 duplicate friendly (dedup).
    Exactly 1 request must reach the server.
    """
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": e2e_server.url,
        "output_format": "json",
        "dedup_enabled": "true",
        "dedup_ttl_seconds": 60,
        "message_rules": [
            # Only pass friendly CoT types
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })

    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)   # sent
    await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)    # dropped — no rule match
    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)   # dropped — duplicate

    assert len(e2e_server.requests) == 1, (
        f"Expected 1 request, got {len(e2e_server.requests)}"
    )
    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 2


@pytest.mark.asyncio
async def test_uid_filter_combined_with_rules(e2e_server):
    """
    UID filter rejects DRONE-* before rules are checked; ANDROID-* passes through.
    """
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": e2e_server.url,
        "uid_filter": "^ANDROID-.*",
        "output_format": "json",
        "dedup_enabled": "false",
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })

    await plugin.handle_cot_message(DRONE_COT_XML, tak_server_id=1)     # dropped — UID filter
    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # sent

    assert len(e2e_server.requests) == 1
    body = json.loads(e2e_server.requests[0]["body"])
    assert body["cot"]["uid"] == "ANDROID-e2e-friendly"

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 1


@pytest.mark.asyncio
async def test_health_stats_match_batch_expectations(e2e_server):
    """Drive 5 events (3 pass, 1 dup, 1 no-match) and verify counters."""
    from plugins.outbound_http import OutboundHTTP

    plugin = OutboundHTTP({
        "endpoint_url": e2e_server.url,
        "output_format": "json",
        "dedup_enabled": "true",
        "dedup_ttl_seconds": 60,
        "message_rules": [
            {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
        ],
    })

    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # sent — uid: ANDROID-e2e-friendly
    await plugin.handle_cot_message(DRONE_COT_XML, tak_server_id=1)     # sent — uid: DRONE-e2e-001
    await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)   # dropped — no rule match
    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # dropped — duplicate
    await plugin.handle_cot_message(DRONE_COT_XML, tak_server_id=1)     # dropped — duplicate

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 2, f"Got {stats}"
    assert stats["events_dropped"] == 3, f"Got {stats}"
    assert len(e2e_server.requests) == 2


@pytest.mark.asyncio
async def test_geofence_filters_batch(e2e_server):
    """Events outside geofence are dropped; events inside pass."""
    from plugins.outbound_http import OutboundHTTP

    # Both FRIENDLY and DRONE are near Washington DC (~38.9N, -77W)
    # Tight geofence centred there — HOSTILE at 39N, -76E is also inside
    # Use a very tight box that only includes lat<38.95 to exclude HOSTILE (lat=39.0)
    plugin = OutboundHTTP({
        "endpoint_url": e2e_server.url,
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

    await plugin.handle_cot_message(FRIENDLY_COT_XML, tak_server_id=1)  # inside box → sent
    await plugin.handle_cot_message(HOSTILE_COT_XML, tak_server_id=1)   # outside box → dropped

    assert len(e2e_server.requests) == 1
    body = json.loads(e2e_server.requests[0]["body"])
    assert body["cot"]["uid"] == "ANDROID-e2e-friendly"

    stats = plugin.get_health_stats()
    assert stats["events_sent"] == 1
    assert stats["events_dropped"] == 1
