# ABOUTME: Webhook Forwarder output plugin that monitors CoT traffic from TAK servers,
# ABOUTME: filters by rules, converts to JSON/XML/template, and delivers via HTTP, WebSocket, or MQTT.

import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp
import certifi
import mgrs
import ssl
from defusedxml import ElementTree as DefusedET

from plugins.base_plugin import (
    BaseOutputPlugin,
    PluginConfigField,
    PluginCustomComponent,
)

# Lazy import to avoid circular dependency
_logger_instance = None


def get_logger():
    """Get module logger, initializing lazily to avoid circular imports"""
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


class WebhookHandler(BaseOutputPlugin):
    """
    Forward CoT messages from TAK servers to external systems.

    Supports three delivery modes:
    - HTTP: Per-message POST/PUT to a webhook URL (stateless)
    - WebSocket: Persistent connection with bounded async buffer
    - MQTT: Publish to MQTT broker with topic substitution
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Deduplication state
        self._seen_messages: Dict[str, float] = {}

        # Health stats
        self._events_sent: int = 0
        self._events_dropped: int = 0

        # WebSocket state
        self._ws_connection = None
        self._ws_writer_task: Optional[asyncio.Task] = None
        self._ws_queue: Optional[asyncio.Queue] = None
        self._ws_connected: bool = False

        # MQTT state
        self._mqtt_client = None
        self._mqtt_connected: bool = False

        # Rate throttle state
        self._last_event_time: float = 0.0

    @property
    def plugin_name(self) -> str:
        return "webhook_forwarder"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Webhook Forwarder",
            "description": (
                "Forward CoT messages to external systems via HTTP, "
                "WebSocket, or MQTT"
            ),
            "icon": "fa-arrow-right",
            "category": "output",
            "help_sections": [
                {
                    "title": "Delivery Modes",
                    "content": [
                        "HTTP: Per-message POST/PUT — good for webhooks, logging, low-volume feeds",
                        "WebSocket: Persistent connection — good for real-time dashboards, custom C2",
                        "MQTT: Publish to broker — good for UAS telemetry, IoT, GCS, data pipelines",
                    ],
                },
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
                    "title": "JSON Output",
                    "content": [
                        "Structured JSON with sections: cot, contact, position, group, device",
                        "Optionally include base64-encoded raw CoT XML",
                    ],
                },
                {
                    "title": "MQTT Topics",
                    "content": [
                        "Topic supports {uid} and {cot_type} substitution",
                        "Example: trakbridge/{uid}/position → trakbridge/ANDROID-123/position",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="endpoint_url",
                    label="Endpoint URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    help_text=(
                        "HTTP: https://... | WebSocket: ws:// or wss:// | "
                        "MQTT: mqtt:// or mqtts://"
                    ),
                ),
                PluginConfigField(
                    name="delivery_mode",
                    label="Delivery Mode",
                    field_type="select",
                    options=[
                        {"value": "http", "label": "HTTP (POST/PUT)"},
                        {"value": "websocket", "label": "WebSocket"},
                        {"value": "mqtt", "label": "MQTT"},
                    ],
                    default_value="http",
                    help_text="How messages are delivered to the endpoint",
                ),
                PluginConfigField(
                    name="http_method",
                    label="HTTP Method",
                    field_type="select",
                    options=[
                        {"value": "POST", "label": "POST"},
                        {"value": "PUT", "label": "PUT"},
                    ],
                    default_value="POST",
                    help_text="HTTP method (only applies to HTTP mode)",
                ),
                PluginConfigField(
                    name="output_format",
                    label="Output Format",
                    field_type="select",
                    options=[
                        {"value": "json", "label": "JSON (structured)"},
                        {"value": "xml", "label": "XML (raw CoT passthrough)"},
                        {"value": "custom_template", "label": "Custom Template"},
                    ],
                    default_value="json",
                    help_text="Format of the forwarded message payload",
                ),
                PluginConfigField(
                    name="custom_template",
                    label="Custom Template",
                    field_type="text",
                    placeholder="ALERT: {callsign} at {lat},{lon}",
                    help_text="Template string using {variable} syntax (custom_template format only)",
                ),
                PluginConfigField(
                    name="custom_headers",
                    label="Custom Headers",
                    field_type="text",
                    placeholder="X-Api-Key: secret\nAuthorization: Bearer token",
                    sensitive=True,
                    help_text="One header per line: Header-Name: value",
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="Global UID Filter (regex)",
                    field_type="text",
                    placeholder="^ANDROID-.*",
                    help_text="Global pre-filter applied before message rules (optional)",
                ),
                PluginConfigField(
                    name="timeout_seconds",
                    label="Timeout (seconds)",
                    field_type="number",
                    default_value=10,
                    min_value=1,
                    max_value=60,
                    help_text="Request/connection timeout in seconds",
                ),
                PluginConfigField(
                    name="include_raw_xml",
                    label="Include Raw XML",
                    field_type="select",
                    options=[
                        {"value": "false", "label": "No"},
                        {"value": "true", "label": "Yes (base64)"},
                    ],
                    default_value="false",
                    help_text="Include base64-encoded raw CoT XML in JSON output",
                ),
                PluginConfigField(
                    name="dedup_enabled",
                    label="Deduplication",
                    field_type="select",
                    options=[
                        {"value": "true", "label": "Enabled"},
                        {"value": "false", "label": "Disabled"},
                    ],
                    default_value="true",
                    help_text="Suppress duplicate UID+type within TTL window (default: enabled for HTTP, disabled for WS/MQTT)",
                ),
                PluginConfigField(
                    name="dedup_ttl_seconds",
                    label="Dedup TTL (seconds)",
                    field_type="number",
                    default_value=5,
                    min_value=1,
                    max_value=300,
                    help_text="Deduplication window in seconds",
                ),
                PluginConfigField(
                    name="max_rate",
                    label="Max Events/Second",
                    field_type="number",
                    help_text="Rate limit (events per second). Leave empty for unlimited.",
                ),
                PluginConfigField(
                    name="stream_buffer_size",
                    label="Stream Buffer Size",
                    field_type="number",
                    default_value=100,
                    min_value=1,
                    max_value=10000,
                    help_text="Bounded buffer for WebSocket/MQTT modes. Oldest events dropped when full.",
                ),
                # MQTT-specific fields
                PluginConfigField(
                    name="mqtt_topic",
                    label="MQTT Topic",
                    field_type="text",
                    placeholder="trakbridge/events",
                    help_text="Topic to publish to. Supports {uid} and {cot_type} substitution.",
                ),
                PluginConfigField(
                    name="mqtt_qos",
                    label="MQTT QoS",
                    field_type="select",
                    options=[
                        {"value": "0", "label": "0 (At most once)"},
                        {"value": "1", "label": "1 (At least once)"},
                        {"value": "2", "label": "2 (Exactly once)"},
                    ],
                    default_value="0",
                    help_text="MQTT Quality of Service level",
                ),
                PluginConfigField(
                    name="mqtt_client_id",
                    label="MQTT Client ID",
                    field_type="text",
                    help_text="Optional. Auto-generated if not set.",
                ),
                PluginConfigField(
                    name="mqtt_username",
                    label="MQTT Username",
                    field_type="text",
                    help_text="Optional broker authentication username",
                ),
                PluginConfigField(
                    name="mqtt_password",
                    label="MQTT Password",
                    field_type="text",
                    sensitive=True,
                    help_text="Optional broker authentication password",
                ),
                PluginConfigField(
                    name="mqtt_keepalive",
                    label="MQTT Keepalive (seconds)",
                    field_type="number",
                    default_value=60,
                    min_value=10,
                    max_value=600,
                    help_text="MQTT keepalive interval in seconds",
                ),
            ],
            "custom_components": [
                PluginCustomComponent(
                    type="message_rules",
                    field_name="message_rules",
                    title="Message Rules",
                    icon="fa-filter",
                    help_text=(
                        "Define rules to filter and format CoT messages. "
                        "Rules are evaluated in order; first matching rule wins."
                    ),
                    config={
                        "template_variables": [
                            "{type}", "{uid}", "{time}", "{stale}",
                            "{callsign}", "{remarks}",
                            "{lat}", "{lon}", "{hae}", "{mgrs}",
                            "{group_name}", "{group_role}",
                            "{device}", "{platform}", "{os}",
                            "{version}", "{battery}",
                            "{speed}", "{course}", "{xmpp_username}",
                        ],
                        "rule_fields": [
                            {
                                "name": "cot_type_pattern",
                                "label": "CoT Type Pattern",
                                "type": "text",
                                "required": True,
                                "placeholder": "a-f-* (wildcards supported)",
                                "help": "Pattern to match CoT types",
                            },
                            {
                                "name": "uid_filter",
                                "label": "UID Filter (regex)",
                                "type": "text",
                                "required": False,
                                "placeholder": "^ANDROID-.*",
                                "help": "Optional regex to filter by UID",
                            },
                            {
                                "name": "format_template",
                                "label": "Format Template",
                                "type": "textarea",
                                "required": True,
                                "placeholder": "{callsign} at {lat},{lon}",
                                "help": "Message format using template variables",
                            },
                        ],
                    },
                ),
                PluginCustomComponent(
                    type="geofence",
                    field_name="global_geofence",
                    title="Geofence",
                    icon="fa-map-marked-alt",
                    help_text=(
                        "Filter messages by geographic bounds. Only messages "
                        "within the defined area will be forwarded."
                    ),
                    config={
                        "default_center": [40.7, -74.0],
                        "default_zoom": 10,
                        "enable_checkbox_label": "Enable Geofence Filtering",
                    },
                ),
            ],
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Initialize persistent connections for WebSocket/MQTT modes."""
        config = self.get_decrypted_config()
        mode = config.get("delivery_mode", "http")

        if mode == "websocket":
            buffer_size = int(config.get("stream_buffer_size", 100))
            self._ws_queue = asyncio.Queue(maxsize=buffer_size)
            await self._connect_websocket()
        elif mode == "mqtt":
            await self._connect_mqtt()

    async def cleanup(self):
        """Release resources for persistent connections."""
        if self._ws_writer_task:
            self._ws_writer_task.cancel()
            self._ws_writer_task = None

        if self._ws_connection:
            try:
                await self._ws_connection.close()
            except Exception:
                pass
            self._ws_connection = None
            self._ws_connected = False

        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_client = None
            self._mqtt_connected = False

    # ------------------------------------------------------------------
    # Main handler — dispatches to the configured delivery mode
    # ------------------------------------------------------------------

    async def handle_cot_message(
        self, cot_xml: bytes, tak_server_id: int
    ) -> None:
        """Parse CoT, filter, convert, and deliver via configured mode."""
        try:
            root = DefusedET.fromstring(cot_xml)
        except Exception as e:
            logger.error(f"WebhookHandler failed to parse CoT XML: {e}")
            return

        cot_type = root.get("type", "")
        uid = root.get("uid", "")

        # Extract lat/lon for geofence
        point = root.find("point")
        lat = point.get("lat", "") if point is not None else ""
        lon = point.get("lon", "") if point is not None else ""

        # Filtering
        should_handle, template = self._should_handle(cot_type, uid, lat, lon)
        if not should_handle:
            return

        config = self.get_decrypted_config()
        mode = config.get("delivery_mode", "http")

        # Deduplication — enabled by default for HTTP, disabled for WS/MQTT
        if self._should_dedup(config, mode):
            dedup_key = f"{uid}:{cot_type}"
            now = time.time()
            ttl = float(config.get("dedup_ttl_seconds", 5))

            # Prune old entries
            self._seen_messages = {
                k: v for k, v in self._seen_messages.items()
                if now - v < ttl
            }

            if dedup_key in self._seen_messages:
                return
            self._seen_messages[dedup_key] = now

        # Rate throttle (WebSocket/MQTT modes)
        if mode in ("websocket", "mqtt"):
            max_rate_str = config.get("max_rate", "")
            if max_rate_str:
                max_rate = float(max_rate_str)
                now = time.time()
                min_interval = 1.0 / max_rate
                if (now - self._last_event_time) < min_interval:
                    self._events_dropped += 1
                    return
                self._last_event_time = now

        # Build payload
        payload = self._build_payload(root, cot_xml, tak_server_id, config, template)

        # Deliver
        try:
            if mode == "http":
                await self._send_http(payload)
            elif mode == "websocket":
                self._enqueue_websocket(payload)
            elif mode == "mqtt":
                self._publish_mqtt(payload, uid, cot_type, config)

            self._events_sent += 1

        except Exception as e:
            logger.error(f"WebhookHandler delivery failed ({mode}): {e}")
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # Payload building
    # ------------------------------------------------------------------

    def _build_payload(self, root, cot_xml, tak_server_id, config, template):
        """Build the output payload based on the configured format."""
        output_format = config.get("output_format", "json")

        if output_format == "xml":
            # Raw CoT passthrough
            return cot_xml

        if output_format == "custom_template":
            variables = self._extract_template_variables(root)
            custom_tpl = config.get("custom_template", template or "{callsign}")
            return self._format_message(custom_tpl, variables)

        # Default: structured JSON
        variables = self._extract_template_variables(root)
        payload = {
            "source": "trakbridge",
            "tak_server_id": tak_server_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cot": {
                "type": root.get("type", ""),
                "uid": root.get("uid", ""),
                "time": root.get("time", ""),
                "stale": root.get("stale", ""),
            },
            "contact": {
                "callsign": variables.get("callsign", "Unknown"),
            },
            "position": {
                "lat": variables.get("lat", ""),
                "lon": variables.get("lon", ""),
                "hae": variables.get("hae", ""),
                "mgrs": variables.get("mgrs", ""),
                "speed": variables.get("speed", ""),
                "course": variables.get("course", ""),
            },
            "group": {
                "name": variables.get("group_name", ""),
                "role": variables.get("group_role", ""),
            },
            "device": {
                "device": variables.get("device", ""),
                "platform": variables.get("platform", ""),
                "os": variables.get("os", ""),
                "version": variables.get("version", ""),
                "battery": variables.get("battery", ""),
            },
            "remarks": variables.get("remarks", ""),
        }

        # Optionally include raw XML as base64
        if config.get("include_raw_xml", "false") == "true":
            payload["raw_xml"] = base64.b64encode(cot_xml).decode("ascii")

        return payload

    # ------------------------------------------------------------------
    # HTTP delivery
    # ------------------------------------------------------------------

    async def _send_http(self, payload) -> None:
        """Send payload via HTTP POST or PUT."""
        config = self.get_decrypted_config()
        url = config.get("endpoint_url", "")
        method = config.get("http_method", "POST").upper()
        timeout_sec = int(config.get("timeout_seconds", 10))

        headers = self._parse_custom_headers(config.get("custom_headers", ""))

        ssl_context = ssl.create_default_context(cafile=certifi.where())

        try:
            async with aiohttp.ClientSession() as session:
                if isinstance(payload, (bytes, str)):
                    # XML passthrough or custom template
                    if isinstance(payload, bytes):
                        headers.setdefault("Content-Type", "application/xml")
                        data = payload
                        kwargs = {"data": data, "headers": headers,
                                  "ssl": ssl_context,
                                  "timeout": aiohttp.ClientTimeout(total=timeout_sec)}
                    else:
                        headers.setdefault("Content-Type", "text/plain")
                        data = payload
                        kwargs = {"data": data, "headers": headers,
                                  "ssl": ssl_context,
                                  "timeout": aiohttp.ClientTimeout(total=timeout_sec)}
                else:
                    # JSON
                    headers.setdefault("Content-Type", "application/json")
                    kwargs = {"json": payload, "headers": headers,
                              "ssl": ssl_context,
                              "timeout": aiohttp.ClientTimeout(total=timeout_sec)}

                send_fn = getattr(session, method.lower())
                async with send_fn(url, **kwargs) as resp:
                    if resp.status >= 400:
                        logger.warning(
                            f"Webhook HTTP {method} to {url} returned {resp.status}"
                        )
        except Exception as e:
            logger.error(f"Webhook HTTP delivery failed: {e}")

    def _parse_custom_headers(self, raw: str) -> Dict[str, str]:
        """Parse 'Header-Name: value' lines into a dict."""
        headers: Dict[str, str] = {}
        if not raw:
            return headers
        for line in raw.strip().split("\n"):
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip()] = value.strip()
        return headers

    # ------------------------------------------------------------------
    # WebSocket delivery
    # ------------------------------------------------------------------

    async def _connect_websocket(self) -> None:
        """Open a persistent WebSocket connection and start the writer task."""
        config = self.get_decrypted_config()
        url = config.get("endpoint_url", "")
        headers = self._parse_custom_headers(config.get("custom_headers", ""))

        try:
            session = aiohttp.ClientSession()
            self._ws_session = session
            self._ws_connection = await session.ws_connect(
                url, headers=headers
            )
            self._ws_connected = True
            self._ws_writer_task = asyncio.create_task(self._ws_writer_loop())
            logger.info(f"WebSocket connected to {url}")
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self._ws_connected = False

    async def _ws_writer_loop(self) -> None:
        """Background task that drains the queue and writes to WebSocket."""
        backoff = 1.0
        max_backoff = 60.0

        while True:
            try:
                payload = await self._ws_queue.get()

                if not self._ws_connected or not self._ws_connection:
                    # Attempt reconnect
                    await self._connect_websocket()
                    if not self._ws_connected:
                        await asyncio.sleep(min(backoff, max_backoff))
                        backoff = min(backoff * 2, max_backoff)
                        continue

                if isinstance(payload, (bytes, str)):
                    await self._ws_connection.send_str(
                        payload if isinstance(payload, str) else payload.decode("utf-8", errors="replace")
                    )
                else:
                    await self._ws_connection.send_str(json.dumps(payload))

                backoff = 1.0  # Reset on success

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WebSocket write error: {e}")
                self._ws_connected = False
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)

    def _enqueue_websocket(self, payload) -> None:
        """Non-blocking enqueue; drops oldest if buffer is full."""
        if self._ws_queue is None:
            return

        if self._ws_queue.full():
            try:
                self._ws_queue.get_nowait()  # Drop oldest
                self._events_dropped += 1
            except asyncio.QueueEmpty:
                pass

        try:
            self._ws_queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # MQTT delivery
    # ------------------------------------------------------------------

    async def _connect_mqtt(self) -> None:
        """Connect to MQTT broker using paho-mqtt."""
        import paho.mqtt.client as paho_mqtt

        config = self.get_decrypted_config()
        url = config.get("endpoint_url", "")
        client_id = config.get("mqtt_client_id", "")
        keepalive = int(config.get("mqtt_keepalive", 60))

        # Parse host/port from endpoint_url
        # mqtt://host:port or mqtts://host:port
        host, port, use_tls = self._parse_mqtt_url(url)

        client = paho_mqtt.Client(client_id=client_id or None)

        # Auth
        username = config.get("mqtt_username", "")
        password = config.get("mqtt_password", "")
        if username:
            client.username_pw_set(username, password)

        if use_tls:
            client.tls_set()

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._mqtt_connected = True
                logger.info(f"MQTT connected to {host}:{port}")
            else:
                logger.error(f"MQTT connection failed with rc={rc}")

        def on_disconnect(client, userdata, rc):
            self._mqtt_connected = False
            if rc != 0:
                logger.warning(f"MQTT unexpected disconnect (rc={rc}), will reconnect")

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=60)

        try:
            client.connect(host, port, keepalive=keepalive)
            client.loop_start()
            self._mqtt_client = client
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")

    def _parse_mqtt_url(self, url: str):
        """Parse mqtt:// or mqtts:// URL into (host, port, use_tls)."""
        use_tls = url.startswith("mqtts://")
        stripped = url.replace("mqtts://", "").replace("mqtt://", "")
        if ":" in stripped:
            host, port_str = stripped.split(":", 1)
            # Strip trailing path if any
            port_str = port_str.split("/")[0]
            port = int(port_str)
        else:
            host = stripped.split("/")[0]
            port = 8883 if use_tls else 1883
        return host, port, use_tls

    def _publish_mqtt(self, payload, uid: str, cot_type: str, config: dict) -> None:
        """Publish a message to the configured MQTT topic."""
        if not self._mqtt_client or not self._mqtt_connected:
            logger.warning("MQTT not connected, dropping message")
            self._events_dropped += 1
            return

        topic = config.get("mqtt_topic", "trakbridge/events")
        # Topic substitution
        topic = topic.replace("{uid}", uid).replace("{cot_type}", cot_type)

        qos = int(config.get("mqtt_qos", 0))

        if isinstance(payload, (bytes, str)):
            msg = payload
        else:
            msg = json.dumps(payload)

        self._mqtt_client.publish(topic, msg, qos=qos)

    # ------------------------------------------------------------------
    # Filtering (same pattern as Discord/Slack handlers)
    # ------------------------------------------------------------------

    def _should_handle(
        self, cot_type: str, uid: str, lat: str = "", lon: str = ""
    ) -> tuple:
        """Returns (should_handle, template) based on config rules."""
        config = self.get_decrypted_config()

        # Global UID filter
        global_uid_filter = config.get("uid_filter", "")
        if global_uid_filter:
            try:
                if not re.match(global_uid_filter, uid):
                    return (False, "")
            except re.error:
                return (False, "")

        # Geofence
        if config.get("global_geofence_enabled", "false") == "true":
            bounds = config.get("global_geofence_bounds", {})
            if bounds and lat and lon:
                if not self._is_within_geofence(lat, lon, bounds):
                    return (False, "")

        # Message rules
        message_rules = config.get("message_rules", [])
        if not message_rules:
            return (False, "")

        for rule in message_rules:
            if not rule.get("enabled", True):
                continue

            # Per-rule UID filter
            rule_uid_filter = rule.get("uid_filter", "")
            if rule_uid_filter:
                try:
                    if not re.match(rule_uid_filter, uid):
                        continue
                except re.error:
                    continue

            pattern = rule.get("cot_type_pattern", "")
            if pattern and self._matches_cot_pattern(cot_type, pattern):
                return (True, rule.get("format_template", ""))

        return (False, "")

    def _matches_cot_pattern(self, cot_type: str, pattern: str) -> bool:
        """Check if CoT type matches pattern (supports wildcards)."""
        if pattern.endswith("*"):
            return cot_type.startswith(pattern[:-1])
        return cot_type == pattern

    def _is_within_geofence(self, lat: str, lon: str, bounds: dict) -> bool:
        """Check if coordinates are within bounding box."""
        try:
            lat_f = float(lat)
            lon_f = float(lon)
            north = float(bounds.get("north", 90))
            south = float(bounds.get("south", -90))
            east = float(bounds.get("east", 180))
            west = float(bounds.get("west", -180))
            return south <= lat_f <= north and west <= lon_f <= east
        except (ValueError, TypeError):
            return True  # Fail open

    # ------------------------------------------------------------------
    # Variable extraction (same as Discord/Slack)
    # ------------------------------------------------------------------

    def _extract_template_variables(self, root) -> Dict[str, str]:
        """Extract template variables from CoT XML."""
        variables = {
            "type": root.get("type", ""),
            "uid": root.get("uid", ""),
            "time": root.get("time", ""),
            "stale": root.get("stale", ""),
            "callsign": "Unknown",
            "lat": "", "lon": "", "hae": "", "mgrs": "",
            "remarks": "",
            "group_name": "", "group_role": "",
            "battery": "",
            "device": "", "platform": "", "os": "", "version": "",
            "speed": "", "course": "",
            "xmpp_username": "",
        }

        point = root.find("point")
        if point is not None:
            variables["lat"] = point.get("lat", "")
            variables["lon"] = point.get("lon", "")
            variables["hae"] = point.get("hae", "")

            if variables["lat"] and variables["lon"]:
                try:
                    m = mgrs.MGRS()
                    variables["mgrs"] = m.toMGRS(
                        float(variables["lat"]), float(variables["lon"])
                    )
                except Exception:
                    variables["mgrs"] = ""

        detail = root.find("detail")
        if detail is not None:
            contact = detail.find("contact")
            if contact is not None:
                variables["callsign"] = contact.get("callsign", "Unknown")
                variables["xmpp_username"] = contact.get("xmppUsername", "")

            remarks = detail.find("remarks")
            if remarks is not None and remarks.text:
                variables["remarks"] = remarks.text

            group = detail.find("__group")
            if group is not None:
                variables["group_name"] = group.get("name", "")
                variables["group_role"] = group.get("role", "")

            status = detail.find("status")
            if status is not None:
                variables["battery"] = status.get("battery", "")

            takv = detail.find("takv")
            if takv is not None:
                variables["device"] = takv.get("device", "")
                variables["platform"] = takv.get("platform", "")
                variables["os"] = takv.get("os", "")
                variables["version"] = takv.get("version", "")

            track = detail.find("track")
            if track is not None:
                variables["speed"] = track.get("speed", "")
                variables["course"] = track.get("course", "")

        return variables

    def _format_message(self, template: str, variables: Dict[str, str]) -> str:
        """Format message using template and variables."""
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Template variable missing: {e}")
            return f"{template} [ERROR: missing variable {e}]"
        except Exception as e:
            logger.error(f"Template formatting error: {e}")
            return template

    # ------------------------------------------------------------------
    # Dedup helper
    # ------------------------------------------------------------------

    def _should_dedup(self, config: dict, mode: str) -> bool:
        """Determine if dedup is active based on config and mode defaults."""
        explicit = config.get("dedup_enabled")
        if explicit is not None:
            return str(explicit).lower() == "true"
        # Default: enabled for HTTP, disabled for WS/MQTT
        return mode == "http"

    # ------------------------------------------------------------------
    # Health stats
    # ------------------------------------------------------------------

    def get_health_stats(self) -> Dict[str, Any]:
        """Return current health statistics."""
        config = self.get_decrypted_config()
        mode = config.get("delivery_mode", "http")

        stats = {
            "delivery_mode": mode,
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
        }

        if mode == "websocket":
            stats["ws_connected"] = self._ws_connected
            stats["buffer_size"] = self._ws_queue.qsize() if self._ws_queue else 0
        elif mode == "mqtt":
            stats["mqtt_connected"] = self._mqtt_connected

        return stats

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    async def test_connection(self) -> Dict[str, Any]:
        """Test the configured endpoint connection."""
        config = self.get_decrypted_config()
        url = config.get("endpoint_url", "")
        mode = config.get("delivery_mode", "http")

        if not url:
            return {"success": False, "error": "Missing endpoint URL"}

        if mode == "http":
            try:
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                async with aiohttp.ClientSession() as session:
                    async with session.head(
                        url,
                        ssl=ssl_context,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        return {
                            "success": True,
                            "message": f"Endpoint responded with HTTP {resp.status}",
                        }
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": True, "message": f"Configuration valid for {mode} mode"}
