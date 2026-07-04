# TrakBridge Output Plugins Guide

## Overview

Output plugins receive CoT messages from TAK servers (via the RX worker) and forward them to external systems — HTTP endpoints, MQTT brokers, WebSocket servers, UDP multicast groups, and messaging platforms.

Unlike GPS input plugins that *fetch* location data and *send* it to TAK, output plugins work in the opposite direction: TAK → TrakBridge → external system.

Plugins appear under one of two categories in the stream creation UI:

- **CoT Forwarding** (`forwarding`) — forward raw CoT events to external systems: `outbound_http`, `outbound_mqtt`, `outbound_websocket`, `udp_multicast_publisher`
- **Notifications** (`notification`) — post human-readable alerts to messaging platforms: `discord_handler`, `slack_handler`, `irc_handler`

## Architecture

```text
TAK Server → RX Worker → cot_service_integration.py
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   OutboundHTTP         OutboundMQTT       OutboundWebSocket
   UdpMulticastPublisher                  DiscordHandler
   (or any BaseOutputPlugin subclass)     SlackHandler / IRCHandler
          │                   │                   │
       HTTP/S              MQTT               WebSocket /
      endpoint             broker          messaging platform
```

### Key Principles

1. **Plugin-Driven Filtering** — Each plugin decides which messages to handle via message rules, UID regex, and geofence filters
2. **Shared Helper Module** — `services/output_plugin_helpers.py` provides CoT extraction, formatting, dedup, rate-limiting, and payload building that all forwarding plugins compose against
3. **Bounded Queues** — Each plugin maintains a bounded async queue with configurable overflow strategy (oldest-drop by default) to prevent memory growth under bursty traffic
4. **Encrypted Secrets** — Sensitive fields (URLs, passwords, tokens) are automatically encrypted at rest
5. **Secure XML Parsing** — All CoT XML is parsed via `defusedxml` to prevent XXE attacks

## CoT Forwarding Plugins

### OutboundHTTP (`outbound_http`)

