# TrakBridge Output Plugins - Developer Guide

## Overview

Output plugins allow TrakBridge to receive and process CoT (Cursor on Target) messages from TAK servers. Unlike GPS input plugins that fetch location data and send it to TAK, output plugins **receive** CoT messages from TAK and route them to external systems like Slack, IRC, databases, or custom integrations.

## Architecture

```text
TAK Server → RX Worker → Output Plugins → External Systems
                              ↓
                    ┌─────────┴─────────┐
                    │                   │
              SlackHandler      IRCHandler      CotArchiver
                    │                   │              │
                  Slack               IRC          Database
```

### Key Principles

1. **Zero Core Assumptions**: The RX worker delivers raw CoT XML to ALL output plugins
2. **Plugin-Driven Filtering**: Each plugin decides which messages to handle
3. **Secure Parsing**: Plugins use `defusedxml` for safe XML parsing
4. **Flexible Configuration**: Dynamic UI generation from plugin metadata
5. **Encrypted Secrets**: Sensitive fields (webhooks, passwords) are automatically encrypted

## Available Output Plugins

### 1. SlackHandler (`slack_handler`)

Routes CoT messages to Slack channels via incoming webhooks.

#### Use Cases
- Team chat notifications for TAK events
- Emergency alerts to Slack channels
- Custom CoT message monitoring
- Integration with Slack workflows

#### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `webhook_url` | URL | Yes | Slack incoming webhook URL (encrypted) |
| `message_types` | Text | No | Comma-separated CoT types (e.g., `b-t-f,b-a-*`) |
| `uid_filter` | Text | No | Regex pattern to filter by UID (e.g., `^ANDROID-.*`) |

#### Message Type Examples
- `b-t-f` - Chat messages (exact match)
- `b-a-*` - All emergency alerts (wildcard)
- `b-t-f,b-a-o-tbl` - Chat and specific emergency type

#### Example Configuration
```python
{
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "message_types": "b-t-f,b-a-*",  # Chat and emergencies
    "uid_filter": "^ANDROID-.*"      # Only Android devices
}
```

#### Message Formatting
- **Chat** (b-t-f): 💬 **Callsign**: Message text
- **Emergency** (b-a-*): 🚨 **EMERGENCY**: Callsign
- **Position** (a-*): Filtered by default to avoid spam
- **Custom**: 📡 **Callsign**: CoT Type

#### Testing Connection
Uses `test_connection()` to send a test message to the configured webhook.

---

### 2. IRCHandler (`irc_handler`)

Routes CoT messages to IRC channels for real-time team communication.

#### Use Cases
- Bridge TAK to IRC operations channels
- Chat relay between TAK and IRC teams
- Emergency notifications to IRC ops channel
- Integration with IRC bots and automation

#### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `server` | Text | Yes | IRC server hostname |
| `port` | Number | Yes | IRC port (6667 plain, 6697 SSL) |
| `use_ssl` | Select | Yes | Enable SSL/TLS encryption |
| `nickname` | Text | Yes | Bot nickname |
| `channel` | Text | Yes | Channel to join (include #) |
| `password` | Password | No | Server password (encrypted) |
| `message_types` | Text | No | Comma-separated CoT types |
| `uid_filter` | Text | No | Regex pattern to filter by UID |

#### Example Configuration
```python
{
    "server": "irc.libera.chat",
    "port": 6697,
    "use_ssl": "true",
    "nickname": "TrakBridge",
    "channel": "#tak-ops",
    "message_types": "b-t-f,b-a-*",
    "uid_filter": ""  # Optional
}
```

#### Message Formatting
- **Chat**: `[CHAT] Callsign: Message text`
- **Emergency**: `[EMERGENCY] Callsign`
- **Custom**: `[cot-type] Callsign`

#### Connection Management
- Persistent connection with auto-reconnect
- Proper IRC handshake (NICK, USER, JOIN)
- Long message splitting (400 char limit)
- Graceful cleanup on shutdown (PART, QUIT)

#### Testing Connection
Connects to IRC server, joins channel, and sends test message.

---

### 3. CotArchiver (`cot_archiver`)

Archives CoT messages to database for audit trail and replay.

#### Use Cases
- Audit trail for compliance
- Message replay and analysis
- Historical data queries
- Debugging and troubleshooting
- Custom reporting and analytics

#### Configuration

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `archive_all` | Select | Yes | Archive all messages or filter by type |
| `message_types` | Text | No | Types to archive (if not archiving all) |
| `include_position_updates` | Select | Yes | Archive position updates (high volume) |
| `retention_days` | Number | No | Days to keep messages (0 = forever) |

#### Example Configurations

**Archive Everything Except Positions:**
```python
{
    "archive_all": "true",
    "include_position_updates": "false",
    "retention_days": 30
}
```

**Archive Only Chat and Emergencies:**
```python
{
    "archive_all": "false",
    "message_types": "b-t-f,b-a-*",
    "retention_days": 90
}
```

#### Database Schema

The `cot_messages` table stores:
- `tak_server_id` - Source TAK server
- `cot_xml` - Raw CoT XML
- `cot_type` - CoT message type
- `uid` - Device UID
- `callsign` - Device callsign
- `cot_time` - Original CoT timestamp
- `received_at` - TrakBridge receive time

#### Indexes
- `tak_server_id + received_at` - Server timeline queries
- `cot_type + received_at` - Type-based queries
- `uid + received_at` - Device history queries
- Individual indexes on callsign, cot_type, uid

#### Querying Archived Messages

```python
from models.cot_message import CotMessage
from datetime import datetime, timedelta

# Get recent emergencies
emergencies = CotMessage.query.filter(
    CotMessage.cot_type.like('b-a-%'),
    CotMessage.received_at >= datetime.utcnow() - timedelta(hours=24)
).all()

# Get all messages from a device
device_history = CotMessage.query.filter_by(
    uid='ANDROID-123'
).order_by(CotMessage.received_at.desc()).limit(100).all()

# Get messages by TAK server
server_messages = CotMessage.query.filter_by(
    tak_server_id=1
).order_by(CotMessage.received_at.desc()).all()
```

---

## Creating Custom Output Plugins

### Step 1: Create Plugin File

Create a new file in `plugins/` directory (e.g., `plugins/my_handler.py`):

```python
# ABOUTME: MyHandler plugin for routing CoT messages to external system
# ABOUTME: Implements BaseOutputPlugin for custom CoT message handling

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
from typing import Any, Dict

# Lazy logger import
_logger_instance = None

def get_logger():
    """Get the module logger, initializing lazily to avoid circular imports"""
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger
        _logger_instance = get_module_logger(__name__)
    return _logger_instance

class _LoggerProxy:
    """Proxy that forwards all attribute access to the lazy logger"""
    def __getattr__(self, name):
        return getattr(get_logger(), name)

logger = _LoggerProxy()


class MyHandler(BaseOutputPlugin):
    """Custom handler for CoT messages"""

    @property
    def plugin_name(self) -> str:
        return "my_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "My Custom Handler",
            "description": "Routes CoT messages to my external system",
            "icon": "fa-rocket",  # FontAwesome icon
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="api_url",
                    label="API Endpoint URL",
                    field_type="url",
                    required=True,
                    help_text="Your external API endpoint"
                ),
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,  # Automatically encrypted
                    help_text="Your API authentication key"
                ),
                PluginConfigField(
                    name="message_types",
                    label="Message Types to Handle",
                    field_type="text",
                    placeholder="b-t-f,b-a-*",
                    help_text="Comma-separated CoT types"
                ),
            ]
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Process received CoT message"""
        config = self.get_decrypted_config()

        try:
            # Parse XML securely
            root = DefusedET.fromstring(cot_xml)

            # Extract fields
            cot_type = root.get("type", "")
            uid = root.get("uid", "")

            # Apply filtering
            if not self._should_handle(cot_type):
                return

            # Extract message details
            detail = root.find("detail")
            callsign = "Unknown"
            if detail is not None:
                contact = detail.find("contact")
                if contact is not None:
                    callsign = contact.get("callsign", "Unknown")

            # Send to your external system
            await self._send_to_external_api(cot_type, uid, callsign)

        except Exception as e:
            logger.error(f"MyHandler failed to process CoT: {e}")

    def _should_handle(self, cot_type: str) -> bool:
        """Filter logic"""
        config = self.get_decrypted_config()
        type_filter = config.get("message_types", "")

        if not type_filter:
            return True  # Handle all if no filter

        types = [t.strip() for t in type_filter.split(",")]
        for t in types:
            if t.endswith("*"):
                if cot_type.startswith(t[:-1]):
                    return True
            elif cot_type == t:
                return True

        return False

    async def _send_to_external_api(self, cot_type: str, uid: str, callsign: str):
        """Send to your API"""
        import aiohttp

        config = self.get_decrypted_config()
        api_url = config.get("api_url")
        api_key = config.get("api_key")

        payload = {
            "type": cot_type,
            "uid": uid,
            "callsign": callsign
        }

        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logger.error(f"API call failed: {resp.status}")

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to external system"""
        config = self.get_decrypted_config()
        api_url = config.get("api_url")

        if not api_url:
            return {
                "success": False,
                "error": "Missing API URL",
                "message": "Please configure API endpoint"
            }

        try:
            # Test API connectivity
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return {
                            "success": True,
                            "message": "Successfully connected to API"
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}",
                            "message": f"API returned error"
                        }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed"
            }
```

### Step 2: Plugin Discovery

Plugins are automatically discovered by the PluginManager. No registration needed!

### Step 3: Test Your Plugin

```python
from plugins.my_handler import MyHandler

# Create instance
config = {
    "api_url": "https://api.example.com/cot",
    "api_key": "your-key",
    "message_types": "b-t-f"
}

handler = MyHandler(config)

# Test connection
result = await handler.test_connection()
print(result)

# Test message handling
cot_xml = b'''<?xml version="1.0"?>
<event version="2.0" uid="TEST-123" type="b-t-f" time="2025-12-15T10:00:00Z" start="2025-12-15T10:00:00Z" stale="2025-12-15T10:05:00Z">
  <point lat="34.5" lon="-118.2" hae="100" ce="10" le="10"/>
  <detail>
    <contact callsign="TestUser"/>
    <remarks>Test message</remarks>
  </detail>
</event>'''

await handler.handle_cot_message(cot_xml, tak_server_id=1)
```

---

## BaseOutputPlugin API Reference

### Required Methods

#### `plugin_name` (property)
Returns the unique plugin identifier (lowercase, underscores).

```python
@property
def plugin_name(self) -> str:
    return "my_handler"
```

#### `plugin_metadata` (property)
Returns plugin metadata for UI generation.

```python
@property
def plugin_metadata(self) -> Dict[str, Any]:
    return {
        "display_name": "Human-Readable Name",
        "description": "What this plugin does",
        "icon": "fa-icon-name",  # FontAwesome icon
        "category": "output",     # or "bidirectional"
        "config_fields": [...]    # List of PluginConfigField
    }
```

#### `handle_cot_message(cot_xml, tak_server_id)`
Process received CoT message.

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
    """
    Args:
        cot_xml: Raw CoT XML bytes from TAK server
        tak_server_id: ID of TAK server that sent this message
    """
    pass
```

### Inherited Helper Methods

#### `get_decrypted_config()`
Get configuration with sensitive fields decrypted.

```python
config = self.get_decrypted_config()
api_key = config.get("api_key")  # Automatically decrypted
```

#### `get_config_fields()`
Get list of PluginConfigField objects from metadata.

```python
fields = self.get_config_fields()
for field in fields:
    print(f"{field.name}: {field.field_type}")
```

#### `get_sensitive_fields()`
Get list of sensitive field names for encryption.

```python
sensitive = self.get_sensitive_fields()
# Returns: ["api_key", "password", "webhook_url", ...]
```

#### `validate_config()`
Validate configuration against metadata requirements.

```python
if not self.validate_config():
    logger.error("Invalid configuration")
```

### Optional Methods

#### `test_connection()`
Test connectivity to external system.

```python
async def test_connection(self) -> Dict[str, Any]:
    return {
        "success": True,
        "message": "Connection successful"
    }
```

---

## Configuration Field Types

### Field Types

| Type | Description | Validation |
|------|-------------|------------|
| `text` | Single-line text | - |
| `password` | Password input | Set `sensitive=True` |
| `url` | URL input | Must start with http:// or https:// |
| `email` | Email input | Must contain @ |
| `number` | Numeric input | Optional min/max validation |
| `select` | Dropdown | Requires `options` list |

### PluginConfigField Parameters

```python
PluginConfigField(
    name="field_name",              # Database field name
    label="Field Label",            # UI display label
    field_type="text",              # Field type (see above)
    required=False,                 # Is field required?
    placeholder="Enter value...",   # Placeholder text
    help_text="Help description",   # Help text below field
    default_value=None,             # Default value
    options=[],                     # For select fields
    min_value=None,                 # For number fields
    max_value=None,                 # For number fields
    sensitive=False                 # Auto-encrypt this field?
)
```

### Select Field Options

```python
PluginConfigField(
    name="level",
    label="Alert Level",
    field_type="select",
    options=[
        {"value": "low", "label": "Low Priority"},
        {"value": "high", "label": "High Priority"},
        {"value": "critical", "label": "Critical"}
    ]
)
```

---

## CoT Message Types Reference

### Common CoT Types

| Type Pattern | Description | Example |
|--------------|-------------|---------|
| `b-t-f*` | Chat messages | `b-t-f` (simple chat) |
| `b-a-*` | Emergency alerts | `b-a-o-tbl` (troops in contact) |
| `a-f-*` | Friendly positions | `a-f-G-U-C` (friendly ground) |
| `a-h-*` | Hostile positions | `a-h-G` (hostile ground) |
| `a-n-*` | Neutral positions | `a-n-G` (neutral ground) |
| `a-u-*` | Unknown positions | `a-u-G` (unknown ground) |
| `b-m-p-*` | Mission/planning | Various mission types |

### Filtering Examples

**Exact Match:**
```python
"message_types": "b-t-f"  # Only simple chat
```

**Wildcard Match:**
```python
"message_types": "b-a-*"  # All emergencies
```

**Multiple Types:**
```python
"message_types": "b-t-f,b-a-*,a-f-*"  # Chat, emergencies, friendlies
```

---

## Parsing CoT XML

### Basic Structure

```xml
<event version="2.0" uid="DEVICE-UID" type="cot-type" time="..." start="..." stale="...">
  <point lat="34.5" lon="-118.2" hae="100" ce="10" le="10"/>
  <detail>
    <contact callsign="Device Name"/>
    <remarks>Additional information</remarks>
    <!-- Plugin-specific detail elements -->
  </detail>
</event>
```

### Parsing Example

```python
from defusedxml import ElementTree as DefusedET

root = DefusedET.fromstring(cot_xml)

# Event attributes
cot_type = root.get("type")
uid = root.get("uid")
time = root.get("time")
start = root.get("start")
stale = root.get("stale")

# Point location
point = root.find("point")
if point is not None:
    lat = float(point.get("lat"))
    lon = float(point.get("lon"))
    hae = float(point.get("hae"))  # Height above ellipsoid

# Contact info
detail = root.find("detail")
if detail is not None:
    contact = detail.find("contact")
    if contact is not None:
        callsign = contact.get("callsign")
        endpoint = contact.get("endpoint")  # IP:PORT

    # Remarks (chat messages)
    remarks = detail.find("remarks")
    if remarks is not None and remarks.text:
        message_text = remarks.text

    # Other detail elements
    link = detail.find("link")
    track = detail.find("track")
    # ... etc
```

### Security: Always Use defusedxml

❌ **NEVER** use standard xml.etree:
```python
# DANGEROUS - vulnerable to XXE attacks
from xml.etree import ElementTree
root = ElementTree.fromstring(cot_xml)  # DON'T DO THIS
```

✅ **ALWAYS** use defusedxml:
```python
# SAFE - protected from XXE attacks
from defusedxml import ElementTree as DefusedET
root = DefusedET.fromstring(cot_xml)  # DO THIS
```

---

## Best Practices

### 1. Filter Early
```python
def _should_handle(self, cot_type: str, uid: str) -> bool:
    """Filter before expensive operations"""
    if not self._matches_type_filter(cot_type):
        return False
    if not self._matches_uid_filter(uid):
        return False
    return True
```

### 2. Handle Errors Gracefully
```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
    try:
        # Process message
        pass
    except Exception as e:
        logger.error(f"Failed to process CoT: {e}")
        # Don't re-raise - prevents one plugin from crashing others
```

### 3. Use Timeouts
```python
async with aiohttp.ClientSession() as session:
    timeout = aiohttp.ClientTimeout(total=10)
    async with session.post(url, json=data, timeout=timeout) as resp:
        # Process response
        pass
```

### 4. Avoid Blocking Operations
```python
# ❌ Bad - blocks other plugins
time.sleep(5)

# ✅ Good - allows concurrent processing
await asyncio.sleep(5)
```

### 5. Log Important Events
```python
logger.info(f"Processed {cot_type} from {uid}")
logger.warning(f"Failed to send to API: {error}")
logger.error(f"Critical error: {error}", exc_info=True)
```

### 6. Test Your Plugin
```python
async def test_connection(self) -> Dict[str, Any]:
    """Always implement connection testing"""
    try:
        # Test connectivity
        # Validate credentials
        # Check permissions
        return {"success": True, "message": "All checks passed"}
    except Exception as e:
        return {"success": False, "error": str(e), "message": "Test failed"}
```

---

## Troubleshooting

### Plugin Not Discovered
- Ensure file is in `plugins/` directory
- Verify class inherits from `BaseOutputPlugin`
- Check for syntax errors in plugin file
- Review plugin manager logs

### Configuration Not Saving
- Verify all required fields are provided
- Check field types match metadata
- Ensure sensitive fields are marked with `sensitive=True`
- Review validation errors in logs

### Messages Not Being Received
- Verify TAK server has `enable_rx=True`
- Check message type filters
- Review UID filter regex
- Check plugin logs for errors

### Connection Test Failing
- Verify credentials are correct
- Check network connectivity
- Review firewall rules
- Ensure external service is accessible

### Performance Issues
- Add indexes to database queries (CotArchiver)
- Use connection pooling for HTTP clients
- Implement rate limiting
- Filter messages early in processing

---

## Examples

### Email Notifier Plugin

```python
class EmailNotifier(BaseOutputPlugin):
    """Send email notifications for critical CoT events"""

    @property
    def plugin_name(self) -> str:
        return "email_notifier"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Email Notifier",
            "description": "Send email alerts for critical events",
            "icon": "fa-envelope",
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="smtp_server",
                    label="SMTP Server",
                    field_type="text",
                    required=True
                ),
                PluginConfigField(
                    name="smtp_password",
                    label="SMTP Password",
                    field_type="password",
                    required=True,
                    sensitive=True
                ),
                PluginConfigField(
                    name="to_email",
                    label="Recipient Email",
                    field_type="email",
                    required=True
                ),
                PluginConfigField(
                    name="alert_types",
                    label="Alert Types",
                    field_type="text",
                    default_value="b-a-*",
                    help_text="CoT types to alert on"
                ),
            ]
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        config = self.get_decrypted_config()

        try:
            root = DefusedET.fromstring(cot_xml)
            cot_type = root.get("type", "")

            if not self._should_alert(cot_type):
                return

            # Extract details
            uid = root.get("uid", "")
            detail = root.find("detail")
            callsign = "Unknown"
            if detail is not None:
                contact = detail.find("contact")
                if contact is not None:
                    callsign = contact.get("callsign", "Unknown")

            # Send email
            await self._send_email(
                subject=f"TAK Alert: {cot_type}",
                body=f"Alert from {callsign} (UID: {uid})\nType: {cot_type}"
            )

        except Exception as e:
            logger.error(f"EmailNotifier failed: {e}")

    def _should_alert(self, cot_type: str) -> bool:
        config = self.get_decrypted_config()
        alert_types = config.get("alert_types", "")

        for pattern in alert_types.split(","):
            pattern = pattern.strip()
            if pattern.endswith("*"):
                if cot_type.startswith(pattern[:-1]):
                    return True
            elif cot_type == pattern:
                return True

        return False

    async def _send_email(self, subject: str, body: str):
        import aiosmtplib
        from email.message import EmailMessage

        config = self.get_decrypted_config()

        message = EmailMessage()
        message["From"] = config.get("from_email", "trakbridge@localhost")
        message["To"] = config.get("to_email")
        message["Subject"] = subject
        message.set_content(body)

        await aiosmtplib.send(
            message,
            hostname=config.get("smtp_server"),
            port=config.get("smtp_port", 587),
            username=config.get("smtp_username"),
            password=config.get("smtp_password"),
            use_tls=True
        )
