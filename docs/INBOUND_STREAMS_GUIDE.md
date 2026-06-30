# TrakBridge Inbound Streams - Developer Guide

## Overview

Inbound streams allow external devices and systems to push location data to TrakBridge via HTTP POST. TrakBridge converts the incoming data to CoT XML using inbound plugins and distributes it to TAK servers through the existing queue infrastructure.

This guide covers the architecture, API endpoints, plugin development, security model, and the outbound output plugins.

## Architecture

```text
External Device (JSON, XML, Protobuf, CSV, NMEA, ...)
    │
    │  HTTP POST /api/inbound/<stream_id>/data
    ▼
Flask Route (routes/inbound.py)
    │  Rate limit, auth, transform, validate
    ▼
InboundCOTService
    │  QueuedCOTService.create_cot_events()
    │  Queue + distribute to TAK servers
    ▼
TAK Server(s) → ATAK/WinTAK
```

### Key Principles

1. **Reuse Downstream Pipeline**: Inbound data enters the same queue/batch/TAK worker path as poll-based streams
2. **Plugin-Driven Parsing**: Each plugin handles its own payload format via `transform_payload()`
3. **Security by Default**: API key auth, rate limiting, anti-enumeration, coordinate validation
4. **Preview Before Live**: New inbound streams start in preview mode for field mapping verification

## Stream Modes

TrakBridge streams operate in one of two modes:

| Mode | Base Class | Trigger | Worker |
| --- | --- | --- | --- |
| `poll` | `BaseGPSPlugin` | Timer calls `fetch_locations()` | `StreamWorker` |
| `inbound` | `BaseInboundPlugin` | HTTP POST, or an active listener spawned in `start()` | `InboundStreamWorker` |

The `stream_mode` column on the `Stream` model determines which worker type is used.

Inbound plugins themselves use one of two transports, distinguished by the `inbound_transport` field of `plugin_metadata`:

| Transport | Driver | Plugin examples |
| --- | --- | --- |
| HTTP push | External device POSTs to `/api/inbound/...`; `transform_payload()` parses the body | `generic_inbound_plugin`, `generic_xml_inbound_plugin`, `inbound_http` |
| Active-connect | Plugin's `start()` dials out, opens a socket, or joins a multicast group; `transform_payload()` is not used | `inbound_active` (MQTT / WebSocket), `udp_multicast_listener` |

## Inbound Plugin Development

### BaseInboundPlugin

Inbound plugins extend `BaseInboundPlugin` (defined in `plugins/base_plugin.py`). The base class provides:

- `validate_config()`, `get_config_fields()`, `get_decrypted_config()`, `get_sensitive_fields()` — reused from the GPS plugin pattern
- Abstract methods that plugins must implement

### Required Methods

```python
from plugins.base_plugin import BaseInboundPlugin, PluginConfigField

class MyInboundPlugin(BaseInboundPlugin):

    @property
    def plugin_name(self) -> str:
        """Unique identifier for this plugin."""
        return "my_inbound_plugin"

    @property
    def plugin_metadata(self) -> dict:
        """Plugin metadata with category 'inbound', config fields, help sections."""
        return {
            "display_name": "My Inbound Plugin",
            "description": "Receives data from my custom device",
            "icon": "fa-satellite-dish",
            "category": "inbound",
            "config_fields": [
                PluginConfigField(
                    name="auth_mode",
                    label="Auth Mode",
                    field_type="select",
                    options=[
                        {"value": "api_key", "label": "API Key"},
                        {"value": "none", "label": "None"},
                    ],
                    default_value="api_key",
                ),
                # ... more fields
            ],
        }

    def transform_payload(
        self, raw_body: bytes, content_type: str, headers: dict
    ) -> list[dict]:
        """
        Convert raw request bytes into a list of location dictionaries.

        Each dict must contain at minimum: uid, lat, lon.
        Optional fields: callsign, speed, course, timestamp.

        The plugin handles ALL parsing — JSON, XML, Protobuf, CSV, NMEA, etc.
        """
        import json
        data = json.loads(raw_body)
        return [{
            "uid": data["device_id"],
            "lat": float(data["latitude"]),
            "lon": float(data["longitude"]),
            "callsign": data.get("name", data["device_id"]),
        }]

    def validate_inbound_request(
        self, headers: dict
    ) -> tuple[bool, str | None]:
        """
        Authenticate the request. Called BEFORE body parsing.

        Returns (True, None) if valid, or (False, "reason") if rejected.
        """
        # Default implementation checks API key from config
        return self._validate_api_key(headers)
```

### Location Dict Schema

