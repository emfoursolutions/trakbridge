# ABOUTME: Outbound MQTT plugin — publishes CoT events to an MQTT broker topic.
# ABOUTME: Maintains a persistent paho-mqtt connection with a bounded send queue and rate limiter.

import asyncio
import logging
from typing import Any, Dict, Optional

from plugins.base_plugin import (
    BaseOutputPlugin,
    PluginConfigField,
    PluginCustomComponent,
)
from services.output_plugin_helpers import (
    Deduplicator,
    RateLimiter,
    build_payload,
    extract_cot_variables,
    should_handle,
)

logger = logging.getLogger(__name__)


class OutboundMQTT(BaseOutputPlugin):
    """
    Outbound plugin that publishes CoT events to an MQTT broker topic.

    Maintains a persistent paho-mqtt connection. Incoming events pass through
    the filter → dedup → rate-limit pipeline and are placed on a bounded queue.
    A background writer task drains the queue and publishes via paho-mqtt.
    The queue is bounded by stream_buffer_size; when full, the oldest item is
    dropped and the new item takes its place.
    """

    PLUGIN_NAME = "outbound_mqtt"

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._events_sent: int = 0
        self._events_dropped: int = 0
        self._last_error: Optional[str] = None
        self._connected: bool = False
        self._mqtt_client = None
        self._writer_task: Optional[asyncio.Task] = None
        self._queue: Optional[asyncio.Queue] = None

        # Local TTL cache — do NOT reach into Deduplicator._ttl
        self._deduplicator: Optional[Deduplicator] = None
        self._dedup_ttl: Optional[int] = None

        self._rate_limiter: Optional[RateLimiter] = None

    # ------------------------------------------------------------------
    # BaseOutputPlugin abstract interface
    # ------------------------------------------------------------------

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Outbound MQTT",
            "description": (
                "Publish CoT events to an MQTT broker topic. "
                "Supports JSON, raw XML, and custom template output formats. "
                "Maintains a persistent connection with a bounded send queue."
            ),
            "icon": "fas fa-broadcast-tower",
            "category": "forwarding",
            "config_fields": [
                PluginConfigField(
                    name="broker_url",
                    label="Broker URL",
                    field_type="url",
                    required=True,
                    placeholder="mqtt://broker.example.com:1883",
                    help_text="MQTT broker URL. Use mqtts:// for TLS.",
                ),
                PluginConfigField(
                    name="topic",
                    label="Topic",
                    field_type="text",
                    required=True,
                    placeholder="trakbridge/events",
                    help_text=(
                        "MQTT topic to publish to. "
                        "Supports {uid} and {cot_type} substitution."
                    ),
                ),
                PluginConfigField(
                    name="qos",
                    label="QoS Level",
                    field_type="select",
                    options=[
                        {"value": "0", "label": "0 — At most once"},
                        {"value": "1", "label": "1 — At least once"},
                        {"value": "2", "label": "2 — Exactly once"},
                    ],
                    default_value="0",
                    help_text="MQTT Quality of Service level.",
                ),
                PluginConfigField(
                    name="client_id",
                    label="Client ID",
                    field_type="text",
                    default_value="trakbridge",
                    help_text="MQTT client identifier. Must be unique per broker.",
                ),
                PluginConfigField(
                    name="username",
                    label="Username",
                    field_type="text",
                    default_value="",
                    help_text="Optional broker username.",
                ),
                PluginConfigField(
                    name="password",
                    label="Password",
                    field_type="password",
                    default_value="",
                    sensitive=True,
                    help_text="Optional broker password.",
                ),
                PluginConfigField(
                    name="keepalive",
                    label="Keepalive (seconds)",
                    field_type="number",
                    default_value=60,
                    min_value=10,
                    max_value=600,
                    help_text="MQTT keepalive interval in seconds.",
                ),
                PluginConfigField(
                    name="ca_source",
                    label="CA Certificate Source",
                    field_type="select",
                    options=[
                        {"value": "system", "label": "System CA bundle"},
                        {"value": "tak_server", "label": "TAK Server certificate"},
                        {"value": "upload", "label": "Uploaded CA certificate"},
                    ],
                    default_value="system",
                    help_text=(
                        "Certificate authority used to verify the broker TLS certificate. "
                        "Only applies when using mqtts://."
                    ),
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
                    help_text="Format of the payload published to the MQTT topic.",
                ),
                PluginConfigField(
                    name="custom_template",
                    label="Custom Template",
                    field_type="text",
                    placeholder="ALERT: {callsign} at {lat},{lon}",
                    default_value="",
                    help_text=(
                        "Template string using {variable} syntax. "
                        "Only used when output_format is 'custom_template'."
                    ),
                    depends_on={"output_format": "custom_template"},
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="Global UID Filter (regex)",
                    field_type="text",
                    default_value="",
                    placeholder="^ANDROID-.*",
                    help_text=(
                        "Optional regex applied to event UID before message rules. "
                        "Leave empty to skip UID filtering."
                    ),
                ),
                PluginConfigField(
                    name="include_raw_xml",
                    label="Include Raw XML",
                    field_type="checkbox",
                    default_value="false",
                    help_text=(
                        "When enabled, the JSON payload includes a 'raw_xml' field "
                        "containing the base64-encoded original CoT XML."
                    ),
                ),
                PluginConfigField(
                    name="timeout_seconds",
                    label="Timeout (seconds)",
                    field_type="number",
                    default_value=10,
                    min_value=1,
                    max_value=60,
                    help_text="Broker connection timeout in seconds.",
                ),
                PluginConfigField(
                    name="max_rate",
                    label="Max Rate (events/sec)",
                    field_type="number",
                    default_value="",
                    help_text=(
                        "Maximum events per second to publish. "
                        "Leave blank for unlimited throughput."
                    ),
                ),
                PluginConfigField(
                    name="stream_buffer_size",
                    label="Buffer Size",
                    field_type="number",
                    default_value=100,
                    help_text=(
                        "Maximum number of events held in the send queue. "
                        "When full, the oldest event is dropped."
                    ),
                ),
                PluginConfigField(
                    name="dedup_enabled",
                    label="Deduplication",
                    field_type="checkbox",
                    default_value="false",
                    help_text=(
                        "Suppress duplicate UID+type events within the TTL window. "
                        "Off by default because MQTT brokers handle deduplication at QoS≥1."
                    ),
                ),
                PluginConfigField(
                    name="dedup_ttl_seconds",
                    label="Dedup TTL (seconds)",
                    field_type="number",
                    default_value=5,
                    min_value=1,
                    max_value=300,
                    help_text="How long (seconds) to remember a seen event for dedup.",
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
                                "help": "Optional regex to filter by UID within this rule",
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
    # URL parsing
    # ------------------------------------------------------------------

    def _parse_mqtt_url(self, url: str):
        """Parse mqtt:// or mqtts:// URL into (host, port, use_tls).

        Raises ValueError for unrecognised schemes.
        """
        if url.startswith("mqtts://"):
            use_tls = True
            stripped = url[len("mqtts://"):]
        elif url.startswith("mqtt://"):
            use_tls = False
            stripped = url[len("mqtt://"):]
        else:
            raise ValueError(f"Unsupported MQTT URL scheme: {url!r}")

        # Strip trailing path component
        host_port = stripped.split("/")[0]

        if ":" in host_port:
            host, port_str = host_port.split(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 8883 if use_tls else 1883

        return host, port, use_tls

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the MQTT broker and start the background writer task."""
        import paho.mqtt.client as paho_mqtt

        config = self.config
        broker_url = config.get("broker_url", "")
        client_id = config.get("client_id", "trakbridge") or "trakbridge"
        keepalive = int(config.get("keepalive", 60))
        username = config.get("username", "") or ""
        password = config.get("password", "") or ""
        ca_source = config.get("ca_source", "system") or "system"
        buffer_size = int(config.get("stream_buffer_size", 100))

        host, port, use_tls = self._parse_mqtt_url(broker_url)

        client = paho_mqtt.Client(client_id=client_id or None)

        if username:
            client.username_pw_set(username, password)

        if use_tls:
            from services.cert_utils import build_ssl_context
            ssl_ctx = build_ssl_context(ca_source, self.stream)
            client.tls_set_context(ssl_ctx)

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._connected = True
                logger.info("outbound_mqtt: connected to %s:%s", host, port)
            else:
                self._connected = False
                logger.error("outbound_mqtt: connection failed rc=%s", rc)

        def on_disconnect(client, userdata, rc):
            self._connected = False
            if rc != 0:
                logger.warning(
                    "outbound_mqtt: unexpected disconnect (rc=%s), paho will reconnect", rc
                )

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.reconnect_delay_set(min_delay=1, max_delay=60)

        try:
            client.connect(host, port, keepalive=keepalive)
            client.loop_start()
            self._mqtt_client = client
        except Exception as exc:
            logger.error("outbound_mqtt: broker connection failed: %s", exc)
            self._last_error = str(exc)

        # Initialise the bounded send queue and rate limiter
        self._queue = asyncio.Queue(maxsize=buffer_size)

        max_rate_raw = config.get("max_rate", "") or ""
        max_rate = float(max_rate_raw) if max_rate_raw else None
        self._rate_limiter = RateLimiter(max_rate)

        # Start the background writer task
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def cleanup(self) -> None:
        """Stop the writer task and disconnect from the broker."""
        if self._writer_task and not self._writer_task.done():
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        self._writer_task = None

        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception as exc:
                logger.warning("outbound_mqtt: error during cleanup: %s", exc)
            self._mqtt_client = None

        self._connected = False

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Process one CoT event through the filter → dedup → rate-limit → enqueue pipeline."""
        config = self.config

        uid_filter = config.get("uid_filter", "") or ""
        geofence = config.get("global_geofence") or {}
        message_rules = config.get("message_rules") or []

        # 1. Filter: uid_filter → geofence → message_rules
        passed, _template = should_handle(cot_xml, uid_filter, geofence, message_rules)
        if not passed:
            self._events_dropped += 1
            return

        # 2. Deduplication
        dedup_enabled = str(config.get("dedup_enabled", "false")).lower() == "true"
        if dedup_enabled:
            dedup_ttl = int(config.get("dedup_ttl_seconds", 5))
            if self._deduplicator is None or self._dedup_ttl != dedup_ttl:
                self._deduplicator = Deduplicator(ttl_seconds=dedup_ttl)
                self._dedup_ttl = dedup_ttl

            try:
                from defusedxml import ElementTree as _ET
                root = _ET.fromstring(cot_xml)
                uid = root.get("uid", "")
                cot_type = root.get("type", "")
            except Exception:
                uid, cot_type = "", ""

            dedup_key = f"{uid}:{cot_type}"
            if not self._deduplicator.check(dedup_key):
                self._events_dropped += 1
                return

        # 3. Rate limit
        if self._rate_limiter and not self._rate_limiter.check():
            self._events_dropped += 1
            return

        # 4. Extract variables and build payload
        output_format = config.get("output_format", "json")
        custom_template = config.get("custom_template", "") or ""
        include_raw_xml = str(config.get("include_raw_xml", "false")).lower() == "true"

        variables = extract_cot_variables(cot_xml)
        payload = build_payload(variables, output_format, custom_template, include_raw_xml, cot_xml)

        # 5. Build the topic with variable substitution
        topic_template = config.get("topic", "trakbridge/events") or "trakbridge/events"
        uid_val = variables.get("uid", "")
        cot_type_val = variables.get("type", "")
        topic = topic_template.replace("{uid}", uid_val).replace("{cot_type}", cot_type_val)

        # 6. Enqueue — if full, drop oldest and count it
        if self._queue is None:
            return

        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                pass
            self._events_dropped += 1

        try:
            self._queue.put_nowait((topic, payload))
        except asyncio.QueueFull:
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    async def _writer_loop(self) -> None:
        """Drain the queue and publish each item to the MQTT broker."""
        while True:
            try:
                topic, payload = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                if not self._connected or not self._mqtt_client:
                    # Re-enqueue so the event buffers until reconnected — but to
                    # avoid infinite spin when the queue is empty, put it back and yield.
                    try:
                        self._queue.put_nowait((topic, payload))
                    except asyncio.QueueFull:
                        self._events_dropped += 1
                    await asyncio.sleep(0.1)
                    continue

                qos = int(self.config.get("qos", 0))

                try:
                    result = self._mqtt_client.publish(topic, payload, qos=qos)
                    if result.rc != 0:
                        error_msg = f"MQTT publish returned rc={result.rc}"
                        logger.warning("outbound_mqtt: %s", error_msg)
                        self._last_error = error_msg
                        self._events_dropped += 1
                    else:
                        self._events_sent += 1
                except Exception as exc:
                    error_msg = f"MQTT publish error: {exc}"
                    logger.error("outbound_mqtt: %s", error_msg)
                    self._last_error = error_msg
                    self._events_dropped += 1
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def get_health_stats(self) -> dict:
        """Return connection state and counters for monitoring and UI display."""
        return {
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "mqtt_connected": self._connected,
            "buffer_size": self._queue.qsize() if self._queue else 0,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    async def test_connection(self):
        """Attempt a brief connection to verify broker reachability.

        Returns a (success: bool, message: str) tuple.
        """
        import paho.mqtt.client as paho_mqtt

        broker_url = self.config.get("broker_url", "")
        try:
            host, port, use_tls = self._parse_mqtt_url(broker_url)
        except ValueError as exc:
            return (False, str(exc))

        result = {"connected": False}
        event = asyncio.Event()

        def on_connect(client, userdata, flags, rc):
            result["connected"] = rc == 0
            event.set()

        client = paho_mqtt.Client(client_id="trakbridge-test")
        client.on_connect = on_connect

        username = self.config.get("username", "") or ""
        password = self.config.get("password", "") or ""
        if username:
            client.username_pw_set(username, password)

        if use_tls:
            try:
                from services.cert_utils import build_ssl_context
                ssl_ctx = build_ssl_context(
                    self.config.get("ca_source", "system"), self.stream
                )
                client.tls_set_context(ssl_ctx)
            except Exception as exc:
                return (False, f"TLS setup failed: {exc}")

        try:
            client.connect(host, port, keepalive=10)
            client.loop_start()

            timeout = int(self.config.get("timeout_seconds", 10))
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return (False, f"Connection timed out after {timeout}s")
            finally:
                client.loop_stop()
                client.disconnect()

            if result["connected"]:
                return (True, f"Connected to {host}:{port}")
            return (False, f"Broker rejected connection to {host}:{port}")

        except Exception as exc:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
            return (False, str(exc))