```

### Geofence Filter Plugin

```python
class GeofenceFilter(BaseOutputPlugin):
    """Only process messages within defined geographic area"""

    @property
    def plugin_name(self) -> str:
        return "geofence_filter"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Geofence Filter",
            "description": "Filter messages by geographic bounds",
            "icon": "fa-map-marker",
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="min_lat",
                    label="Minimum Latitude",
                    field_type="number",
                    required=True
                ),
                PluginConfigField(
                    name="max_lat",
                    label="Maximum Latitude",
                    field_type="number",
                    required=True
                ),
                PluginConfigField(
                    name="min_lon",
                    label="Minimum Longitude",
                    field_type="number",
                    required=True
                ),
                PluginConfigField(
                    name="max_lon",
                    label="Maximum Longitude",
                    field_type="number",
                    required=True
                ),
                PluginConfigField(
                    name="webhook_url",
                    label="Alert Webhook URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    help_text="Send alerts for messages in geofence"
                ),
            ]
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        config = self.get_decrypted_config()

        try:
            root = DefusedET.fromstring(cot_xml)

            # Extract location
            point = root.find("point")
            if point is None:
                return

            lat = float(point.get("lat"))
            lon = float(point.get("lon"))

            # Check geofence
            if not self._in_geofence(lat, lon):
                return

            # Inside geofence - send alert
            uid = root.get("uid", "")
            cot_type = root.get("type", "")

            await self._send_alert(
                f"Device {uid} entered geofence at ({lat}, {lon})"
            )

        except Exception as e:
            logger.error(f"GeofenceFilter failed: {e}")

    def _in_geofence(self, lat: float, lon: float) -> bool:
        config = self.get_decrypted_config()

        min_lat = float(config.get("min_lat"))
        max_lat = float(config.get("max_lat"))
        min_lon = float(config.get("min_lon"))
        max_lon = float(config.get("max_lon"))

        return (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon)

    async def _send_alert(self, message: str):
        import aiohttp
        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")

        async with aiohttp.ClientSession() as session:
            await session.post(webhook_url, json={"text": message})
