# TrakBridge Handler Plugin Development Guide

## Overview

This guide explains how to create output handler plugins for TrakBridge's bidirectional TAK communication system. Handler plugins receive CoT messages from TAK servers and can process them however you want - send to chat platforms, store in databases, trigger alerts, relay to other systems, etc.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Plugin Architecture](#plugin-architecture)
3. [Creating Your First Handler](#creating-your-first-handler)
4. [Configuration Management](#configuration-management)
5. [CoT Message Parsing](#cot-message-parsing)
6. [Filtering Strategies](#filtering-strategies)
7. [Error Handling](#error-handling)
8. [Performance Best Practices](#performance-best-practices)
9. [Testing Your Plugin](#testing-your-plugin)
10. [Custom UI Components](#custom-ui-components)
11. [Advanced Topics](#advanced-topics)

## Quick Start

### Minimal Handler Plugin

```python
from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
from typing import Any, Dict

class MyHandler(BaseOutputPlugin):
    """Minimal handler plugin example"""

    @property
    def plugin_name(self) -> str:
        return "my_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "My Handler",
            "description": "Handles CoT messages from TAK",
            "icon": "fa-bell",
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="endpoint_url",
                    label="Endpoint URL",
                    field_type="url",
                    required=True,
                    help_text="URL to send notifications to"
                )
            ]
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Handle received CoT message"""
        try:
            # Parse XML safely
            root = DefusedET.fromstring(cot_xml)

            # Extract basic fields
            cot_type = root.get('type')
            uid = root.get('uid')

            # Filter for chat messages only
            if not cot_type.startswith('b-t-f'):
                return  # Ignore non-chat messages

            # Get configuration
            config = self.get_decrypted_config()
            endpoint_url = config.get('endpoint_url')

            # Do something with the message
            print(f"Chat from {uid}: {cot_type}")

        except Exception as e:
            logger.error(f"MyHandler failed: {e}")
```

Save this as `plugins/my_handler.py` and it will automatically be discovered!

## Plugin Architecture

### Base Class: `BaseOutputPlugin`

All handler plugins inherit from `BaseOutputPlugin`, which provides:

- **Configuration Management**: Encryption, decryption, validation
- **Metadata System**: UI generation, field definitions
- **Helper Methods**: Reusable utilities for common tasks
- **Type Safety**: Clear interface contract

### Plugin Lifecycle

```
1. Discovery: TrakBridge scans plugins/ directory
2. Registration: PluginManager registers available plugins
3. Configuration: User configures via web UI
4. Instantiation: Plugin instance created per Stream
5. Message Routing: RX worker calls handle_cot_message()
6. Execution: Plugin processes message (parse, filter, act)
```

### Key Differences from GPS Plugins

| Feature | GPS Plugin (Input) | Handler Plugin (Output) |
|---------|-------------------|------------------------|
| Base Class | `BaseGPSPlugin` | `BaseOutputPlugin` |
| Method | `fetch_locations()` | `handle_cot_message()` |
| Direction | Fetches data → TAK | TAK → processes data |
| Timing | Periodic polling | Event-driven (real-time) |
| Category | "input" | "output" |

## Creating Your First Handler

### Step 1: Define Plugin Metadata

```python
from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from typing import Any, Dict

class SlackHandler(BaseOutputPlugin):
    @property
    def plugin_name(self) -> str:
        """Unique identifier for this plugin"""
        return "slack_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Metadata for UI generation and configuration"""
        return {
            "display_name": "Slack CoT Handler",
            "description": "Send CoT messages to Slack channel",
            "icon": "fa-slack",  # FontAwesome icon
            "category": "output",  # or "bidirectional" for hybrid
            "config_fields": [
                PluginConfigField(
                    name="webhook_url",
                    label="Slack Webhook URL",
                    field_type="url",
                    required=True,
                    sensitive=True,  # Will be encrypted in DB
                    help_text="Incoming webhook URL from Slack app"
                ),
                PluginConfigField(
                    name="message_types",
                    label="Message Types to Handle",
                    field_type="text",
                    placeholder="b-t-f,b-a-*",
                    help_text="Comma-separated CoT types (use * for wildcard)"
                ),
                PluginConfigField(
                    name="channel_name",
                    label="Channel Name",
                    field_type="text",
                    placeholder="#alerts",
                    help_text="Optional: Override default channel"
                ),
            ]
        }
```

### Step 2: Implement Message Handler

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
    """
    Handle received CoT message from TAK server.

    Args:
        cot_xml: Raw CoT XML bytes from TAK server
        tak_server_id: ID of TAK server that sent this message

    Responsibilities:
        - Parse XML (use defusedxml for security)
        - Filter messages (by type, UID, content, etc.)
        - Take action (send to Slack, log, store, etc.)
        - Handle errors gracefully
    """
    try:
        # Get decrypted configuration
        config = self.get_decrypted_config()

        # Parse XML safely
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        # Extract CoT fields
        cot_type = root.get('type')
        uid = root.get('uid')
        time = root.get('time')

        # Apply plugin's own filters
        if not self._should_handle(cot_type, uid):
            return  # Filtered out

        # Extract detail information
        detail = root.find('detail')
        callsign = self._extract_callsign(detail)
        message_text = self._extract_message(detail)

        # Take action based on message type
        if cot_type.startswith('b-t-f'):
            # Chat message
            await self._send_to_slack(
                f"💬 **{callsign}**: {message_text}",
                cot_type
            )
        elif cot_type.startswith('b-a'):
            # Emergency alert
            await self._send_to_slack(
                f"🚨 **EMERGENCY**: {callsign}",
                cot_type,
                urgent=True
            )
        else:
            # Other message types
            logger.debug(f"Ignoring CoT type: {cot_type}")

    except Exception as e:
        # NEVER raise - log and continue
        logger.error(f"SlackHandler failed to process CoT: {e}", exc_info=True)
```

### Step 3: Add Helper Methods

```python
def _should_handle(self, cot_type: str, uid: str) -> bool:
    """Plugin-specific filtering logic"""
    import re

    config = self.get_decrypted_config()

    # Filter by message type
    type_filter = config.get('message_types', '')
    if type_filter:
        types = [t.strip() for t in type_filter.split(',')]
        matches = False

        for t in types:
            if t.endswith('*'):
                # Wildcard match: "b-a-*" matches "b-a-o-tfc"
                if cot_type.startswith(t[:-1]):
                    matches = True
                    break
            elif cot_type == t:
                matches = True
                break

        if not matches:
            return False

    # Additional filtering could go here
    # - UID regex matching
    # - Geographic filtering
    # - Time-based filtering
    # - Content-based filtering

    return True

def _extract_callsign(self, detail) -> str:
    """Extract callsign from CoT detail element"""
    if detail is None:
        return "Unknown"

    contact = detail.find('contact')
    if contact is not None:
        return contact.get('callsign', 'Unknown')

    return "Unknown"

def _extract_message(self, detail) -> str:
    """Extract message text from CoT detail element"""
    if detail is None:
        return ""

    remarks = detail.find('remarks')
    if remarks is not None and remarks.text:
        return remarks.text

    return ""

async def _send_to_slack(self, text: str, cot_type: str, urgent: bool = False):
    """Send message to Slack webhook"""
    import aiohttp

    config = self.get_decrypted_config()
    webhook_url = config.get('webhook_url')

    if not webhook_url:
        logger.warning("No webhook URL configured")
        return

    payload = {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"CoT Type: `{cot_type}`"
                    }
                ]
            }
        ]
    }

    # Override channel if configured
    channel = config.get('channel_name')
    if channel:
        payload['channel'] = channel

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Slack webhook failed: {resp.status}")
    except asyncio.TimeoutError:
        logger.error("Slack webhook timed out")
    except Exception as e:
        logger.error(f"Failed to send to Slack: {e}")
```

## Configuration Management

### Field Types

```python
config_fields = [
    # Text input
    PluginConfigField(
        name="api_key",
        label="API Key",
        field_type="text",
        required=True,
        sensitive=True  # Encrypted in database
    ),

    # URL input (with validation)
    PluginConfigField(
        name="webhook_url",
        label="Webhook URL",
        field_type="url",
        required=True,
        placeholder="https://example.com/webhook"
    ),

    # Password input (masked in UI)
    PluginConfigField(
        name="password",
        label="Password",
        field_type="password",
        sensitive=True
    ),

    # Number input
    PluginConfigField(
        name="timeout_seconds",
        label="Timeout (seconds)",
        field_type="number",
        default_value="30"
    ),

    # Checkbox
    PluginConfigField(
        name="enabled",
        label="Enable Processing",
        field_type="checkbox",
        default_value="true"
    ),
]
```

### Accessing Configuration

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    # Get decrypted configuration
    config = self.get_decrypted_config()

    # Access fields
    api_key = config.get('api_key')  # Already decrypted
    webhook_url = config.get('webhook_url')
    timeout = int(config.get('timeout_seconds', 30))
    enabled = config.get('enabled', 'true').lower() == 'true'

    if not enabled:
        return  # Plugin disabled

    # Use configuration...
```

### Sensitive Field Encryption

```python
# Fields marked sensitive=True are automatically:
# 1. Encrypted when stored in database
# 2. Decrypted when loaded by get_decrypted_config()
# 3. Masked in UI (shown as *****)
# 4. Never logged or exposed in API responses

PluginConfigField(
    name="api_secret",
    label="API Secret",
    field_type="password",
    sensitive=True,  # ← Automatic encryption
    required=True
)
```

## CoT Message Parsing

### Basic CoT Structure

```xml
<event version="2.0" uid="ANDROID-123" type="a-f-G-E-V-C" time="2025-01-15T10:30:00Z"
       start="2025-01-15T10:30:00Z" stale="2025-01-15T10:40:00Z" how="m-g">
    <point lat="34.5" lon="-118.2" hae="100.0" ce="10.0" le="5.0"/>
    <detail>
        <contact callsign="Team Leader" endpoint="*:-1:stcp"/>
        <precisionlocation geopointsrc="GPS" altsrc="GPS"/>
        <status battery="75"/>
        <takv platform="ATAK" version="4.5.0"/>
        <track speed="2.5" course="180.0"/>
    </detail>
</event>
```

### Parsing Example

```python
from defusedxml import ElementTree as DefusedET

async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    # Parse XML
    root = DefusedET.fromstring(cot_xml)

    # Extract root attributes
    uid = root.get('uid')              # "ANDROID-123"
    cot_type = root.get('type')        # "a-f-G-E-V-C"
    time = root.get('time')            # "2025-01-15T10:30:00Z"
    start = root.get('start')
    stale = root.get('stale')
    how = root.get('how')              # "m-g" (manually entered)

    # Extract point (coordinates)
    point = root.find('point')
    if point is not None:
        lat = float(point.get('lat'))
        lon = float(point.get('lon'))
        hae = float(point.get('hae', 0))  # Height above ellipsoid
        ce = float(point.get('ce', 0))    # Circular error
        le = float(point.get('le', 0))    # Linear error

    # Extract detail elements
    detail = root.find('detail')
    if detail is not None:
        # Contact information
        contact = detail.find('contact')
        if contact is not None:
            callsign = contact.get('callsign')
            endpoint = contact.get('endpoint')

        # Status
        status = detail.find('status')
        if status is not None:
            battery = int(status.get('battery', 0))

        # Track information
        track = detail.find('track')
        if track is not None:
            speed = float(track.get('speed', 0))
            course = float(track.get('course', 0))

        # Chat messages
        remarks = detail.find('remarks')
        if remarks is not None:
            message_text = remarks.text or ""

        # Custom elements
        custom = detail.find('__custom')
        if custom is not None:
            # Your custom XML elements
            pass
```

### Common CoT Types

```python
# Position updates
'a-f-G-E-V-C'  # Ground track, friendly, vehicle, commercial
'a-f-G-E-S'    # Ground track, friendly, person
'a-h-G'        # Hostile ground track
'a-n-G'        # Neutral ground track
'a-u-G'        # Unknown ground track

# Chat messages
'b-t-f'        # Chat broadcast to all
'b-t-f-d'      # Direct chat message
'b-t-f-c'      # Chat to channel/group

# Emergency/911
'b-a-o-tfc'    # Troops in contact
'b-a-o-can'    # Cancel emergency
'b-a-g'        # General emergency
'b-a-o-pan'    # Pan-pan (urgency)

# Markers/Waypoints
'b-m-p-s-p-loc' # Marker with location
'b-m-p-w'      # Waypoint

# You can match these with startswith():
if cot_type.startswith('a-'):    # Position update
if cot_type.startswith('b-t-f'): # Chat
if cot_type.startswith('b-a'):   # Emergency
if cot_type.startswith('b-m'):   # Marker/Waypoint
```

## Filtering Strategies

### Type-Based Filtering

```python
def _should_handle(self, cot_type: str, uid: str) -> bool:
    """Filter by CoT type"""
    config = self.get_decrypted_config()

    # Get configured type filter
    type_filter = config.get('message_types', '')
    if not type_filter:
        return True  # No filter = accept all

    # Parse comma-separated types
    types = [t.strip() for t in type_filter.split(',')]

    for t in types:
        if t.endswith('*'):
            # Wildcard: "b-a-*" matches any emergency
            if cot_type.startswith(t[:-1]):
                return True
        elif cot_type == t:
            # Exact match
            return True

    return False
```

### UID-Based Filtering

```python
def _should_handle(self, cot_type: str, uid: str) -> bool:
    """Filter by UID pattern"""
    import re

    config = self.get_decrypted_config()
    uid_pattern = config.get('uid_filter', '')

    if not uid_pattern:
        return True  # No filter

    try:
        # Regex matching
        if re.match(uid_pattern, uid):
            return True
    except re.error as e:
        logger.error(f"Invalid UID regex: {uid_pattern}: {e}")
        return True  # Accept on regex error

    return False

# Example patterns:
# "^ANDROID-.*"     - Only Android devices
# "^TEAM1-.*"       - Only team 1 members
# ".*-LEADER$"      - Only leaders
# "^(ALPHA|BRAVO)-" - Alpha or Bravo teams
```

### Geographic Filtering

```python
def _should_handle_by_location(self, cot_xml: bytes) -> bool:
    """Filter by geographic area"""
    from defusedxml import ElementTree as DefusedET

    root = DefusedET.fromstring(cot_xml)
    point = root.find('point')

    if point is None:
        return True  # No location = accept

    lat = float(point.get('lat'))
    lon = float(point.get('lon'))

    config = self.get_decrypted_config()

    # Bounding box filter
    min_lat = float(config.get('min_lat', -90))
    max_lat = float(config.get('max_lat', 90))
    min_lon = float(config.get('min_lon', -180))
    max_lon = float(config.get('max_lon', 180))

    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        return False  # Outside bounding box

    # Circular geofence
    center_lat = float(config.get('center_lat', 0))
    center_lon = float(config.get('center_lon', 0))
    radius_km = float(config.get('radius_km', 0))

    if radius_km > 0:
        distance = self._calculate_distance(lat, lon, center_lat, center_lon)
        if distance > radius_km:
            return False  # Outside radius

    return True

def _calculate_distance(self, lat1, lon1, lat2, lon2) -> float:
    """Calculate distance in kilometers using Haversine formula"""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371  # Earth radius in km

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))

    return R * c
```

### Time-Based Filtering

```python
def _should_handle_by_time(self) -> bool:
    """Filter by time of day"""
    from datetime import datetime, time

    config = self.get_decrypted_config()

    # Only handle during business hours
    start_hour = int(config.get('start_hour', 0))
    end_hour = int(config.get('end_hour', 24))

    current_hour = datetime.now().hour

    if not (start_hour <= current_hour < end_hour):
        return False  # Outside operating hours

    return True
```

### Rate Limiting

```python
class MyHandler(BaseOutputPlugin):
    def __init__(self, config):
        super().__init__(config)
        self.last_message_time = {}
        self.message_count = {}

    def _should_handle_rate_limit(self, uid: str) -> bool:
        """Rate limit per UID"""
        import time

        config = self.get_decrypted_config()
        max_per_minute = int(config.get('max_messages_per_minute', 10))

        current_time = time.time()

        # Clean up old entries
        for key in list(self.last_message_time.keys()):
            if current_time - self.last_message_time[key] > 60:
                del self.last_message_time[key]
                del self.message_count[key]

        # Check rate limit
        if uid in self.message_count:
            if self.message_count[uid] >= max_per_minute:
                return False  # Rate limit exceeded
            self.message_count[uid] += 1
        else:
            self.last_message_time[uid] = current_time
            self.message_count[uid] = 1

        return True
```

## Error Handling

### Best Practices

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    """
    CRITICAL: NEVER raise exceptions from handle_cot_message()!

    The RX worker will timeout your plugin after 10 seconds and move on.
    Raising exceptions can crash the RX worker and stop message processing.

    Instead: Log errors and return gracefully.
    """
    try:
        # Your message handling logic
        config = self.get_decrypted_config()

        # Parse XML
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        # Process message
        await self._process_message(root, tak_server_id)

    except DefusedET.ParseError as e:
        # XML parsing failed - log and continue
        logger.error(f"Failed to parse CoT XML: {e}")
        return

    except asyncio.TimeoutError:
        # External API timed out - log and continue
        logger.warning(f"Timeout while processing CoT message")
        return

    except Exception as e:
        # Unexpected error - log with stack trace and continue
        logger.error(f"Handler failed to process CoT message: {e}", exc_info=True)
        return

    # NEVER let exceptions propagate!
```

### Timeout Handling

```python
async def _send_to_external_api(self, data: dict):
    """Send data with timeout protection"""
    import aiohttp

    config = self.get_decrypted_config()
    timeout_seconds = int(config.get('timeout_seconds', 5))

    try:
        async with asyncio.timeout(timeout_seconds):
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config['api_url'],
                    json=data,
                    headers={'Authorization': f"Bearer {config['api_key']}"}
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"API returned {resp.status}: {await resp.text()}")
                    else:
                        logger.debug("Message sent successfully")

    except asyncio.TimeoutError:
        logger.warning(f"API request timed out after {timeout_seconds}s")
    except aiohttp.ClientError as e:
        logger.error(f"HTTP client error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending to API: {e}")
```

### Retry Logic

```python
async def _send_with_retry(self, data: dict, max_retries: int = 3):
    """Send data with exponential backoff retry"""
    import aiohttp

    for attempt in range(max_retries):
        try:
            async with asyncio.timeout(10):
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data) as resp:
                        if resp.status == 200:
                            return True  # Success
                        elif resp.status >= 500:
                            # Server error - retry
                            logger.warning(f"Server error {resp.status}, retrying...")
                        else:
                            # Client error - don't retry
                            logger.error(f"Client error {resp.status}, giving up")
                            return False

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.warning(f"Attempt {attempt+1} failed: {e}")

        if attempt < max_retries - 1:
            # Exponential backoff: 1s, 2s, 4s
            await asyncio.sleep(2 ** attempt)

    logger.error(f"Failed after {max_retries} attempts")
    return False
```

## Performance Best Practices

### 1. Async I/O (Do This!)

```python
# ✅ GOOD: Non-blocking async I/O
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=data) as resp:
            await resp.text()

# ❌ BAD: Blocking synchronous I/O
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    import requests

    # This blocks the entire event loop!
    requests.post(url, json=data)
```

### 2. Lazy Parsing

```python
# ✅ GOOD: Parse only if needed
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    # Quick type check without full parsing
    if b'type="a-f-' not in cot_xml:
        return  # Not a friendly position update, skip

    # Only parse if we need details
    from defusedxml import ElementTree as DefusedET
    root = DefusedET.fromstring(cot_xml)
    # ... full processing

# ❌ BAD: Always parse everything
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    from defusedxml import ElementTree as DefusedET
    root = DefusedET.fromstring(cot_xml)  # Expensive!

    cot_type = root.get('type')
    if not cot_type.startswith('a-f-'):
        return  # Wasted parsing
```

### 3. Batch Processing

```python
class MyHandler(BaseOutputPlugin):
    def __init__(self, config):
        super().__init__(config)
        self.message_queue = []
        self.batch_task = None

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Add to batch queue instead of sending immediately"""
        # Parse message
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        # Add to queue
        self.message_queue.append({
            'type': root.get('type'),
            'uid': root.get('uid'),
            'time': root.get('time')
        })

        # Start batch processor if not running
        if self.batch_task is None or self.batch_task.done():
            self.batch_task = asyncio.create_task(self._process_batch())

    async def _process_batch(self):
        """Process messages in batches every 5 seconds"""
        await asyncio.sleep(5)

        if not self.message_queue:
            return

        # Send batch
        batch = self.message_queue[:]
        self.message_queue.clear()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={'messages': batch}) as resp:
                    logger.info(f"Sent batch of {len(batch)} messages")
        except Exception as e:
            logger.error(f"Failed to send batch: {e}")
```

### 4. Connection Pooling

```python
class MyHandler(BaseOutputPlugin):
    def __init__(self, config):
        super().__init__(config)
        self.session = None  # Reusable session

    async def _get_session(self):
        """Get or create HTTP session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Reuse connection pool"""
        session = await self._get_session()

        try:
            async with session.post(url, json=data) as resp:
                await resp.text()
        except Exception as e:
            logger.error(f"Failed: {e}")

    def __del__(self):
        """Cleanup session on deletion"""
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())
```

### 5. Caching

```python
class MyHandler(BaseOutputPlugin):
    def __init__(self, config):
        super().__init__(config)
        self.uid_cache = {}  # Cache UID lookups
        self.cache_ttl = 300  # 5 minutes

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        uid = root.get('uid')

        # Check cache first
        if uid in self.uid_cache:
            cache_entry = self.uid_cache[uid]
            if time.time() - cache_entry['timestamp'] < self.cache_ttl:
                user_info = cache_entry['data']
            else:
                # Cache expired
                del self.uid_cache[uid]
                user_info = await self._lookup_user(uid)
                self.uid_cache[uid] = {
                    'data': user_info,
                    'timestamp': time.time()
                }
        else:
            # Not in cache
            user_info = await self._lookup_user(uid)
            self.uid_cache[uid] = {
                'data': user_info,
                'timestamp': time.time()
            }

        # Use user_info...
```

## Testing Your Plugin

### Unit Tests

```python
# tests/test_my_handler.py
import pytest
from plugins.my_handler import MyHandler

@pytest.fixture
def handler():
    """Create handler instance with test config"""
    config = {
        'webhook_url': 'https://test.example.com/webhook',
        'message_types': 'b-t-f,b-a-*',
    }
    return MyHandler(config)

@pytest.mark.asyncio
async def test_chat_message_handling(handler):
    """Test chat message handling"""
    cot_xml = b'''
    <event version="2.0" uid="TEST-1" type="b-t-f"
           time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
           stale="2025-01-15T10:10:00Z" how="h-e">
        <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
        <detail>
            <contact callsign="Tester"/>
            <remarks>Test message</remarks>
        </detail>
    </event>
    '''

    # Should not raise
    await handler.handle_cot_message(cot_xml, tak_server_id=1)

@pytest.mark.asyncio
async def test_filtering(handler):
    """Test message type filtering"""
    # Position update (should be filtered)
    cot_xml = b'''
    <event version="2.0" uid="TEST-1" type="a-f-G-E-V-C"
           time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
           stale="2025-01-15T10:10:00Z" how="m-g">
        <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
        <detail>
            <contact callsign="Tester"/>
        </detail>
    </event>
    '''

    # Should not raise, should be filtered out
    await handler.handle_cot_message(cot_xml, tak_server_id=1)

@pytest.mark.asyncio
async def test_malformed_xml(handler):
    """Test handling of malformed XML"""
    cot_xml = b'<event>incomplete'

    # Should not raise, should log error
    await handler.handle_cot_message(cot_xml, tak_server_id=1)
```

### Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_slack(live_slack_webhook):
    """Test actual Slack integration (requires real webhook)"""
    handler = MyHandler({
        'webhook_url': live_slack_webhook,
        'message_types': 'b-t-f'
    })

    cot_xml = b'''
    <event version="2.0" uid="TEST-1" type="b-t-f"
           time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
           stale="2025-01-15T10:10:00Z" how="h-e">
        <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
        <detail>
            <contact callsign="Integration Test"/>
            <remarks>This is a test from integration tests</remarks>
        </detail>
    </event>
    '''

    await handler.handle_cot_message(cot_xml, tak_server_id=1)

    # Verify message appeared in Slack (manual verification or Slack API check)
```

### Load Testing

```python
@pytest.mark.performance
@pytest.mark.asyncio
async def test_throughput(handler):
    """Test handler can process 100 messages/second"""
    import time

    cot_xml = b'''<event version="2.0" uid="TEST-1" type="b-t-f"
           time="2025-01-15T10:00:00Z" start="2025-01-15T10:00:00Z"
           stale="2025-01-15T10:10:00Z" how="h-e">
        <point lat="34.5" lon="-118.2" hae="0" ce="10" le="5"/>
        <detail><contact callsign="Test"/><remarks>Test</remarks></detail>
    </event>'''

    start_time = time.time()
    tasks = []

    # Send 1000 messages
    for i in range(1000):
        task = asyncio.create_task(
            handler.handle_cot_message(cot_xml, tak_server_id=1)
        )
        tasks.append(task)

    await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    throughput = 1000 / elapsed

    print(f"Throughput: {throughput:.1f} messages/second")
    assert throughput >= 100, f"Throughput too low: {throughput:.1f} msg/s"
```

## Custom UI Components

Plugins can declare custom UI components via the `custom_components` metadata key. These render as interactive cards in the Stream Configuration form, below the standard config fields.

### Declaring Custom Components

Custom components are defined using `PluginCustomComponent` from `plugins.base_plugin`. Each component specifies a type (which maps to a shared JS renderer), a form field name, a display title, and component-specific configuration.

```python
from plugins.base_plugin import BaseOutputPlugin, PluginConfigField, PluginCustomComponent

class MyHandler(BaseOutputPlugin):
    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "My Handler",
            "description": "Handler with custom UI",
            "icon": "fa-bell",
            "category": "output",
            "config_fields": [...],
            "custom_components": [
                PluginCustomComponent(
                    type="message_rules",
                    field_name="rules",
                    title="Message Routing Rules",
                    icon="fa-filter",
                    help_text="Define rules for filtering and routing messages",
                    config={
                        "rule_fields": [
                            {
                                "name": "uid_filter",
                                "label": "UID Filter (regex)",
                                "type": "text",
                                "placeholder": ".*",
                                "required": False,
                                "help": "Regex to match CoT UIDs",
                            },
                            # ... more fields per rule
                        ]
                    },
                ),
            ],
        }
```

### PluginCustomComponent Fields

| Field | Type | Description |
| ----- | ---- | ----------- |
| `type` | `str` | Component type: `"message_rules"`, `"geofence"`, or `"grouped_multi_select"` |
| `field_name` | `str` | Form field name used by the backend to read submitted data |
| `title` | `str` | Display title shown on the component card |
| `icon` | `str` | FontAwesome icon class (e.g., `"fa-filter"`) |
| `help_text` | `str` | Optional help text displayed below the title |
| `config` | `dict` | Component-specific configuration (see below) |

### Available Component Types

#### Message Rules (`"message_rules"`)

A dynamic rule builder UI. Users add/remove/edit structured rules, each with an enabled toggle and a set of fields you define. Used by Slack, IRC, and Discord handlers for message filtering and routing.

**Config keys:**

- `rule_fields` — list of field descriptors, each with `name`, `label`, `type` (`"text"` or `"textarea"`), `placeholder`, `required`, `help`, and `default`

The submitted form value is a JSON array of rule objects. Each rule has an `id`, `enabled` flag, and the fields you defined.

#### Geofence (`"geofence"`)

A Leaflet map with shift+drag rectangle drawing and four coordinate inputs (north/south/east/west). Users can optionally enable geographic bounding-box filtering. The geofence values are submitted as individual form fields (`plugin_<field_name>_enabled`, `plugin_<field_name>_north`, etc.), not as a single JSON blob.

**Config keys:**

- `enable_checkbox_label` — label for the enable/disable checkbox
- `default_center` — `[lat, lng]` array for initial map view
- `default_zoom` — integer zoom level

#### Grouped Multi-Select (`"grouped_multi_select"`)

A searchable, grouped checkbox grid. Items are organized into collapsible groups with per-group and global select-all/clear controls, plus a text search filter. The submitted form value is a JSON array of the selected integer values.

**Config keys:**

- `items` — dict mapping display name to integer value, e.g. `{"Ukraine": 0, "Syria": 3}`
- `groups` — dict mapping group name to list of item names, e.g. `{"Europe": ["Ukraine", ...], "Middle East": ["Syria", ...]}`

### Shared JS Architecture

Custom component rendering is handled by four shared JavaScript files loaded by both `create_stream.html` and `edit_stream.html`:

| File | Purpose |
| ---- | ------- |
| `static/js/component_common.js` | Registry and dispatch — defines `componentRenderers`, `componentValidators`, `renderCustomComponents()`, and `validateCustomComponents()` |
| `static/js/component_message_rules.js` | Renders the message rules builder, manages rule state, serializes to JSON |
| `static/js/component_geofence.js` | Renders the Leaflet map, handles shift+drag drawing, validates coordinates |
| `static/js/component_grouped_multi_select.js` | Renders the grouped checkbox grid, handles search filtering and serialization |

Each component file self-registers its renderer and validator into the global `componentRenderers` and `componentValidators` dictionaries when loaded. The templates call `renderCustomComponents(pluginType, components)` when a plugin is selected, passing the `custom_components` array from plugin metadata. Templates contain no component-specific logic.

## Advanced Topics

### Connection Lifecycle Management

For plugins that maintain persistent connections (IRC, MQTT, WebSocket, etc.), implement proper lifecycle hooks:

```python
class PersistentConnectionHandler(BaseOutputPlugin):
    """Handler with persistent connection management"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected: bool = False
        self._connection_lock = asyncio.Lock()
        self._reader_task: Optional[asyncio.Task] = None

    async def start(self):
        """
        Initialize connection when stream starts.

        Called by framework when stream is enabled.
        Use this for connection setup, authentication, joining channels, etc.
        """
        logger.info(f"{self.plugin_name} starting - establishing connection...")
        success = await self._ensure_connected()
        if success:
            logger.info(f"{self.plugin_name} started successfully")
        else:
            logger.error(f"{self.plugin_name} failed to start - connection failed")

    async def _ensure_connected(self) -> bool:
        """Ensure connection is established (with reconnection logic)"""
        async with self._connection_lock:
            if self._connected and self._writer and not self._writer.is_closing():
                return True  # Already connected

            try:
                config = self.get_decrypted_config()
                server = config.get("server")
                port = int(config.get("port", 6667))

                # Connect
                self._reader, self._writer = await asyncio.open_connection(server, port)
                logger.info(f"Connected to {server}:{port}")

                # Perform handshake/authentication
                await self._perform_handshake()

                # Start background task for message handling
                if self._reader_task is None or self._reader_task.done():
                    self._reader_task = asyncio.create_task(self._handle_server_messages())

                self._connected = True
                return True

            except Exception as e:
                logger.error(f"Failed to connect: {e}")
                self._connected = False
                return False

    async def _handle_server_messages(self):
        """Background task to handle server messages (PING/PONG, etc.)"""
        try:
            while self._reader:
                line = await asyncio.wait_for(self._reader.readline(), timeout=300)
                if not line:
                    logger.warning("Connection closed by server")
                    self._connected = False
                    break

                message = line.decode('utf-8', errors='ignore').strip()

                # Handle server messages (PING, errors, etc.)
                if message.startswith('PING'):
                    # Respond to keepalive
                    self._writer.write(b"PONG\r\n")
                    await self._writer.drain()

        except Exception as e:
            logger.error(f"Server message handler crashed: {e}")
            self._connected = False

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Handle CoT with automatic reconnection"""
        # Ensure connected before processing
        if not await self._ensure_connected():
            logger.error("Cannot process - connection failed")
            return

        # Process message...

    async def cleanup(self):
        """
        Cleanup resources when stream stops.

        Called by framework when stream is disabled or deleted.
        Close connections, cancel tasks, clean up resources.
        """
        # Cancel background tasks
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        # Close connection gracefully
        if self._writer and not self._writer.is_closing():
            try:
                self._writer.write(b"QUIT\r\n")
                await self._writer.drain()
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

        self._connected = False
```

**Key Lifecycle Methods:**

- `async def start()` - Called when stream starts (optional)
- `async def handle_cot_message()` - Called for each CoT message (required)
- `async def cleanup()` - Called when stream stops (optional)
- `async def test_connection()` - Called by "Test Connection" button (optional)

### Help Sections in Plugin Metadata

Provide comprehensive help directly in your plugin metadata for better UX:

```python
@property
def plugin_metadata(self) -> Dict[str, Any]:
    return {
        "display_name": "My Handler",
        "description": "Handle CoT messages and do something useful",
        "icon": "fa-bell",
        "category": "output",
        "help_sections": [
            {
                "title": "Template Variables",
                "content": [
                    "Basic: {type}, {uid}, {time}, {stale}, {callsign}, {remarks}",
                    "Location: {lat}, {lon}, {hae}, {mgrs}",
                    "Group: {group_name}, {group_role}",
                    "Device: {device}, {platform}, {os}, {version}, {battery}",
                    "Track: {speed}, {course}, {xmpp_username}",
                ],
            },
            {
                "title": "Common CoT Types & Examples",
                "content": [
                    "Chat (b-t-f): \"[CHAT] {callsign}: {remarks}\"",
                    "Emergency (b-a-o-tl): \"[EMERGENCY] {callsign} at {mgrs}\"",
                    "Friendly Position (a-f-G-E-V): \"[{group_name}] {callsign} - Battery: {battery}%\"",
                ],
            },
            {
                "title": "Important Notes",
                "content": [
                    "Messages are deduplicated within 5 seconds",
                    "Use wildcards (*) in patterns for broader matching",
                    "At least one message rule is required",
                ],
            },
        ],
        "config_fields": [
            # ... your config fields
        ]
    }
```

Help sections appear in the UI sidebar when users configure your plugin.

### Hiding the COT Type Selector

Some plugins hardcode their own CoT type for every event (e.g., a spot map marker type) and the global "COT Type" selector in the Stream Configuration card would be misleading. You can hide it by setting `hide_cot_type` in your plugin metadata:

```python
@property
def plugin_metadata(self) -> Dict[str, Any]:
    return {
        "display_name": "My OSINT Handler",
        "description": "Fetches events with hardcoded CoT types",
        "icon": "fa-globe",
        "category": "osint",
        "hide_cot_type": True,  # Hides the COT Type selector in Stream Configuration
        "config_fields": [
            # ... your config fields
        ]
    }
```

When `hide_cot_type` is `True`, the COT Type `<select>` is hidden in both the Create Stream and Edit Stream forms. Poll Interval and COT Stale Time remain visible. The selector reappears when the user switches to a plugin that does not set this flag.

### Message Deduplication

Prevent duplicate processing of messages that TAK servers may rebroadcast:

```python
class DeduplicatingHandler(BaseOutputPlugin):
    """Handler with built-in deduplication"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Track recently seen messages
        self._seen_messages: Dict[str, float] = {}
        self._dedup_ttl_seconds: float = 5.0

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Handle CoT with deduplication"""
        from defusedxml import ElementTree as DefusedET
        import time

        root = DefusedET.fromstring(cot_xml)

        # Create dedup key from UID + type (not timestamp!)
        uid = root.get('uid')
        cot_type = root.get('type')
        dedup_key = f"{uid}:{cot_type}"

        now = time.time()

        # Clean up old entries
        self._seen_messages = {
            k: v for k, v in self._seen_messages.items()
            if now - v < self._dedup_ttl_seconds
        }

        # Check if we've seen this recently
        if dedup_key in self._seen_messages:
            time_since_last = now - self._seen_messages[dedup_key]
            logger.debug(f"Duplicate ignored: {dedup_key} (seen {time_since_last:.2f}s ago)")
            return

        # Mark as seen
        self._seen_messages[dedup_key] = now

        # Process message...
        logger.debug(f"New message: {dedup_key}")
```

**Why deduplication matters:**
- TAK servers may rebroadcast messages
- Position updates come frequently
- Prevents spam to external services
- Reduces API costs

**Best practices:**
- Use UID + type as key (not timestamp)
- TTL of 5-10 seconds is usually sufficient
- Clean up old entries to prevent memory leaks
- Log when duplicates are filtered

### MGRS Coordinate Conversion

For military/tactical applications, MGRS (Military Grid Reference System) is often preferred:

```python
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    """Handle CoT with MGRS conversion"""
    from defusedxml import ElementTree as DefusedET
    import mgrs

    root = DefusedET.fromstring(cot_xml)

    # Extract coordinates
    point = root.find('point')
    if point is not None:
        lat = float(point.get('lat'))
        lon = float(point.get('lon'))

        # Convert to MGRS
        try:
            m = mgrs.MGRS()
            mgrs_coord = m.toMGRS(lat, lon)
            logger.info(f"Position: {lat},{lon} = {mgrs_coord}")

            # Use MGRS in your message
            message = f"Alert at {mgrs_coord}"

        except Exception as e:
            logger.warning(f"MGRS conversion failed: {e}")
            # Fallback to lat/lon
            message = f"Alert at {lat},{lon}"
```

Install mgrs library: `pip install mgrs`

### Template-Based Message Formatting

Allow users to customize message formats with template variables:

```python
def _extract_template_variables(self, root) -> Dict[str, str]:
    """Extract all template variables from CoT XML"""
    variables = {
        # Basic CoT fields
        "type": root.get("type", ""),
        "uid": root.get("uid", ""),
        "time": root.get("time", ""),
        "stale": root.get("stale", ""),

        # Initialize all with defaults
        "callsign": "Unknown",
        "lat": "",
        "lon": "",
        "hae": "",
        "mgrs": "",
        "remarks": "",
        "group_name": "",
        "group_role": "",
        "battery": "",
        "device": "",
        "platform": "",
        "os": "",
        "version": "",
        "speed": "",
        "course": "",
    }

    # Extract point data
    point = root.find("point")
    if point is not None:
        variables["lat"] = point.get("lat", "")
        variables["lon"] = point.get("lon", "")
        variables["hae"] = point.get("hae", "")

    # Extract detail elements
    detail = root.find("detail")
    if detail is not None:
        # Contact info
        contact = detail.find("contact")
        if contact is not None:
            variables["callsign"] = contact.get("callsign", "Unknown")

        # Remarks (chat messages)
        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            variables["remarks"] = remarks.text

        # Group data
        group = detail.find("__group")
        if group is not None:
            variables["group_name"] = group.get("name", "")
            variables["group_role"] = group.get("role", "")

        # Battery status
        status = detail.find("status")
        if status is not None:
            variables["battery"] = status.get("battery", "")

        # Device info
        takv = detail.find("takv")
        if takv is not None:
            variables["device"] = takv.get("device", "")
            variables["platform"] = takv.get("platform", "")
            variables["os"] = takv.get("os", "")
            variables["version"] = takv.get("version", "")

        # Track data
        track = detail.find("track")
        if track is not None:
            variables["speed"] = track.get("speed", "")
            variables["course"] = track.get("course", "")

    return variables

def _format_message(self, template: str, variables: Dict[str, str]) -> str:
    """Format message using template and variables"""
    try:
        return template.format(**variables)
    except KeyError as e:
        logger.warning(f"Template variable missing: {e}")
        return f"{template} [ERROR: missing variable {e}]"
    except Exception as e:
        logger.error(f"Template formatting error: {e}")
        return f"{template} [ERROR: {e}]"

# Usage:
async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
    root = DefusedET.fromstring(cot_xml)

    # Get user-configured template from config
    config = self.get_decrypted_config()
    template = config.get("message_template", "[{type}] {callsign}")

    # Extract all variables
    variables = self._extract_template_variables(root)

    # Format message
    message = self._format_message(template, variables)

    # Send formatted message
    await self._send_message(message)
```

**Template examples users can configure:**
- `"[CHAT] {callsign}: {remarks}"` - Chat messages
- `"[{group_name}] {callsign} ({group_role}) - Battery: {battery}%"` - Team updates
- `"[ALERT] {callsign} at {mgrs}"` - Emergency alerts
- `"{callsign} moving at {speed} m/s heading {course}°"` - Movement tracking

### Hybrid Plugins (Both Input and Output)

```python
from plugins.base_plugin import BaseGPSPlugin, BaseOutputPlugin

class SmartRelayPlugin(BaseGPSPlugin, BaseOutputPlugin):
    """
    Hybrid plugin that BOTH sends AND receives!

    Use case:
    - Fetches data from external API and sends to TAK (input)
    - Receives alerts from TAK and triggers external actions (output)
    """

    @property
    def plugin_name(self) -> str:
        return "smart_relay"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Smart Relay",
            "description": "Bidirectional relay between external system and TAK",
            "icon": "fa-exchange",
            "category": "bidirectional",  # ← Marks as hybrid
            "config_fields": [
                # Input config
                PluginConfigField(
                    name="api_url",
                    label="External API URL",
                    field_type="url",
                    required=True
                ),
                # Output config
                PluginConfigField(
                    name="webhook_url",
                    label="Alert Webhook URL",
                    field_type="url",
                    sensitive=True
                ),
            ]
        }

    # INPUT: Implements BaseGPSPlugin interface
    async def fetch_locations(self, session) -> List[Dict]:
        """Fetch GPS data from external API"""
        config = self.get_decrypted_config()

        async with session.get(config['api_url']) as resp:
            data = await resp.json()

            # Transform to TrakBridge location format
            locations = []
            for item in data['devices']:
                locations.append({
                    'device_id': item['id'],
                    'latitude': item['lat'],
                    'longitude': item['lon'],
                    'altitude': item.get('alt', 0),
                    'speed': item.get('speed', 0),
                    'course': item.get('heading', 0),
                    'timestamp': item['timestamp'],
                    'callsign': item['name']
                })

            return locations

    # OUTPUT: Implements BaseOutputPlugin interface
    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Receive emergency alerts and trigger external webhook"""
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        # Only handle emergencies
        if not root.get('type').startswith('b-a'):
            return

        # Extract alert details
        uid = root.get('uid')
        point = root.find('point')
        lat = float(point.get('lat')) if point is not None else 0
        lon = float(point.get('lon')) if point is not None else 0

        # Send alert to external system
        config = self.get_decrypted_config()
        webhook_url = config.get('webhook_url')

        if webhook_url:
            alert_data = {
                'type': 'emergency',
                'uid': uid,
                'location': {'lat': lat, 'lon': lon},
                'time': root.get('time')
            }

            async with aiohttp.ClientSession() as session:
                await session.post(webhook_url, json=alert_data)
```

### Two-Way Communication

```python
class TwoWayHandler(BaseOutputPlugin):
    """Handler that can also SEND CoT back to TAK"""

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Receive command from Slack, send waypoint to TAK"""
        from defusedxml import ElementTree as DefusedET
        root = DefusedET.fromstring(cot_xml)

        # Parse chat message
        detail = root.find('detail')
        if detail is None:
            return

        remarks = detail.find('remarks')
        if remarks is None or not remarks.text:
            return

        message = remarks.text

        # Check for command: "!waypoint 34.5 -118.2 Target Alpha"
        if message.startswith('!waypoint'):
            parts = message.split()
            if len(parts) >= 4:
                try:
                    lat = float(parts[1])
                    lon = float(parts[2])
                    name = ' '.join(parts[3:])

                    # Generate waypoint CoT
                    waypoint_cot = self._create_waypoint_cot(lat, lon, name)

                    # Send back to TAK via existing TX path
                    from services.cot_service_integration import get_cot_service
                    cot_service = get_cot_service()
                    await cot_service.enqueue_event(waypoint_cot, tak_server_id)

                    logger.info(f"Created waypoint {name} at {lat},{lon}")

                except (ValueError, IndexError) as e:
                    logger.error(f"Invalid waypoint command: {e}")

    def _create_waypoint_cot(self, lat: float, lon: float, name: str) -> str:
        """Generate CoT XML for a waypoint marker"""
        import uuid
        from datetime import datetime, timedelta

        uid = f"WAYPOINT-{uuid.uuid4()}"
        now = datetime.utcnow()
        stale = now + timedelta(hours=24)

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{uid}" type="b-m-p-s-p-loc"
       time="{now.isoformat()}Z" start="{now.isoformat()}Z"
       stale="{stale.isoformat()}Z" how="h-e">
    <point lat="{lat}" lon="{lon}" hae="0" ce="10" le="10"/>
    <detail>
        <contact callsign="{name}"/>
        <link uid="{uid}" type="b-m-p-s-p-loc" relation="p-p"/>
        <usericon iconsetpath="COT_MAPPING_SPOTMAP/b-m-p-s-p-loc/pin_red.png"/>
        <color value="-65536"/>
    </detail>
</event>'''
```

### Database Storage Plugin

```python
class DatabaseArchiver(BaseOutputPlugin):
    """Store all received CoT in database for audit trail and replay"""

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Store raw CoT XML in database"""
        from models.cot_message import CotMessage
        from models.database import db
        from datetime import datetime
        from defusedxml import ElementTree as DefusedET

        try:
            # Parse for indexing
            root = DefusedET.fromstring(cot_xml)

            # Create database record
            msg = CotMessage(
                tak_server_id=tak_server_id,
                cot_type=root.get('type'),
                uid=root.get('uid'),
                cot_xml=cot_xml.decode('utf-8'),
                received_at=datetime.utcnow()
            )

            # Extract point for spatial queries
            point = root.find('point')
            if point is not None:
                msg.latitude = float(point.get('lat'))
                msg.longitude = float(point.get('lon'))
                msg.altitude = float(point.get('hae', 0))

            db.session.add(msg)
            db.session.commit()

            logger.debug(f"Archived CoT {msg.uid}")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to archive CoT: {e}")
```

### Metrics and Health Monitoring

```python
class MonitoredHandler(BaseOutputPlugin):
    """Handler with built-in performance monitoring"""

    def __init__(self, config):
        super().__init__(config)
        self.metrics = {
            'messages_received': 0,
            'messages_processed': 0,
            'messages_filtered': 0,
            'errors': 0,
            'total_latency_ms': 0.0
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int):
        """Handle message with performance tracking"""
        import time

        start_time = time.time()
        self.metrics['messages_received'] += 1

        try:
            # Parse
            from defusedxml import ElementTree as DefusedET
            root = DefusedET.fromstring(cot_xml)

            # Filter
            if not self._should_handle(root.get('type'), root.get('uid')):
                self.metrics['messages_filtered'] += 1
                return

            # Process
            await self._process_message(root, tak_server_id)

            self.metrics['messages_processed'] += 1

        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Handler error: {e}")

        finally:
            # Record latency
            latency_ms = (time.time() - start_time) * 1000
            self.metrics['total_latency_ms'] += latency_ms

            # Log every 100 messages
            if self.metrics['messages_received'] % 100 == 0:
                avg_latency = self.metrics['total_latency_ms'] / self.metrics['messages_received']
                logger.info(
                    f"Handler metrics: "
                    f"received={self.metrics['messages_received']}, "
                    f"processed={self.metrics['messages_processed']}, "
                    f"filtered={self.metrics['messages_filtered']}, "
                    f"errors={self.metrics['errors']}, "
                    f"avg_latency={avg_latency:.2f}ms"
                )

    def get_health_status(self) -> dict:
        """Return health status for monitoring systems"""
        total = self.metrics['messages_received']
        if total == 0:
            return {'status': 'healthy', 'reason': 'no messages yet'}

        error_rate = self.metrics['errors'] / total
        avg_latency = self.metrics['total_latency_ms'] / total

        if error_rate > 0.05:  # > 5% errors
            return {
                'status': 'unhealthy',
                'reason': f'high error rate: {error_rate*100:.1f}%'
            }

        if avg_latency > 1000:  # > 1 second
            return {
                'status': 'degraded',
                'reason': f'high latency: {avg_latency:.0f}ms'
            }

        return {'status': 'healthy'}
```

## Built-in Output Plugins (v1.3.0+)

TrakBridge ships three production-ready output plugins. Study these as the reference architecture before writing a custom handler:

### OutboundHTTP (`plugins/outbound_http.py`)

POSTs or PUTs CoT events to an HTTP/HTTPS endpoint. Supports JSON, raw XML, and custom templates. Key patterns to borrow:

- Scheme allow-listing — rejects non-http/https URLs before any network I/O
- CRLF injection prevention in custom headers via `parse_custom_headers()`
- Composes against `services/output_plugin_helpers.py` for dedup, rate limiting, and payload building

### OutboundMQTT (`plugins/outbound_mqtt.py`)

Publishes CoT to an MQTT broker with persistent paho connection, TLS via `cert_utils.build_ssl_context()`, bounded queue with oldest-drop semantics, and bad-auth detection. Good reference for plugins that maintain a long-lived connection.

### OutboundWebSocket (`plugins/outbound_websocket.py`)

Streams CoT to a WebSocket server with exponential backoff reconnect, background reader for server-close detection, and URL credential redaction in logs. Good reference for plugins that use `asyncio` background tasks.

### Shared Helpers (`services/output_plugin_helpers.py`)

All three built-in plugins compose against this module. Prefer using it over rolling your own:

```python
from services.output_plugin_helpers import (
    extract_cot_variables,   # parse CoT XML into a variables dict
    Deduplicator,            # TTL-based UID deduplication
    RateLimiter,             # per-minute token bucket
    is_within_geofence,      # bounding-box check
    build_payload,           # JSON / XML / template payload builder
)
```

See [Output Plugins Guide](OUTPUT_PLUGINS_GUIDE.md) for full API details.

---

## Summary

**Key Takeaways:**

1. **Inherit from `BaseOutputPlugin`** — use the output base class, not GPS
2. **Implement `handle_cot_message()`** — core method called for every CoT message
3. **Use `defusedxml` for parsing** — never use standard `xml.etree` (XXE risk)
4. **Filter in the plugin** — core doesn't filter; that's the plugin's job
5. **Never re-raise from `handle_cot_message`** — log and return; one failing plugin must not stop others
6. **Use async I/O** — non-blocking operations only; `await asyncio.sleep()` not `time.sleep()`
7. **Set timeouts on all external calls** — always pass `aiohttp.ClientTimeout`
8. **Encryption is automatic** — mark fields `sensitive=True` for auto-encryption
9. **Compose against `output_plugin_helpers`** — don't re-implement dedup, rate limiting, or payload building
10. **Test thoroughly** — unit, integration, and E2E tests; see built-in plugins for examples

**Resources:**

- Built-in plugins: `plugins/outbound_http.py`, `plugins/outbound_mqtt.py`, `plugins/outbound_websocket.py`
- Shared helpers: `services/output_plugin_helpers.py`
- Base class: `plugins/base_plugin.py` (`BaseOutputPlugin`)
- RX worker: `services/cot_service_integration.py` (`_rx_worker`)
- Reference implementation: `docs/example_external_plugins/sample_custom_handler.py`
- CoT spec: https://github.com/TAK-Product-Center/Server/tree/main/src/docs/COT
- defusedxml: https://github.com/tiran/defusedxml

**Need Help?**

- Check logs: `tail -f logs/trakbridge.log`
- Enable debug mode: Set `DEBUG=True` in config
- Test plugin connection: Web UI > Streams > Test Connection
- View RX metrics: Check monitoring dashboard (if enabled)

Happy coding, Poults! 🚀