The `transform_payload()` method must return a list of dictionaries with these fields:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `uid` | str | Yes | Unique device identifier |
| `lat` | float | Yes | Latitude (decimal degrees, ±90) |
| `lon` | float | Yes | Longitude (decimal degrees, ±180) |
| `callsign` | str | No | Display name for TAK marker |
| `speed` | float | No | Speed in m/s |
| `course` | float | No | Heading in degrees |
| `timestamp` | str/datetime | No | Event timestamp (ISO 8601) |

### Plugin Discovery

Inbound plugins are auto-discovered by `PluginManager` — no manual registration needed. Place your plugin file in `plugins/` and it will be detected on startup.

## Built-in Plugin: Generic JSON Inbound

The `GenericInboundPlugin` (`plugins/generic_inbound_plugin.py`) handles JSON payloads with configurable field mapping via dot-notation paths.

### Configuration Fields

| Field | Default | Description |
| --- | --- | --- |
| `auth_mode` | `api_key` | Authentication mode |
| `lat_field` | `lat` | Dot-notation path to latitude |
| `lon_field` | `lon` | Dot-notation path to longitude |
| `uid_field` | `id` | Dot-notation path to device UID |
| `callsign_field` | `name` | Dot-notation path to callsign |

### Dot-Notation Examples

For nested JSON structures, use dot notation:

```python
# Payload: {"position": {"latitude": 38.9, "longitude": -77.0}, "device": {"id": "d1"}}
# Config:  lat_field="position.latitude", lon_field="position.longitude", uid_field="device.id"
```

### Batch Support

The plugin accepts both single objects and arrays:

```json
// Single
{"id": "d1", "lat": 38.9, "lon": -77.0}

// Batch
[
  {"id": "d1", "lat": 38.9, "lon": -77.0},
  {"id": "d2", "lat": 39.0, "lon": -76.5}
]
```

## Built-in Plugin: UDP Multicast CoT Bridge

The `UdpMulticastListener` (`plugins/udp_multicast_listener.py`) joins a UDP multicast group and forwards CoT events to every TAK server configured on the stream. The intended use case is bridging LAN multicast Mesh SA (e.g. ATAK clients) across VPN/WAN links that do not carry multicast.

This is an **active-connect** plugin — it has no HTTP endpoint and does not call `transform_payload()`. The listener is opened in `start()` and torn down in `cleanup()`.

### Wire formats

The plugin accepts both ATAK wire formats and auto-detects per datagram:

| Format | Trigger | Forwarding |
| --- | --- | --- |
| CoT XML | Datagram starts with `<event …>` | Forwarded byte-for-byte to TAK servers |
| TAK Protocol v1 (Mesh SA protobuf) | Datagram starts with magic `0xbf 0x01 0xbf` | Decoded to CoT XML via `takproto`, then forwarded |

Decoded XML preserves the structured Detail submessages (`contact`, `__group`, `precisionlocation`, `status`, `takv`, `track`) plus the residual `xmlDetail` string. Times are converted from ms-since-epoch to ISO-8601 UTC.

### Configuration fields

| Field | Default | Description |
| --- | --- | --- |
| `multicast_group` | `239.2.3.1` | IPv4 multicast address (224.0.0.0/4) |
| `multicast_port` | `6969` | UDP port |
| `bind_interface` | `0.0.0.0` | Local IP for the IGMP join; set explicitly on multi-homed hosts |
| `source_filter` | empty | Comma-separated source IP allowlist; switches to IGMPv3 source-specific multicast when set |
| `max_packet_bytes` | `65535` | Drop datagrams larger than this |
| `per_source_rate_limit` | `200` | Per-source-IP token bucket cap (packets/sec); `0` disables |
| `require_cot_event_root` | `true` | Drop datagrams whose root element is not `<event>` (XML) or whose magic prefix isn't `0xbf 0x01 0xbf` (takproto) |
| `format` | `auto` | `auto`, `xml`, or `takproto` |

### Forwarding path

The plugin calls `QueuedCOTService.enqueue_event(bytes, tak_server_id)` directly for every configured TAK server — no `InboundCOTService.process_inbound_locations()` round-trip. This keeps the bytes on the wire to the TAK server bit-identical to the decoded CoT (or the originally-received XML), avoiding the parse-and-re-emit cost of the standard inbound path.

### Operator diagnostics

`cleanup()` (called when the stream stops) emits two INFO summary lines:

```text
UDP multicast listener stopped — received=812, forwarded=2436, dropped_validation=4, dropped_rate=0, dropped_size=0
UDP multicast forwarded-per-uid (top 3 of 3): ANDROID-abc=270, ANDROID-def=265, ANDROID-ghi=258
```