```

---

## Migration Guide

### From Phase 2 to Phase 3

If you implemented custom output handling before Phase 3, here's how to migrate:

**Before (custom code in cot_service):**
```python
# Custom handling in cot_service_integration.py
async def _rx_worker(self, ...):
    # Parse CoT
    # Custom logic here
    # Send to Slack/IRC/etc
```

**After (output plugin):**
```python
# Create plugins/my_handler.py
class MyHandler(BaseOutputPlugin):
    async def handle_cot_message(self, cot_xml, tak_server_id):
        # Your logic here
        pass
```

**Benefits:**
- No core code changes needed
- Configuration via UI
- Automatic encryption of secrets
- Reusable across projects
- Testable in isolation

---

## Additional Resources

- [TrakBridge Output Spec](../Plans/output_spec.md) - Full architectural specification
- [BaseGPSPlugin Guide](../../README.md) - Input plugin development
- [CoT XML Reference](https://github.com/TAK-Product-Center/Server/wiki/CoT-XML) - Official CoT documentation
- [defusedxml Documentation](https://pypi.org/project/defusedxml/) - Secure XML parsing

---

## Support

For questions or issues with output plugins:

1. Check plugin logs in TrakBridge console
2. Verify configuration in UI
3. Test connection using "Test Connection" button
4. Review this guide for best practices
5. Create GitHub issue with logs and configuration

---

**Happy Plugin Development! 🚀**
