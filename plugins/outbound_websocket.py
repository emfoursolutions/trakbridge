# ABOUTME: Outbound WebSocket plugin — streams CoT events to a WebSocket endpoint.
# ABOUTME: Maintains a persistent aiohttp connection with reconnect backoff, bounded queue, and rate limiter.

import asyncio
import logging
from typing import Any, Dict, Optional, Union
from urllib.parse import urlparse, urlunparse

import aiohttp

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
    parse_custom_headers,
    should_handle,
)

logger = logging.getLogger(__name__)

# Maximum reconnect sleep in seconds — caps exponential backoff growth.
_MAX_BACKOFF = 30.0

# Allowed URL schemes for WebSocket connections.
_ALLOWED_WS_SCHEMES = {"ws", "wss"}


def _redact_url(url: str) -> str:
    """Return the URL with any userinfo (username:password) stripped from netloc.

    Preserves host, port, path, query, and fragment so log messages remain
    useful while keeping credentials out of log files.
    """
    try:
        parsed = urlparse(url)
        # Rebuild netloc as host only (with optional port), dropping userinfo.
        host = parsed.hostname or ""
        port = parsed.port
        netloc = f"{host}:{port}" if port else host
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        # If parsing fails, return a safe placeholder rather than the raw URL.
        return "<url-parse-error>"


