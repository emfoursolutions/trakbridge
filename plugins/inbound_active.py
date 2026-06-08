# ABOUTME: Active-connect inbound plugin — dials out to MQTT or WebSocket,
# ABOUTME: receives messages, and converts them to CoT for TAK servers.

import asyncio
import json
from typing import Any, Dict, Optional

import aiohttp

from plugins.base_plugin import BaseInboundPlugin, PluginConfigField

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


class InboundActive(BaseInboundPlugin):
    """
    Inbound plugin that actively connects to an MQTT broker or WebSocket.

    Subscribes/reads arriving messages and converts them to CoT for TAK
    servers. Unlike HTTP-push inbound plugins, this plugin dials out via
    start() and manages a persistent connection. transform_payload() is
    not used.
    """

    PLUGIN_NAME = "inbound_active"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        self._mqtt_client = None
        self._mqtt_connected: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._ws_connection = None
        self._ws_session = None
        self._ws_reader_task: Optional[asyncio.Task] = None
        self._ws_connected: bool = False

        self._messages_received: int = 0
        self._messages_failed: int = 0

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Inbound Active",
            "description": (
                "Connect to an MQTT broker or WebSocket and receive position data, "
                "converting it to CoT for TAK servers"
            ),
            "icon": "fa-arrow-down",
            "category": "inbound",
            "inbound_transport": "active",
            "accepted_content_types": ["application/json"],
            "help_sections": [
                {
                    "title": "Overview",
                    "content": [
                        "TrakBridge dials out and subscribes to the remote source",
                        "Arriving messages are parsed and converted to CoT",
                        "MQTT: connects to a broker and subscribes to a topic",
                        "WebSocket: connects to a server and reads messages",
                        "Reconnection is automatic with exponential backoff",
                    ],
                },
                {
                    "title": "Field Mapping",
                    "content": [
                        "Use dot-notation paths to extract values from JSON messages",
                        "Example: position.latitude for nested structures",
                        "Latitude, Longitude, and UID are required per message",
                        "Callsign falls back to UID if the field is absent",
                    ],
                },
                {
                    "title": "MQTT Settings",
                    "content": [
                        "Broker URL: mqtt:// for plain, mqtts:// for TLS",
                        "Subscribe Topic: wildcards + and # are supported",
                        "Client ID must be unique per stream on the same broker",
                        "TLS CA Source (Uploaded): upload a cert in the CA Certificate section",
                    ],
                },
                {
                    "title": "CoT Output",
                    "content": [
                        "CoT Type: the marker type that appears on the TAK map",
                        "Stale Time: how long the marker persists without a fresh update",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="source_url",
                    label="Source URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    allowed_schemes=("mqtt://", "mqtts://", "ws://", "wss://"),
                    help_text=(
                        "MQTT: mqtt://host:port or mqtts://host:port | "
                        "WebSocket: ws://host:port or wss://host:port"
                    ),
                ),
                PluginConfigField(
                    name="transport",
                    label="Transport",
                    field_type="select",
                    options=[
                        {"value": "mqtt", "label": "MQTT"},
                        {"value": "websocket", "label": "WebSocket"},
                    ],
                    default_value="mqtt",
                    help_text="Protocol to use when connecting to the source",
                ),
                # MQTT-specific fields
                PluginConfigField(
                    name="mqtt_subscribe_topic",
                    label="Subscribe Topic",
                    field_type="text",
                    placeholder="sensors/+/position",
                    help_text="MQTT topic to subscribe to (+ and # wildcards supported)",
                    depends_on={"field": "transport", "values": ["mqtt"]},
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
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                PluginConfigField(
                    name="mqtt_client_id",
                    label="MQTT Client ID",
                    field_type="text",
                    default_value="trakbridge-inbound",
                    help_text=(
                        "Unique client identifier. "
                        "Each stream on the same broker needs a distinct ID."
                    ),
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                PluginConfigField(
                    name="mqtt_username",
                    label="MQTT Username",
                    field_type="text",
                    help_text="Optional broker authentication username",
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                PluginConfigField(
                    name="mqtt_password",
                    label="MQTT Password",
                    field_type="password",
                    sensitive=True,
                    help_text="Optional broker authentication password",
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                PluginConfigField(
                    name="mqtt_keepalive",
                    label="MQTT Keepalive (seconds)",
                    field_type="number",
                    default_value=60,
                    min_value=10,
                    max_value=600,
                    help_text="MQTT keepalive interval in seconds",
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                PluginConfigField(
                    name="ca_source",
                    label="TLS CA Certificate Source",
                    field_type="select",
                    options=[
                        {"value": "system", "label": "System CA Bundle (default)"},
                        {"value": "tak_server", "label": "Reuse TAK Server Certificate CA"},
                        {"value": "upload", "label": "Uploaded CA Certificate"},
                    ],
                    default_value="system",
                    help_text=(
                        "How to verify the remote TLS certificate. "
                        "'Uploaded CA Certificate' uses the cert uploaded below."
                    ),
                    depends_on={"field": "transport", "values": ["mqtt"]},
                ),
                # Field mapping
                PluginConfigField(
                    name="lat_field",
                    label="Latitude Field",
                    field_type="text",
                    default_value="lat",
                    placeholder="lat or position.latitude",
                    help_text="Dot-notation path to latitude in the message JSON",
                    row_group="field_row_1",
                ),
                PluginConfigField(
                    name="lon_field",
                    label="Longitude Field",
                    field_type="text",
                    default_value="lon",
                    placeholder="lon or position.longitude",
                    help_text="Dot-notation path to longitude in the message JSON",
                    row_group="field_row_1",
                ),
                PluginConfigField(
                    name="uid_field",
                    label="UID Field",
                    field_type="text",
                    default_value="uid",
                    placeholder="uid or device.id",
                    help_text="Dot-notation path to device UID in the message JSON",
                    row_group="field_row_2",
                ),
                PluginConfigField(
                    name="callsign_field",
                    label="Callsign Field",
                    field_type="text",
                    default_value="callsign",
                    placeholder="callsign or device.name",
                    help_text="Dot-notation path to callsign (UID used as fallback)",
                    row_group="field_row_2",
                ),
                PluginConfigField(
                    name="speed_field",
                    label="Speed Field",
                    field_type="text",
                    placeholder="speed (optional)",
                    help_text="Dot-notation path to speed in the message JSON",
                    row_group="field_row_3",
                ),
                PluginConfigField(
                    name="course_field",
                    label="Course Field",
                    field_type="text",
                    placeholder="course (optional)",
                    help_text="Dot-notation path to course/heading in the message JSON",
                    row_group="field_row_3",
                ),
                PluginConfigField(
                    name="remarks_field",
                    label="Remarks Field",
                    field_type="text",
                    placeholder="status (optional)",
                    help_text=(
                        "Dot-notation path to a field whose value is included "
                        "as remarks on the CoT marker"
                    ),
                ),
                # CoT output
                PluginConfigField(
                    name="cot_type",
                    label="CoT Type",
                    field_type="text",
                    default_value="a-f-G-U-C",
                    help_text="CoT type assigned to converted messages",
                    row_group="cot_row_1",
                ),
                PluginConfigField(
                    name="cot_stale_time",
                    label="CoT Stale Time (seconds)",
                    field_type="number",
                    default_value=300,
                    min_value=10,
                    max_value=86400,
                    help_text=(
                        "How long the marker persists on the TAK map "
                        "without a fresh update"
                    ),
                    row_group="cot_row_1",
                ),
            ],
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        config = self.get_decrypted_config()
        transport = config.get("transport", "mqtt")
        if transport == "mqtt":
            await self._connect_mqtt(config)
        elif transport == "websocket":
            await self._connect_websocket(config)

    async def cleanup(self) -> None:
        if self._ws_reader_task:
            self._ws_reader_task.cancel()
            self._ws_reader_task = None

        if self._ws_connection:
            try:
                await self._ws_connection.close()
            except Exception:
                pass
            self._ws_connection = None
            self._ws_connected = False

        if self._ws_session:
            try:
                await self._ws_session.close()
            except Exception:
                pass
            self._ws_session = None

        if self._mqtt_client:
            try:
                self._mqtt_client.loop_stop()
                self._mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_client = None
            self._mqtt_connected = False

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------

    async def _connect_mqtt(self, config: dict) -> None:
        import paho.mqtt.client as paho_mqtt

        self._loop = asyncio.get_event_loop()
        url = config.get("source_url", "")
        host, port, use_tls = self._parse_url(url)
        client_id = config.get("mqtt_client_id", "trakbridge-inbound")
        keepalive = int(config.get("mqtt_keepalive", 60))
        subscribe_topic = config.get("mqtt_subscribe_topic", "")
        qos = int(config.get("mqtt_qos", 0))

        client = paho_mqtt.Client(client_id=client_id or None)

        username = config.get("mqtt_username", "")
        password = config.get("mqtt_password", "")
        if username:
            client.username_pw_set(username, password)

        if use_tls:
            client.tls_set()

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                self._mqtt_connected = True
                logger.info(
                    f"InboundActive MQTT connected to {host}:{port}"
                )
                if subscribe_topic:
                    client.subscribe(subscribe_topic, qos=qos)
                    logger.info(
                        f"InboundActive subscribed to {subscribe_topic}"
                    )
                else:
                    logger.warning("InboundActive: no subscribe topic configured")
            else:
                logger.error(
                    f"InboundActive MQTT connection failed (rc={rc})"
                )

        def on_disconnect(client, userdata, rc):
            self._mqtt_connected = False
            if rc != 0:
                logger.warning(
                    f"InboundActive MQTT disconnected (rc={rc}), will reconnect"
                )

        def on_message(client, userdata, msg):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_message(msg.payload), self._loop
                )
            except Exception as e:
                logger.error(f"InboundActive MQTT message error: {e}")

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.reconnect_delay_set(min_delay=1, max_delay=60)

        try:
            client.connect(host, port, keepalive=keepalive)
            client.loop_start()
            self._mqtt_client = client
        except Exception as e:
            logger.error(f"InboundActive MQTT connect failed: {e}")

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def _connect_websocket(self, config: dict) -> None:
        url = config.get("source_url", "")
        try:
            session = aiohttp.ClientSession()
            self._ws_session = session
            self._ws_connection = await session.ws_connect(url)
            self._ws_connected = True
            self._ws_reader_task = asyncio.create_task(
                self._ws_reader_loop()
            )
            logger.info(f"InboundActive WebSocket connected to {url}")
        except Exception as e:
            logger.error(f"InboundActive WebSocket connect failed: {e}")
            self._ws_connected = False

    async def _ws_reader_loop(self) -> None:
        backoff = 1.0
        max_backoff = 60.0
        config = self.get_decrypted_config()
        url = config.get("source_url", "")

        while True:
            try:
                if not self._ws_connected or not self._ws_connection:
                    await asyncio.sleep(min(backoff, max_backoff))
                    backoff = min(backoff * 2, max_backoff)
                    try:
                        if self._ws_session and not self._ws_session.closed:
                            await self._ws_session.close()
                        self._ws_session = aiohttp.ClientSession()
                        self._ws_connection = await self._ws_session.ws_connect(url)
                        self._ws_connected = True
                        backoff = 1.0
                        logger.info(
                            f"InboundActive WebSocket reconnected to {url}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"InboundActive WebSocket reconnect failed: {e}"
                        )
                    continue

                msg = await self._ws_connection.receive()

                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data.encode("utf-8"))
                    backoff = 1.0
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_message(msg.data)
                    backoff = 1.0
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.ERROR,
                ):
                    self._ws_connected = False
                    logger.warning("InboundActive WebSocket closed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"InboundActive WebSocket reader error: {e}")
                self._ws_connected = False
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _resolve_path(self, data: dict, path: str):
        current = data
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return None
            current = current[segment]
        return current

    async def _handle_message(self, raw: bytes) -> None:
        try:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning("InboundActive: failed to parse JSON message")
                self._messages_failed += 1
                return

            config = self.get_decrypted_config()

            lat = self._resolve_path(data, config.get("lat_field", "lat"))
            lon = self._resolve_path(data, config.get("lon_field", "lon"))
            uid = self._resolve_path(data, config.get("uid_field", "uid"))

            if lat is None or lon is None or uid is None:
                logger.debug(
                    "InboundActive: missing required fields (lat/lon/uid)"
                )
                self._messages_failed += 1
                return

            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (ValueError, TypeError):
                logger.warning("InboundActive: non-numeric lat/lon")
                self._messages_failed += 1
                return

            if lat_f < -90 or lat_f > 90 or lon_f < -180 or lon_f > 180:
                logger.warning(
                    f"InboundActive: coordinates out of range "
                    f"(lat={lat_f}, lon={lon_f})"
                )
                self._messages_failed += 1
                return

            callsign_field = config.get("callsign_field", "callsign")
            location = {
                "lat": lat_f,
                "lon": lon_f,
                "uid": str(uid),
                "callsign": str(
                    self._resolve_path(data, callsign_field) or uid
                ),
                "cot_type": config.get("cot_type", "a-f-G-U-C"),
                "cot_stale_time": int(config.get("cot_stale_time", 300)),
            }

            speed_field = config.get("speed_field", "")
            if speed_field:
                speed = self._resolve_path(data, speed_field)
                if speed is not None:
                    location["speed"] = speed

            course_field = config.get("course_field", "")
            if course_field:
                course = self._resolve_path(data, course_field)
                if course is not None:
                    location["course"] = course

            remarks_field = config.get("remarks_field", "")
            if remarks_field:
                remarks = self._resolve_path(data, remarks_field)
                if remarks is not None:
                    location["description"] = str(remarks)

            self._messages_received += 1

            if not self.stream:
                logger.warning(
                    "InboundActive: no stream context, cannot process"
                )
                return

            from services.inbound_cot_service import InboundCOTService

            service = InboundCOTService()
            result = await service.process_inbound_locations(
                [location],
                self.stream,
                cot_type=config.get("cot_type"),
                cot_stale_time=int(config.get("cot_stale_time")) if config.get("cot_stale_time") is not None else None,
            )

            if result.get("success"):
                logger.debug(
                    f"InboundActive: processed "
                    f"{result.get('events_created', 0)} events"
                )
            else:
                logger.warning(
                    f"InboundActive processing failed: {result.get('error')}"
                )
                self._messages_failed += 1

        except Exception as e:
            logger.error(f"InboundActive message handler error: {e}")
            self._messages_failed += 1

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    def _parse_url(self, url: str):
        """Parse mqtt:// mqtts:// ws:// wss:// into (host, port, use_tls)."""
        use_tls = url.startswith(("mqtts://", "wss://"))
        stripped = url
        for prefix in ("mqtts://", "mqtt://", "wss://", "ws://"):
            stripped = stripped.replace(prefix, "")
            if stripped != url:
                break
        if ":" in stripped:
            host, port_str = stripped.split(":", 1)
            port = int(port_str.split("/")[0])
        else:
            host = stripped.split("/")[0]
            port = 8883 if use_tls else 1883
        return host, port, use_tls

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health_stats(self) -> Dict[str, Any]:
        config = self.get_decrypted_config()
        transport = config.get("transport", "mqtt")
        stats = {
            "transport": transport,
            "messages_received": self._messages_received,
            "messages_failed": self._messages_failed,
        }
        if transport == "mqtt":
            stats["connected"] = self._mqtt_connected
        elif transport == "websocket":
            stats["connected"] = self._ws_connected
        return stats

    async def test_connection(self) -> Dict[str, Any]:
        config = self.get_decrypted_config()
        url = config.get("source_url", "")
        transport = config.get("transport", "mqtt")

        if not url:
            return {"success": False, "error": "Missing source URL"}

        return {
            "success": True,
            "message": (
                f"Configuration valid for {transport} active inbound"
            ),
        }