POSTs or PUTs CoT events to any HTTP/HTTPS endpoint.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `endpoint_url` | URL | Yes | Destination URL (http:// or https:// only) |
| `http_method` | Select | No | `POST` (default) or `PUT` |
| `payload_format` | Select | No | `json`, `xml`, or `template` |
| `template` | Text | No | Message template (used when `payload_format=template`) |
| `custom_headers` | Text | No | `Header: value` lines; CRLF injection prevention applied |
| `timeout_seconds` | Number | No | HTTP request timeout (default 10s) |
| `dedup_ttl_seconds` | Number | No | Deduplication window; `0` disables (default 5s) |
| `rate_limit_per_minute` | Number | No | Max events per minute; `0` disables |

Plus `message_rules` and `global_geofence` custom components (see [Filtering](#filtering)).

**Scheme allow-listing**: Non-http/https URLs are rejected with a log message before any network I/O.

**CRLF injection prevention**: `parse_custom_headers()` strips any header value containing `\r` or `\n` before passing headers to aiohttp.

#### Payload Formats

**JSON** (default):
```json
{
  "uid": "ANDROID-abc123",
  "callsign": "Alpha-1",
  "type": "a-f-G-U-C",
  "lat": 38.897,
  "lon": -77.036,
  "hae": 100.0,
  "speed": 2.5,
  "course": 270.0,
  "remarks": "On route",
  "battery": 85,
  "group_name": "Cyan",
  "group_role": "Team Member",
  "mgrs": "18SUJ2348306479",
  "timestamp": "2026-07-02T10:00:00Z",
  "tak_server_id": 1
}
```

**XML**: Raw CoT XML bytes forwarded verbatim.

**Template**: Use `{variable}` placeholders. Available variables:
`{callsign}`, `{uid}`, `{type}`, `{lat}`, `{lon}`, `{hae}`, `{speed}`, `{course}`, `{remarks}`, `{battery}`, `{group_name}`, `{group_role}`, `{mgrs}`, `{timestamp}`

#### Example

```bash
curl -X POST http://localhost:8080/api/inbound/5/data \
  -H "Content-Type: application/json" \
  -d '{"endpoint_url": "https://api.example.com/cot", "payload_format": "json"}'
```

---

### OutboundMQTT (`outbound_mqtt`)

Publishes CoT events to an MQTT broker topic with a persistent paho-mqtt connection.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `broker_url` | Text | Yes | `mqtt://host:1883` or `mqtts://host:8883` |
| `topic` | Text | Yes | MQTT topic to publish to |
| `client_id` | Text | No | MQTT client ID (auto-generated if blank) |
| `username` | Text | No | Broker username |
| `password` | Password | No | Broker password (encrypted) |
| `qos` | Select | No | QoS level: `0`, `1`, or `2` (default `1`) |
| `payload_format` | Select | No | `json`, `xml`, or `template` |
| `template` | Text | No | Message template |
| `ca_cert_file` | Text | No | Path to CA cert for `mqtts://` |
| `client_cert_file` | Text | No | Path to client cert for mTLS |
| `client_key_file` | Text | No | Path to client key for mTLS |
| `dedup_ttl_seconds` | Number | No | Deduplication window (default 5s) |
| `rate_limit_per_minute` | Number | No | Max events per minute; `0` disables |

Plus `message_rules` and `global_geofence` custom components.

**TLS**: `mqtts://` URLs use `cert_utils.build_ssl_context()` (the same cert infrastructure as TAK server connections), not paho's `client.tls_set()` directly.

**Reconnection**: paho auto-reconnect via `loop_start()`/`loop_stop()`. Bad-auth detection: plugin stays disconnected with a clear log message when credentials are rejected by the broker.

**Bounded queue**: Oldest events are dropped when the queue fills. Every drop increments `events_dropped` in the plugin stats.

---

### OutboundWebSocket (`outbound_websocket`)

Maintains a persistent aiohttp WebSocket connection and streams CoT events.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `endpoint_url` | URL | Yes | WebSocket URL (ws:// or wss:// only) |
| `payload_format` | Select | No | `json`, `xml`, or `template` |
| `template` | Text | No | Message template |
| `custom_headers` | Text | No | Extra HTTP headers for the WS upgrade request |
| `reconnect_delay_seconds` | Number | No | Initial backoff delay (default 1s, caps at 30s) |
| `dedup_ttl_seconds` | Number | No | Deduplication window (default 5s) |
| `rate_limit_per_minute` | Number | No | Max events per minute; `0` disables |

Plus `message_rules` and `global_geofence` custom components.

**Scheme allow-listing**: Non-ws/wss URLs are rejected before any connection attempt.

**URL credential redaction**: Username/password in the URL are stripped before any log statement in `_connect()`.

**Reconnection**: Exponential backoff starting at `reconnect_delay_seconds`, capped at 30s. A background reader task detects server-side closes so reconnection begins immediately rather than waiting for the next send attempt.

**Bounded queue**: Same oldest-drop semantics as OutboundMQTT.

---

### UdpMulticastPublisher (`udp_multicast_publisher`)

Publishes CoT events to a UDP multicast group. Intended for bridging CoT from a TAK server onto a LAN segment where ATAK clients listen on a multicast address.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `multicast_group` | Text | Yes | IPv4 multicast address (e.g. `239.2.3.1`) |
| `multicast_port` | Number | Yes | UDP port (e.g. `6969`) |
| `bind_interface` | Text | No | Local IP to bind; leave blank for `0.0.0.0` |
| `ttl` | Number | No | Multicast TTL (default `1` — LAN only) |
| `payload_format` | Select | No | `xml` (default) or `json` |

Plus `message_rules` and `global_geofence` custom components.

**Metrics**: Forwarded event counts are persisted to the stream DB record via a batched flush every 30 seconds and on plugin stop. This means the "Messages Sent" counter on the stream detail page reflects actual delivery.

---

## Notification Plugins

### SlackHandler (`slack_handler`)

Forwards CoT messages to a Slack channel via an incoming webhook using Block Kit formatting.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_url` | URL | Yes | Slack incoming webhook URL (encrypted) |
| `uid_filter` | Text | No | Global UID regex pre-filter applied before message rules |

Plus `message_rules` and `global_geofence` custom components.

#### Message Formatting

Slack messages use Block Kit rich formatting. Template variables available in message rules:

`{type}`, `{uid}`, `{callsign}`, `{remarks}`, `{lat}`, `{lon}`, `{hae}`, `{mgrs}`, `{group_name}`, `{group_role}`, `{device}`, `{platform}`, `{battery}`, `{speed}`, `{course}`, `{time}`, `{stale}`, `{xmpp_username}`

#### Example Message Rule Templates

- Chat: `[CHAT] {callsign}: {remarks}`
- Emergency: `[EMERGENCY] {callsign} at {mgrs}`
- Friendly position: `[{group_name}] {callsign} ({group_role}) - Battery: {battery}%`

#### Notes

- At least one message rule is required for messages to be sent
- Messages are deduplicated within a 5-second window
- Webhook URL is masked on edit forms (stored encrypted)

---

### IRCHandler (`irc_handler`)

Forwards CoT messages to an IRC channel over plain TCP or SSL.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `server` | Text | Yes | IRC server hostname |
| `port` | Number | Yes | IRC port (6667 plain, 6697 SSL) |
| `use_ssl` | Select | Yes | Enable SSL/TLS (`true`/`false`) |
| `verify_ssl` | Select | No | Verify SSL certificate (`true`/`false`, default `true`) |
| `nickname` | Text | Yes | Bot nickname |
| `channel` | Text | Yes | Channel to join (include `#`) |
| `password` | Password | No | Server/NickServ password (encrypted) |
| `uid_filter` | Text | No | Global UID regex pre-filter |

Plus `message_rules` and `global_geofence` custom components.

#### Notes

- Maintains a persistent connection with PING/PONG keepalive and async reader task
- Messages longer than 400 characters are split automatically
- At least one message rule required; 5-second deduplication window

---

### DiscordHandler (`discord_handler`)

Forwards CoT messages to a Discord channel via an incoming webhook.

#### Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_url` | URL | Yes | Discord incoming webhook URL (encrypted) |
| `webhook_username` | Text | No | Override webhook display name |
| `webhook_avatar_url` | URL | No | Override webhook avatar image URL |
| `use_embeds` | Select | No | Use rich embed formatting (`true`/`false`, default `true`) |
| `uid_filter` | Text | No | Global UID regex pre-filter |

Plus `message_rules` and `global_geofence` custom components.

#### Message Formatting

When `use_embeds = true`, messages are posted as Discord embeds with colour-coded fields for MGRS location, battery, group/role, and remarks. When `false`, plain text template formatting is used.

Same template variables as SlackHandler.

#### Notes

- Webhook URL is masked on edit forms (stored encrypted)
- 5-second deduplication window; at least one message rule required

---

## Shared Output Plugin Helpers

`services/output_plugin_helpers.py` provides the shared pipeline that all three built-in plugins compose against. You can import these in custom output plugins too.

### CoT Variable Extraction

```python
from services.output_plugin_helpers import extract_cot_variables

variables = extract_cot_variables(cot_xml)
# Returns dict with: uid, callsign, type, lat, lon, hae, speed,
# course, remarks, battery, group_name, group_role, mgrs, timestamp
```

### Message Rule Filtering

```python
from services.output_plugin_helpers import should_handle_message, matches_message_rules

# Check message rules config component
if not matches_message_rules(variables, rules_config):
    return  # filtered out
```

### Geofence Filtering

```python
from services.output_plugin_helpers import is_within_geofence

if geofence_enabled and not is_within_geofence(lat, lon, geofence_config):
    return  # outside bounds
```

### Deduplication

```python
from services.output_plugin_helpers import Deduplicator

dedup = Deduplicator(ttl_seconds=5)
if dedup.is_duplicate(uid, timestamp):
    return  # already seen
```

### Rate Limiting

```python
from services.output_plugin_helpers import RateLimiter

limiter = RateLimiter(per_minute=60)
if not limiter.allow():
    return  # rate limited
```

### Payload Building

```python
from services.output_plugin_helpers import build_payload

payload = build_payload(variables, format="json", template=None)
# Returns bytes (JSON-encoded) or str depending on format
```

---

## Filtering

All three built-in plugins share the same filtering pipeline via `PluginCustomComponent` entries in `plugin_metadata`. Filters are evaluated in order; a message is handled only if all enabled filters pass.

### Message Rules

Defined as a `message_rules` custom component. Each rule has:

| Field | Description |
|-------|-------------|
| CoT type pattern | Wildcard-capable (e.g., `a-f-*`, `b-t-f`, `b-a-*`) |
| UID regex | Optional regex applied to the event UID |

A message passes if it matches **any** rule (OR logic across rules). If no rules are defined, all messages pass.

**Examples:**
- `a-f-*` — all friendly positions
- `b-t-f` — chat messages (exact)
- `b-a-*` with UID regex `^ANDROID-.*` — emergency alerts from Android devices only

### Global Geofence

Defined as a `global_geofence` custom component. When enabled, messages are only forwarded if the CoT event's `<point>` falls within the configured bounding box (lat/lon min/max).

An interactive Leaflet map on the stream detail page shows the configured bounding box.

### Deduplication

When `dedup_ttl_seconds > 0`, a message with the same UID that arrives within the TTL window is dropped. This prevents double-posting when TAK server re-broadcasts the same event.

---

## Creating Custom Output Plugins

### Step 1: Create the Plugin File

```python
# ABOUTME: MyHandler plugin — receives CoT from TAK and forwards to an external system
# ABOUTME: Extends BaseOutputPlugin; discovered automatically from plugins/ directory

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
from typing import Any, Dict
import aiohttp

_logger_instance = None

def get_logger():
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger
        _logger_instance = get_module_logger(__name__)
    return _logger_instance

class _LoggerProxy:
    def __getattr__(self, name):
        return getattr(get_logger(), name)

logger = _LoggerProxy()


class MyHandler(BaseOutputPlugin):

    @property
    def plugin_name(self) -> str:
        return "my_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "My Custom Handler",
            "description": "Routes CoT messages to my external system",
            "icon": "fa-rocket",
            "category": "forwarding",  # or "notification" for messaging plugins
            "config_fields": [
                PluginConfigField(
                    name="api_url",
                    label="API Endpoint URL",
                    field_type="url",
                    required=True,
                    help_text="Your external API endpoint (https:// recommended)"
                ),
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="API key — stored encrypted"
                ),
            ]
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        config = self.get_decrypted_config()
        try:
            root = DefusedET.fromstring(cot_xml)
            cot_type = root.get("type", "")
            uid = root.get("uid", "")

            # Only handle position reports
            if not cot_type.startswith("a-"):
                return

            detail = root.find("detail")
            callsign = "Unknown"
            if detail is not None:
                contact = detail.find("contact")
                if contact is not None:
                    callsign = contact.get("callsign", "Unknown")

            point = root.find("point")
            if point is None:
                return

            await self._post_to_api(config, uid, callsign, point)

        except Exception as e:
            logger.error(f"MyHandler failed: {e}")

    async def _post_to_api(self, config, uid, callsign, point):
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                config["api_url"],
                json={
                    "uid": uid,
                    "callsign": callsign,
                    "lat": float(point.get("lat")),
                    "lon": float(point.get("lon")),
                },
                headers={"Authorization": f"Bearer {config['api_key']}"},
            ) as resp:
                if resp.status >= 400:
                    logger.warning(f"MyHandler API returned {resp.status}")

    async def test_connection(self) -> Dict[str, Any]:
        config = self.get_decrypted_config()
        if not config.get("api_url"):
            return {"success": False, "error": "Missing API URL"}
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(config["api_url"]) as resp:
                    return {"success": resp.status < 500, "message": f"HTTP {resp.status}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

### Step 2: Plugin Discovery

Place the file in `plugins/`. The `PluginManager` scans `plugins/` on startup — no manual registration needed.

### Step 3: Compose with Shared Helpers (Recommended)

For dedup, rate limiting, and geofence filtering, compose against `output_plugin_helpers` rather than re-implementing:

```python
from services.output_plugin_helpers import (
    extract_cot_variables,
    Deduplicator,
    RateLimiter,
    is_within_geofence,
    build_payload,
)

class MyHandler(BaseOutputPlugin):

    def __init__(self, config):
        super().__init__(config)
        self._dedup = Deduplicator(ttl_seconds=5)
        self._rate_limiter = RateLimiter(per_minute=60)

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        variables = extract_cot_variables(cot_xml)
        if not variables:
            return

        if self._dedup.is_duplicate(variables["uid"], variables["timestamp"]):
            return

        if not self._rate_limiter.allow():
            return

        payload = build_payload(variables, format="json")
        await self._send(payload)
```

---

## BaseOutputPlugin API Reference

### Required Methods

#### `plugin_name` (property)
Unique plugin identifier — lowercase, underscores. Must be unique across all plugins.

#### `plugin_metadata` (property)
Returns plugin metadata for UI generation. Minimum required keys:

```python
{
    "display_name": "Human-Readable Name",
    "description": "What this plugin does",
    "icon": "fa-icon-name",
    "category": "forwarding",  # "forwarding", "notification", or "bidirectional"
    "config_fields": [...],
    # Optional custom components:
    "custom_components": [
        {"type": "message_rules", ...},
        {"type": "global_geofence", ...},
    ]
}
```

#### `handle_cot_message(cot_xml, tak_server_id)`
Process one CoT message. Called by the RX worker with a 10-second timeout.

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
    # cot_xml — raw CoT XML bytes from TAK server
    # tak_server_id — DB ID of the TAK server that sent this message
    pass
```

**Never re-raise exceptions** — one plugin raising will not stop other plugins from receiving the same message, but repeated exceptions will be logged.

### Inherited Helper Methods

| Method | Description |
|--------|-------------|
| `get_decrypted_config()` | Config dict with `sensitive=True` fields decrypted |
| `get_config_fields()` | List of `PluginConfigField` from metadata |
| `get_sensitive_fields()` | Names of fields marked `sensitive=True` |
| `validate_config()` | Validate config against metadata requirements |

### Optional Methods

#### `test_connection()`
Test connectivity to external system. Called from UI "Test Connection" button.

```python
async def test_connection(self) -> Dict[str, Any]:
    return {
        "success": True,      # bool
        "message": "...",     # shown to user
        # "error": "..."      # on failure
    }
```

---

## Configuration Field Reference

### PluginConfigField Parameters

```python
PluginConfigField(
    name="field_name",            # Internal identifier (DB key)
    label="Field Label",          # UI display label
    field_type="text",            # See types below
    required=False,
    placeholder="Enter value...",
    help_text="Shown below field",
    default_value=None,
    options=[],                   # For select fields only
    min_value=None,               # For number fields
    max_value=None,               # For number fields
    sensitive=False,              # Auto-encrypt this field
    group=None,                   # Group header label
    depends_on=None,              # {"field": "name", "value": "val"}
    row_group=None,               # Side-by-side layout key
)
```

### Field Types

| Type | Description |
|------|-------------|
| `text` | Single-line text |
| `password` | Masked input — set `sensitive=True` |
| `url` | URL input |
| `email` | Email input |
| `number` | Numeric input — optional `min_value`/`max_value` |
| `select` | Dropdown — requires `options` list |
| `api_key` | Text with "Generate" button |
| `checkbox` | Boolean toggle |
| `textarea` | Multi-line text |

---

## CoT Message Types Reference

| Pattern | Description |
|---------|-------------|
| `a-f-*` | Friendly positions |
| `a-h-*` | Hostile positions |
| `a-n-*` | Neutral positions |
| `a-u-*` | Unknown positions |
| `b-t-f` | Chat messages |
| `b-a-*` | Emergency alerts |
| `b-m-p-*` | Mission/planning items |

---

## Parsing CoT XML

### Always Use defusedxml

```python
# SAFE — protected from XXE
from defusedxml import ElementTree as DefusedET
root = DefusedET.fromstring(cot_xml)

# NEVER use standard xml.etree — vulnerable to XXE
# from xml.etree import ElementTree  # DON'T DO THIS
```

### Common Extraction Patterns

```python
root = DefusedET.fromstring(cot_xml)

# Event attributes
cot_type = root.get("type")
uid      = root.get("uid")
time     = root.get("time")

# Location
point = root.find("point")
if point is not None:
    lat = float(point.get("lat"))
    lon = float(point.get("lon"))
    hae = float(point.get("hae", "0"))

# Callsign and remarks
detail = root.find("detail")
if detail is not None:
    contact = detail.find("contact")
    callsign = contact.get("callsign", "Unknown") if contact is not None else "Unknown"

    remarks = detail.find("remarks")
    text = remarks.text if remarks is not None else ""

    # Team colour/role
    group = detail.find("__group")
    if group is not None:
        team_name = group.get("name", "")
        team_role = group.get("role", "")

    # Speed/course
    track = detail.find("track")
    if track is not None:
        speed  = float(track.get("speed", "0"))
        course = float(track.get("course", "0"))
```

Use `extract_cot_variables()` from `output_plugin_helpers` to get all of the above in one call.

---

## Best Practices

### 1. Filter early
Check message rules, UID, and geofence before any parsing or network I/O.

### 2. Never re-raise from `handle_cot_message`
Log and return. One plugin crashing must not stop others from receiving the same event.

### 3. Set timeouts on all network calls
```python
timeout = aiohttp.ClientTimeout(total=10)
async with aiohttp.ClientSession(timeout=timeout) as session:
    ...
```

### 4. Use `await`, never `time.sleep()`
`time.sleep()` blocks the event loop. Use `await asyncio.sleep()`.

### 5. Redact credentials from logs
Never log webhook URLs, API keys, or passwords in plaintext.

### 6. Mark sensitive fields with `sensitive=True`
Fields with `sensitive=True` are encrypted at rest automatically and masked on edit forms.

---

## Troubleshooting

### Plugin Not Discovered
- File must be in `plugins/` directory
- Class must inherit from `BaseOutputPlugin`
- Check for syntax errors: `python -m py_compile plugins/my_handler.py`
- Review startup logs for import errors

### Messages Not Arriving
- Verify the TAK server has `enable_rx = true`
- Check message rule filters are not too restrictive (try removing rules temporarily)
- Confirm the stream is associated with the correct TAK server
- Review plugin logs for filtering decisions

### Connection Failures
- Use "Test Connection" button in the stream UI to validate credentials
- Check firewall rules between TrakBridge container and target service
- Verify TLS certificates are valid and trusted
- Check for scheme allow-listing rejections in logs (`endpoint_url must use http/https`)

### High Memory / Queue Build-up
- Lower `rate_limit_per_minute` to throttle output
- Reduce message rules scope to fewer CoT types
- Enable geofence to drop out-of-area events
- Monitor `events_dropped` stat in the stream detail page

---

## Migration from webhook_handler

The legacy `webhook_handler` plugin was removed in v1.3.0. Migrate existing streams:

| Old plugin | New plugin | Notes |
|-----------|-----------|-------|
| `webhook_handler` (HTTP) | `outbound_http` | Configure `endpoint_url`, `payload_format`; re-enter message rules in the new UI component |
| `webhook_handler` (bidirectional) | `outbound_http` + inbound stream | Split into separate outbound and inbound streams |

Message rules and geofence config must be re-entered in the new `message_rules` and `global_geofence` UI components — they are not migrated automatically.

---

## Additional Resources

- [Inbound Streams Guide](INBOUND_STREAMS_GUIDE.md) — push-based and active-connect inbound plugins
- [Handler Plugin Development Guide](HANDLER_PLUGIN_DEVELOPMENT_GUIDE.md) — detailed development walkthrough with examples
- [Plugin Development Guide](PLUGIN_DEVELOPMENT.md) — GPS input plugin development
- [CoT XML Reference](https://github.com/TAK-Product-Center/Server/wiki/CoT-XML) — official CoT schema
- [defusedxml](https://pypi.org/project/defusedxml/) — secure XML parsing library
- `docs/example_external_plugins/sample_custom_handler.py` — production-ready reference implementation