The per-UID counter is matched by the TX side's `TX written-per-uid for <server>: …` line emitted by the `QueuedCOTService` TX loop on exit. Comparing the two lets you locate silent drops between the bridge and the socket (queue overflow, transmission failures, etc).

### Running under Docker

UDP multicast does not cross Docker's default bridge network. A container whose only NIC is the bridge (typically `172.x.x.x`) will issue its IGMP join on that interface and never see the LAN traffic. The listener appears healthy in the log (`UDP multicast listener joined 239.2.3.1:6969`) but `received` stays at zero. There are two supported deployment topologies; pick based on whether the container sits behind a reverse proxy on a Docker network.

#### Option A — `macvlan` network (recommended behind Traefik / nginx)

Attach a second network on the host's LAN NIC. The container keeps its existing bridge IP for HTTP traffic (so the reverse proxy on the bridge network keeps working) and gets a real LAN IP for the multicast listener.

```yaml
networks:
  web:
    external: true            # whatever your reverse-proxy network is called

  lan_multicast:
    driver: macvlan
    driver_opts:
      parent: eth0            # host's LAN NIC (eth0, en0, enp3s0, ens18, ...)
    ipam:
      config:
        - subnet: 192.168.1.0/24       # match your real LAN subnet
          gateway: 192.168.1.1         # match your real LAN gateway
          ip_range: 192.168.1.240/29   # carve out IPs not handed out by DHCP;
                                       # ip_range must align to its mask
                                       # (a /29 must start on a multiple of 8)

services:
  trakbridge:
    networks:
      web: {}                          # reverse proxy keeps reaching you here
      lan_multicast:
        ipv4_address: 192.168.1.242    # one of the addresses in ip_range
```

Then in the multicast stream config:

- `multicast_group`, `multicast_port`: as desired
- `bind_interface`: set to the macvlan IP (`192.168.1.242` in this example) — not `0.0.0.0`. This makes the IGMP join deterministic on the LAN-facing interface.

**macvlan caveats:**

