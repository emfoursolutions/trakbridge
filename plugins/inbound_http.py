# ABOUTME: HTTP push inbound plugin — receives JSON payloads via POST and maps
# ABOUTME: configurable dot-notation fields to standard location dicts for CoT.

import json
from datetime import datetime
from typing import Any, Dict, List

from plugins.base_plugin import BaseInboundPlugin, PluginConfigField
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

# Sentinel for "field not found" — distinguishes missing from None/falsy values
_MISSING = object()


def _resolve_path(data: dict, path: str) -> Any:
    """Resolve a dot-notation path against a nested dict."""
    current = data
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


class InboundHTTP(BaseInboundPlugin):
    """
    Inbound plugin for receiving JSON location data via HTTP POST.

    External devices POST to /api/inbound/<stream_id>/data. This plugin
    parses the payload and maps configurable dot-notation fields to the
    standard location dict format for CoT generation.
    """

    PLUGIN_NAME = "inbound_http"

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Inbound HTTP",
            "description": (
                "Receive JSON location data via HTTP POST. "
                "External devices push position data to a TrakBridge endpoint."
            ),
            "icon": "fas fa-arrow-circle-down",
            "category": "inbound",
            "inbound_transport": "http",
            "accepted_content_types": ["application/json"],
            "help_sections": [
                {
                    "title": "Overview",
                    "content": [
                        "External devices POST JSON to the stream's "
                        "endpoint URL",
                        "Supports single JSON objects and arrays of objects",
                        "Use dot-notation for nested fields "
                        "(e.g. position.latitude)",
                        "Set items_path to extract arrays from a "
                        "wrapper object",
                        "An API key is required — use the Bearer token "
                        "in Authorization header",
                    ],
                },
                {
                    "title": "Field Mapping",
                    "content": [
                        "lat_field / lon_field: paths to latitude and "
                        "longitude (required)",
                        "uid_field: path to a unique device identifier",
                        "callsign_field: path to the device display name "
                        "/ callsign",
                        "timestamp_field, speed_field, course_field: "
                        "optional telemetry",
                        "All fields support dot-notation (e.g. data.gps.lat)",
                    ],
                },
                {
                    "title": "CoT Output",
                    "content": [
                        "cot_type: CoT type assigned to converted locations",
                        "cot_stale_time: seconds before the marker expires "
                        "on the TAK map",
                        "Both can be overridden per-device if cot_type "
                        "is in the payload",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="items_path",
                    label="Items Path",
                    field_type="text",
                    required=False,
                    default_value="",
                    placeholder="data.devices",
                    help_text=(
                        "Dot-notation path to the array of items within "
                        "the payload. Leave empty if the root is the array "
                        "or a single object."
                    ),
                ),
                PluginConfigField(
                    name="lat_field",
                    label="Latitude Field",
                    field_type="text",
                    required=True,
                    default_value="lat",
                    help_text=(
                        "Dot-notation path to latitude "
                        "(e.g. position.latitude)"
                    ),
                    row_group="field_row_1",
                ),
                PluginConfigField(
                    name="lon_field",
                    label="Longitude Field",
                    field_type="text",
                    required=True,
                    default_value="lon",
                    help_text=(
                        "Dot-notation path to longitude "
                        "(e.g. position.longitude)"
                    ),
                    row_group="field_row_1",
                ),
                PluginConfigField(
                    name="uid_field",
                    label="UID Field",
                    field_type="text",
                    required=True,
                    default_value="uid",
                    help_text="Dot-notation path to unique device identifier",
                    row_group="field_row_2",
                ),
                PluginConfigField(
                    name="callsign_field",
                    label="Callsign / Name Field",
                    field_type="text",
                    required=True,
                    default_value="callsign",
                    help_text=(
                        "Dot-notation path to device display name / callsign"
                    ),
                    row_group="field_row_2",
                ),
                PluginConfigField(
                    name="timestamp_field",
                    label="Timestamp Field",
                    field_type="text",
                    required=False,
                    default_value="",
                    placeholder="timestamp (optional)",
                    help_text=(
                        "Dot-notation path to ISO-8601 timestamp (optional)"
                    ),
                    row_group="field_row_3",
                ),
                PluginConfigField(
                    name="speed_field",
                    label="Speed Field",
                    field_type="text",
                    required=False,
                    default_value="",
                    placeholder="speed (optional)",
                    help_text="Dot-notation path to speed in m/s (optional)",
                    row_group="field_row_3",
                ),
                PluginConfigField(
                    name="course_field",
                    label="Course / Heading Field",
                    field_type="text",
                    required=False,
                    default_value="",
                    placeholder="course (optional)",
                    help_text=(
                        "Dot-notation path to heading in degrees (optional)"
                    ),
                    row_group="field_row_3",
                ),
                PluginConfigField(
                    name="cot_type",
                    label="CoT Type",
                    field_type="text",
                    default_value="a-f-G-U-C",
                    help_text="CoT type assigned to converted locations",
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
                # HTTP endpoint settings
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="api_key",
                    sensitive=True,
                    required=False,
                    default_value="",
                    help_text=(
                        "Bearer token for authenticating inbound requests. "
                        "Click Generate to create a new random key."
                    ),
                ),
                PluginConfigField(
                    name="preview_mode",
                    label="Preview Mode",
                    field_type="checkbox",
                    required=False,
                    default_value=True,
                    help_text=(
                        "Accept and transform payloads without forwarding "
                        "to TAK servers. The transformed result is returned "
                        "in the HTTP response so you can verify field "
                        "mapping. Turn off to deliver to TAK."
                    ),
                ),
                PluginConfigField(
                    name="rate_limit",
                    label="Rate Limit (requests/min)",
                    field_type="number",
                    required=False,
                    default_value=60,
                    min_value=1,
                    max_value=10000,
                    help_text="Maximum inbound requests per minute",
                ),
                PluginConfigField(
                    name="ip_allowlist",
                    label="IP Allowlist (optional)",
                    field_type="textarea",
                    required=False,
                    default_value="",
                    placeholder='["10.0.0.0/8", "192.168.1.0/24"]',
                    help_text=(
                        "JSON list of allowed CIDR ranges. "
                        "Leave empty to allow all IPs."
                    ),
                ),
            ],
        }

    # ------------------------------------------------------------------
    # Payload transformation
    # ------------------------------------------------------------------

    def transform_payload(
        self,
        raw_body: bytes,
        content_type: str,
        headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Parse JSON body and map configured fields to location dicts."""
        config = self.get_decrypted_config()

        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON payload: {exc}") from exc

        if data is None:
            raise ValueError("Invalid JSON payload: received null")

        items = self._extract_items(data, config.get("items_path", ""))
        if not items:
            raise ValueError("No locations found in payload")

        return [
            self._map_item(item, config, idx)
            for idx, item in enumerate(items)
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_items(self, data: Any, items_path: str) -> List[dict]:
        if items_path:
            resolved = _resolve_path(data, items_path)
            if resolved is _MISSING:
                raise ValueError(
                    f"items_path '{items_path}' not found in payload"
                )
            data = resolved

        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise ValueError(
            f"Expected JSON object or array, got {type(data).__name__}"
        )

    def _map_item(
        self, item: dict, config: Dict[str, Any], index: int
    ) -> Dict[str, Any]:
        lat_field = config.get("lat_field", "lat")
        lon_field = config.get("lon_field", "lon")
        uid_field = config.get("uid_field", "uid")
        callsign_field = config.get("callsign_field", "callsign")

        raw_lat = _resolve_path(item, lat_field)
        if raw_lat is _MISSING:
            raise ValueError(
                f"Required field '{lat_field}' (lat) not found in item {index}"
            )
        raw_lon = _resolve_path(item, lon_field)
        if raw_lon is _MISSING:
            raise ValueError(
                f"Required field '{lon_field}' (lon) not found in item "
                f"{index}"
            )

        try:
            lat = float(raw_lat)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Cannot convert lat '{raw_lat}' to float in item {index}"
            ) from exc
        try:
            lon = float(raw_lon)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Cannot convert lon '{raw_lon}' to float in item {index}"
            ) from exc

        raw_uid = _resolve_path(item, uid_field)
        uid = str(raw_uid) if raw_uid is not _MISSING else f"unknown-{index}"

        raw_name = _resolve_path(item, callsign_field)
        name = str(raw_name) if raw_name is not _MISSING else uid

        location: Dict[str, Any] = {
            "uid": uid,
            "name": name,
            "lat": lat,
            "lon": lon,
            "cot_type": config.get("cot_type", "a-f-G-U-C"),
            "cot_stale_time": int(config.get("cot_stale_time", 300)),
        }

        self._set_optional(
            location, "timestamp", item,
            config.get("timestamp_field", ""),
            converter=self._parse_timestamp,
        )
        self._set_optional(
            location, "speed", item,
            config.get("speed_field", ""),
            converter=float,
        )
        self._set_optional(
            location, "course", item,
            config.get("course_field", ""),
            converter=float,
        )

        return location

    @staticmethod
    def _set_optional(
        location: dict,
        key: str,
        item: dict,
        field_path: str,
        converter=None,
    ) -> None:
        if not field_path:
            return
        raw = _resolve_path(item, field_path)
        if raw is _MISSING:
            return
        if converter is not None:
            try:
                raw = converter(raw)
            except Exception:
                logger.debug(
                    f"Could not convert optional field '{field_path}': {raw}"
                )
                return
        location[key] = raw

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        ts_str = str(value)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
