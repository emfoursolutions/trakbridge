# ABOUTME: Outbound HTTP plugin — POSTs or PUTs CoT events to an HTTP endpoint
# ABOUTME: as JSON, raw XML, or a rendered custom template via aiohttp.

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

from plugins.base_plugin import (
    BaseOutputPlugin,
    PluginConfigField,
    PluginCustomComponent,
)
from services.output_plugin_helpers import (
    Deduplicator,
    build_payload,
    extract_cot_variables,
    parse_custom_headers,
    should_handle,
)

logger = logging.getLogger(__name__)

# Allowed URL schemes for HTTP delivery.
_ALLOWED_HTTP_SCHEMES = {"http", "https"}


class OutboundHTTP(BaseOutputPlugin):
    """
    Outbound plugin that forwards CoT events to an HTTP endpoint.

    Supports POST and PUT, with JSON, raw XML, or custom template output.
    Applies UID filter, geofence, message rules, and optional deduplication
    before sending.  HTTP failures are logged and counted; they never raise
    so upstream processing is unaffected.
    """

    PLUGIN_NAME = "outbound_http"

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._events_sent: int = 0
        self._events_dropped: int = 0
        self._last_error: Optional[str] = None

        # Deduplicator is created lazily in handle_cot_message based on config,
        # but initialise a default here so the object is always consistent.
        self._deduplicator: Optional[Deduplicator] = None
        self._dedup_ttl: Optional[int] = None

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
            "display_name": "Outbound HTTP",
            "description": (
                "Forward CoT events to an HTTP endpoint via POST or PUT. "
                "Supports JSON, raw XML, and custom template output formats."
            ),
            "icon": "fas fa-paper-plane",
            "category": "forwarding",
            "config_fields": [
                PluginConfigField(
                    name="endpoint_url",
                    label="Endpoint URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    placeholder="https://example.com/webhook",
                    help_text="URL to POST/PUT CoT events to. HTTPS recommended.",
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
                    help_text="HTTP method used to deliver events.",
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
                    help_text="Format of the payload sent to the endpoint.",
                ),
                PluginConfigField(
                    name="custom_template",
                    label="Custom Template",
                    field_type="text",
                    placeholder="ALERT: {callsign} at {lat},{lon}",
                    help_text=(
                        "Template string using {variable} syntax. "
                        "Only used when output_format is 'custom_template'."
                    ),
                    depends_on={"output_format": "custom_template"},
                ),
                PluginConfigField(
                    name="custom_headers",
                    label="Custom Headers",
                    field_type="textarea",
                    placeholder="X-Api-Key: secret\nAuthorization: Bearer token",
                    sensitive=True,
                    help_text="Newline-separated 'Header-Name: value' lines.",
                ),
                PluginConfigField(
                    name="timeout_seconds",
                    label="Timeout (seconds)",
                    field_type="number",
                    default_value=10,
                    min_value=1,
                    max_value=60,
                    help_text="HTTP request timeout in seconds.",
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="Global UID Filter (regex)",
                    field_type="text",
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
                    name="dedup_enabled",
                    label="Deduplication",
                    field_type="checkbox",
                    default_value="true",
                    help_text=(
                        "Suppress duplicate UID+type events within the TTL window."
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
    # Lifecycle — no persistent connections, so these are no-ops
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """No-op: HTTP plugin creates a fresh session per request."""

    async def cleanup(self) -> None:
        """No-op: HTTP plugin creates a fresh session per request."""

    # ------------------------------------------------------------------
    # Core message handler
    # ------------------------------------------------------------------

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Process one CoT event through the filter → dedup → build → send pipeline.

        tak_server_id is used for internal routing only and must not appear in
        the outbound payload.
        """
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
        dedup_enabled = str(config.get("dedup_enabled", "true")).lower() == "true"
        if dedup_enabled:
            dedup_ttl = int(config.get("dedup_ttl_seconds", 5))
            # Re-create deduplicator if TTL changed, or lazily initialise.
            # Cache the TTL locally to avoid reaching into Deduplicator internals.
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

        # 3. Build payload
        output_format = config.get("output_format", "json")
        custom_template = config.get("custom_template", "") or ""
        include_raw_xml = str(config.get("include_raw_xml", "false")).lower() == "true"

        variables = extract_cot_variables(cot_xml)
        payload = build_payload(variables, output_format, custom_template, include_raw_xml, cot_xml)

        # 4. Send
        await self._send(payload, output_format, config)

    async def _send(self, payload, output_format: str, config: dict) -> None:
        """Send payload to the configured HTTP endpoint.

        On any failure (non-2xx, network error, timeout) the error is logged
        and counted; it is never re-raised so upstream processing continues.
        """
        url = config.get("endpoint_url", "")
        method = str(config.get("http_method", "POST")).upper()
        timeout_sec = int(config.get("timeout_seconds", 10))
        headers = parse_custom_headers(config.get("custom_headers", "") or "")

        # Validate scheme before making any network call.
        parsed_scheme = urlparse(url).scheme.lower() if url else ""
        if parsed_scheme not in _ALLOWED_HTTP_SCHEMES:
            error_msg = (
                f"endpoint_url has unsupported scheme '{parsed_scheme}'; "
                f"expected http:// or https://"
            )
            logger.error("outbound_http: %s", error_msg)
            self._last_error = error_msg
            self._events_dropped += 1
            return

        # Determine Content-Type and request kwargs based on payload type
        if isinstance(payload, bytes):
            # Raw XML passthrough
            headers.setdefault("Content-Type", "application/xml")
            request_kwargs = {
                "data": payload,
                "headers": headers,
                "timeout": aiohttp.ClientTimeout(total=timeout_sec),
            }
        elif isinstance(payload, str) and output_format != "json":
            # Custom template rendered to a string
            headers.setdefault("Content-Type", "text/plain")
            request_kwargs = {
                "data": payload,
                "headers": headers,
                "timeout": aiohttp.ClientTimeout(total=timeout_sec),
            }
        else:
            # JSON: payload is a JSON string from build_payload; parse back to dict
            # so aiohttp can serialise it properly with correct Content-Type.
            import json as _json
            headers.setdefault("Content-Type", "application/json")
            try:
                json_body = _json.loads(payload)
            except Exception:
                json_body = {"raw": payload}
            request_kwargs = {
                "json": json_body,
                "headers": headers,
                "timeout": aiohttp.ClientTimeout(total=timeout_sec),
            }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **request_kwargs) as resp:
                    if resp.status >= 400:
                        error_msg = (
                            f"HTTP {method} to {url} returned {resp.status}"
                        )
                        logger.warning("outbound_http: %s", error_msg)
                        self._last_error = error_msg
                        self._events_dropped += 1
                    else:
                        self._events_sent += 1
        except Exception as exc:
            error_msg = f"HTTP delivery failed: {exc}"
            logger.error("outbound_http: %s", error_msg)
            self._last_error = error_msg
            self._events_dropped += 1

    # ------------------------------------------------------------------
    # Health reporting
    # ------------------------------------------------------------------

    def get_health_stats(self) -> dict:
        """Return counters for monitoring and UI display."""
        return {
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "last_error": self._last_error,
        }