- On Linux, the Docker host machine cannot reach the macvlan container IP on the same NIC. Other devices on the LAN can. Not an issue when the reverse proxy reaches the container over the bridge network instead.
- The `parent` NIC must allow promiscuous-mode traffic. Bare metal and most hypervisors are fine; some cloud-VM virtual NICs are not.
- Docker Desktop for Mac/Windows does not support macvlan reliably (the VM doesn't expose host NICs the way Linux does). Use a Linux host for production multicast deployments.

#### Option B — `network_mode: host` (simplest when not behind a reverse proxy)

The container shares the host's network namespace directly:

```yaml
services:
  trakbridge:
    network_mode: host
    # delete `ports:` and `networks:` — host mode bypasses them
```

The multicast join lands on the host's NICs directly, just as a bare-metal deployment would. **Do not use this if Traefik / nginx is fronting TrakBridge on a Docker network** — host mode bypasses the network the reverse proxy is on, so the proxy won't route to it. Host networking is also not supported on Docker Desktop for Mac/Windows.

#### Common symptoms and fixes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Log says `joined 239.2.3.1:6969`, but `received` stays at 0 on stop | IGMP join landed on the Docker bridge interface, not the LAN NIC | Switch to macvlan or host mode (above); set `bind_interface` explicitly |
| Works in dev (bare metal) but not in Docker | Same as above | Same as above |
| Receives packets but only from some senders | Multi-homed host picked the wrong NIC, or IGMP snooping on an upstream switch is dropping multicast | Set `bind_interface` to the explicit LAN IP; check switch IGMP-snooping config |
| Traffic stops a few minutes after start | IGMP membership query timed out (some switches require periodic re-querying) | Confirm IGMP querier is enabled on the LAN switch; otherwise switch ATAK to a static multicast TTL |

### Out of scope

ATAK's "Network Encryption" Mesh SA option (pre-shared AES key) is **not yet supported**. Encrypted datagrams arrive opaque and fail validation. Implementation is pending a verified writeup of the on-wire layout from the ATAK-CIV `commoncommo` source.

## API Endpoints

All endpoints are under the `/api/inbound` blueprint, registered in `app.py`.

### Push Data

**POST** `/api/inbound/<stream_id>/data`

| Step | Action |
| --- | --- |
| 1 | Enforce payload size limit (1 MB) |
| 2 | Apply sliding-window rate limiting (per-stream, default 60/min) |
| 3 | Validate stream exists, is active, and is in `inbound` mode |
| 4 | Check optional IP allowlist |
| 5 | Validate Content-Type against plugin's `accepted_content_types` |
| 6 | Call `plugin.validate_inbound_request(headers)` for auth |
| 7 | Call `plugin.transform_payload(raw_body, content_type, headers)` |
| 8 | Validate coordinates (lat ±90, lon ±180) |
| 9 | Deduplicate via `DeviceStateManager` |
| 10 | Create CoT events and distribute to TAK servers |

**Anti-enumeration**: Steps 3, 4, and 6 all return an identical `{"error": "Not found"}, 404` response to prevent stream ID or API key enumeration.

**Response (202):**

```json
{
  "status": "accepted",
  "locations_received": 2,
  "events_created": 2,
  "servers": {
    "TAK1": {"success": true, "events_enqueued": 2}
  }
}
```

### Preview Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/<stream_id>/preview` | Return captured payloads with mapped results |
| POST | `/<stream_id>/preview/remap` | Re-run mapping with alternate config |
| DELETE | `/<stream_id>/preview` | Clear the capture buffer |

### Generate API Key

**POST** `/api/inbound/generate-api-key`

Requires `streams:write` permission. Returns a cryptographically secure API key.

## Security Model

### Authentication

- **Per-stream API keys** stored encrypted via `EncryptionService`
- Keys sent via `Authorization: Bearer <key>` header
- Timing-safe comparison via `hmac.compare_digest()` to prevent timing attacks
- API keys masked in all log output (last 4 chars only)

### Rate Limiting

Sliding 60-second window per stream, implemented in `routes/inbound.py`:

```python
_rate_limit_buckets: Dict[int, List[float]] = {}
```

Configurable via `inbound_rate_limit` on the `Stream` model.

### Payload Validation

| Check | Limit |
| --- | --- |
| Payload size | 1 MB (`MAX_PAYLOAD_BYTES`) |
| Locations per request | 100 (`MAX_LOCATIONS_PER_REQUEST`) |
| Latitude range | ±90 degrees |
| Longitude range | ±180 degrees |

### Deduplication

Uses the existing `DeviceStateManager` (`services/device_state_manager.py`):

- Tracks last-seen timestamp per device UID
- Rejects locations with timestamps older than or equal to the last-seen value
- Prevents duplicate positions from device retries

### IP Allowlisting

Optional per-stream CIDR allowlist stored as JSON in `inbound_ip_allowlist`:

```json
["10.0.0.0/8", "192.168.1.0/24"]
```

Requests from non-allowed IPs receive the same 404 as other failures.

## InboundCOTService

The `InboundCOTService` (`services/inbound_cot_service.py`) handles the CoT distribution step:

```python
async def process_inbound_locations(locations: list, stream: Stream) -> dict
```

1. Gets configured TAK servers for the stream
2. Creates CoT events via `QueuedCOTService.create_cot_events()`
3. Starts persistent workers for each TAK server
4. Enqueues events with per-server failure isolation
5. Returns per-server delivery status

## InboundStreamWorker

The `InboundStreamWorker` (`services/inbound_stream_worker.py`) manages the lifecycle of inbound streams:

- No poll loop — manages start/stop only
- Registers in the active stream registry for fast HTTP endpoint lookup
- Maintains a capture buffer (ring buffer, last 10 payloads) for preview mode

## Outbound Plugins

Three focused outbound plugins forward CoT from TAK servers to external systems. Each plugs into the existing RX worker routing in `cot_service_integration.py`.

- `plugins/outbound_http.py` — Outbound HTTP plugin (POST/PUT JSON/XML/template to an HTTP endpoint).
- `plugins/outbound_mqtt.py` — Outbound MQTT plugin (publish CoT to an MQTT broker topic).
- `plugins/outbound_websocket.py` — Outbound WebSocket plugin (push CoT to a WebSocket endpoint).

Users wanting inbound and outbound on the same transport should combine an inbound stream (e.g. `inbound_active` or `udp_multicast_listener`) with the matching outbound plugin.

### Conditional Field Visibility

The plugins use `PluginConfigField` metadata attributes for conditional UI rendering:

| Attribute | Purpose |
| --- | --- |
| `group` | Groups fields under section headers |
| `depends_on` | Shows/hides fields based on other field values |
| `row_group` | Places fields with matching values side-by-side |

These are serialized via `to_dict()` and consumed by `renderPluginConfig()` in the templates.

## Stream Model Additions

The `Stream` model (`models/stream.py`) has these inbound-specific columns:

| Column | Type | Default | Description |
| --- | --- | --- | --- |
| `stream_mode` | String | `"poll"` | `"poll"` or `"inbound"` |
| `inbound_api_key` | String | null | Encrypted API key |
| `inbound_rate_limit` | Integer | 60 | Requests per minute |
| `inbound_ip_allowlist` | Text | null | JSON list of allowed CIDRs |
| `inbound_preview_mode` | Boolean | True | Start in preview mode |

## Testing

### Test Files

| File | Covers |
| --- | --- |
| `tests/unit/test_inbound_plugin.py` | `BaseInboundPlugin` instantiation, transform, validation |
| `tests/unit/test_inbound_security.py` | API key masking, coordinate bounds, payload size, content-type, IP allowlist, anti-enumeration, rate limiting |
| `tests/unit/test_inbound_dedup.py` | `DeviceStateManager`: stale rejection, new device acceptance, timestamp ordering |
| `tests/unit/test_inbound_routes.py` | HTTP endpoint: auth, rate limiting, payload validation, error cases |
| `tests/unit/test_generic_inbound_plugin.py` | JSON field mapping, nested paths, batch payloads |
| `tests/unit/test_udp_multicast_listener.py` | UDP multicast bridge: IGMP join, XML/takproto auto-detect, rate limit, per-UID counters |
| `tests/unit/test_inbound_preview.py` | Capture buffer, preview mode, remap |
| `tests/unit/test_outbound_http.py` | OutboundHTTP: metadata, pipeline, HTTP/JSON/XML/template delivery, dedup, health stats |
| `tests/integration/test_outbound_http_integration.py` | OutboundHTTP: real HTTP server, POST/PUT, headers, error handling |
| `tests/e2e/test_outbound_http_e2e.py` | OutboundHTTP: plugin discovery, batch delivery, geofence, rule filtering |
| `tests/unit/test_outbound_mqtt.py` | OutboundMQTT: metadata, pipeline, queue, dedup, rate limiting, health stats |
| `tests/integration/test_outbound_mqtt_integration.py` | OutboundMQTT: real mosquitto broker, publish, reconnect, TLS |
| `tests/e2e/test_outbound_mqtt_e2e.py` | OutboundMQTT: plugin discovery, batch delivery, geofence, buffer overflow |
| `tests/unit/test_outbound_websocket.py` | OutboundWebSocket: metadata, lifecycle, pipeline, writer, backoff, health stats |
| `tests/integration/test_outbound_websocket_integration.py` | OutboundWebSocket: real aiohttp WS server, reconnect, custom headers |
| `tests/e2e/test_outbound_websocket_e2e.py` | OutboundWebSocket: plugin discovery, batch delivery, geofence, buffer overflow |
| `tests/integration/test_inbound_e2e.py` | POST → CoT → queued for TAK |

### Running Tests

```bash
# All inbound tests
pytest tests/unit/test_inbound_*.py -v

# All outbound plugin tests
pytest tests/unit/test_outbound_*.py tests/integration/test_outbound_*.py tests/e2e/test_outbound_*.py -v

# Integration tests
pytest tests/integration/test_inbound_e2e.py -v

# Full suite
pytest tests/ -v
```

## Critical Files Reference

| File | Purpose |
| --- | --- |
| `plugins/base_plugin.py` | `BaseInboundPlugin` base class, `PluginConfigField` |
| `plugins/generic_inbound_plugin.py` | Built-in JSON inbound plugin |
| `plugins/udp_multicast_listener.py` | Built-in UDP multicast CoT bridge (XML + TAK Protocol v1 protobuf via `takproto`) |
| `plugins/outbound_http.py` | Outbound HTTP plugin (POST/PUT JSON/XML/template to an HTTP endpoint) |
| `plugins/outbound_mqtt.py` | Outbound MQTT plugin (publish CoT to an MQTT broker topic) |
| `plugins/outbound_websocket.py` | Outbound WebSocket plugin (push CoT to a WebSocket endpoint) |
| `routes/inbound.py` | HTTP endpoint, preview endpoints, API key generation |
| `services/inbound_cot_service.py` | Location → CoT → TAK distribution |
| `services/inbound_stream_worker.py` | Lifecycle manager + capture buffer |
| `services/device_state_manager.py` | Deduplication by UID + timestamp |
| `models/stream.py` | `stream_mode`, `inbound_api_key`, `inbound_preview_mode` columns |

---

*See also: [Output Plugins Guide](OUTPUT_PLUGINS_GUIDE.md) | [Plugin Development](PLUGIN_DEVELOPMENT.md) | [API Reference](API_REFERENCE.md)*