class OutboundWebSocket(BaseOutputPlugin):
    """
    Outbound plugin that streams CoT events to a WebSocket endpoint.

    Maintains a persistent aiohttp WebSocket connection. Incoming events pass
    through the filter → dedup → rate-limit pipeline and are placed on a
    bounded queue. A background writer task drains the queue and sends via the
    WebSocket. On disconnect, the writer retries with exponential backoff
    (1 → 2 → 4 → … → 30 s). The queue stays bounded throughout — when full,
    the oldest item is dropped (oldest-drop semantics).
    """

    PLUGIN_NAME = "outbound_websocket"

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._events_sent: int = 0
        self._events_dropped: int = 0
        self._last_error: Optional[str] = None
        self._connected: bool = False

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._writer_task: Optional[asyncio.Task] = None
        # Reader task drains incoming WS frames so server-side CLOSE is detected.
        self._reader_task: Optional[asyncio.Task] = None
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
            "display_name": "Outbound WebSocket",
            "description": (
                "Stream CoT events to a WebSocket endpoint. "
                "Supports JSON, raw XML, and custom template output formats. "
                "Maintains a persistent connection with automatic reconnect and a bounded send queue."
            ),
            "icon": "fas fa-plug",
            "category": "forwarding",
            "config_fields": [
                PluginConfigField(
                    name="endpoint_url",
                    label="Endpoint URL",
                    field_type="url",
                    required=True,
                    placeholder="ws://example.com/ws",
                    help_text="WebSocket endpoint URL. Use wss:// for TLS.",
                ),
                PluginConfigField(
                    name="custom_headers",
                    label="Custom Headers",
                    field_type="textarea",
                    default_value="",
                    placeholder="X-Api-Key: secret\nAuthorization: Bearer token",
                    sensitive=True,
                    help_text="Newline-separated 'Header-Name: value' lines sent during the WebSocket handshake.",
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
                    help_text="Format of the payload sent over the WebSocket.",
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
                    help_text="WebSocket connection timeout in seconds.",
                ),
                PluginConfigField(
                    name="max_rate",
                    label="Max Rate (events/sec)",
                    field_type="number",
                    default_value="",
                    help_text=(
                        "Maximum events per second to send. "
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
                    help_text="Suppress duplicate UID+type events within the TTL window.",
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
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the WebSocket connection and start the background writer task."""
        config = self.config
        buffer_size = int(config.get("stream_buffer_size", 100))
        self._queue = asyncio.Queue(maxsize=buffer_size)

        max_rate_raw = config.get("max_rate", "") or ""
        max_rate = float(max_rate_raw) if max_rate_raw else None
        self._rate_limiter = RateLimiter(max_rate)

        await self._connect()

        # Writer task runs indefinitely; handles reconnect internally.
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def cleanup(self) -> None:
        """Stop background tasks and close the WebSocket connection and session."""
        for task in (self._writer_task, self._reader_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._writer_task = None
        self._reader_task = None

        await self._close_ws()

        if self._session:
            try:
                await self._session.close()
            except Exception as exc:
                logger.warning("outbound_websocket: error closing session: %s", exc)
            self._session = None

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

        # 5. Enqueue — if full, drop oldest and count it
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
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    async def _writer_loop(self) -> None:
        """Drain the queue and send each payload over the WebSocket.

        Reconnects with exponential backoff when disconnected. Every queue.get()
        is paired with queue.task_done() via try/finally so the queue's internal
        unfinished-task counter never drifts.

        The get() uses a 1-second timeout so the loop can proactively detect
        a server-side WS close even while the queue is idle.
        """
        backoff = 1.0

        while True:
            # Reconnect if needed before attempting to drain
            if not self._connected or self._ws is None or self._ws.closed:
                self._connected = False
                await self._connect()
                if not self._connected:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF)
                    continue
                backoff = 1.0  # Reset after successful connect

            # Use a short timeout so the loop can detect server-initiated
            # WS closes even when the queue is idle.
            try:
                payload = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                # No item within the window; loop back to check WS state.
                continue
            except asyncio.CancelledError:
                break

            try:
                try:
                    if isinstance(payload, bytes):
                        await self._ws.send_bytes(payload)
                    else:
                        await self._ws.send_str(payload)
                    self._events_sent += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error_msg = f"WebSocket send error: {exc}"
                    logger.error("outbound_websocket: %s", error_msg)
                    self._last_error = error_msg
                    self._connected = False
                    self._events_dropped += 1
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF)
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        """Attempt to open a WebSocket connection. Sets _connected on success.

        Also cancels any stale reader task and starts a fresh one so incoming
        frames (especially CLOSE) are processed and _connected is updated.
        """
        # Cancel any stale reader task from the previous connection.
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = None

        config = self.config
        url = config.get("endpoint_url", "")
        headers = parse_custom_headers(config.get("custom_headers", "") or "")
        timeout_sec = int(config.get("timeout_seconds", 10))

        # Validate scheme before making any network call.
        parsed_scheme = urlparse(url).scheme.lower() if url else ""
        if parsed_scheme not in _ALLOWED_WS_SCHEMES:
            error_msg = (
                f"WebSocket endpoint_url has unsupported scheme '{parsed_scheme}'; "
                f"expected ws:// or wss://"
            )
            logger.error("outbound_websocket: %s", error_msg)
            self._last_error = error_msg
            self._events_dropped += 1
            self._connected = False
            return

        redacted = _redact_url(url)
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            self._ws = await self._session.ws_connect(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_sec),
            )
            self._connected = True
            # Start the reader task to detect server-initiated CLOSE frames.
            self._reader_task = asyncio.create_task(self._reader_loop())
            logger.info("outbound_websocket: connected to %s", redacted)
        except Exception as exc:
            error_msg = f"WebSocket connection failed: {exc}"
            logger.error("outbound_websocket: %s at %s", error_msg, redacted)
            self._last_error = error_msg
            self._connected = False

    async def _reader_loop(self) -> None:
        """Drain incoming WS frames so server-side CLOSE is detected promptly.

        Sets _connected=False when the server closes or errors the connection,
        which allows the writer loop to trigger reconnect.
        """
        try:
            async for msg in self._ws:
                from aiohttp import WSMsgType
                if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR, WSMsgType.CLOSED):
                    logger.info(
                        "outbound_websocket: server closed connection (type=%s)", msg.type
                    )
                    self._connected = False
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("outbound_websocket: reader loop exited: %s", exc)
        finally:
            self._connected = False

    async def _close_ws(self) -> None:
        """Close the WebSocket connection if open."""
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.warning("outbound_websocket: error closing WebSocket: %s", exc)
        self._ws = None

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def get_health_stats(self) -> dict:
        """Return connection state and counters for monitoring and UI display."""
        return {
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "ws_connected": self._connected,
            "buffer_size": self._queue.qsize() if self._queue else 0,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    async def test_connection(self):
        """Attempt a brief connection to verify endpoint reachability.

        Returns a (success: bool, message: str) tuple.
        """
        url = self.config.get("endpoint_url", "")
        headers = parse_custom_headers(self.config.get("custom_headers", "") or "")
        timeout_sec = int(self.config.get("timeout_seconds", 10))

        session = aiohttp.ClientSession()
        try:
            ws = await session.ws_connect(
                url,
                headers=headers,
                timeout=aiohttp.ClientWSTimeout(ws_close=timeout_sec),
            )
            await ws.close()
            return (True, f"Connected to {url}")
        except Exception as exc:
            return (False, str(exc))
        finally:
            await session.close()
