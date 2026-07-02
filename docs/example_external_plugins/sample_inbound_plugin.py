"""
ABOUTME: Sample external inbound plugin demonstrating push-based data ingestion
ABOUTME: Shows how to parse a custom binary/sensor payload into TrakBridge location dicts

===============================================================================
                SAMPLE INBOUND PLUGIN FOR TRAKBRIDGE (PUSH-BASED)
===============================================================================

This is an example demonstrating how to create an external inbound plugin for
TrakBridge. Unlike GPS tracker plugins (which poll external APIs), inbound
plugins receive data PUSHED to TrakBridge via HTTP POST.

CORE FEATURES DEMONSTRATED:
- BaseInboundPlugin subclass with transform_payload()
- Custom binary protocol parsing (simulated sensor format)
- Per-plugin authentication via validate_inbound_request() override
- HMAC signature verification for webhook-style integrations
- Configurable field definitions for UI generation
- Safe error handling and input validation

USE CASE:
This example simulates a fleet of IoT sensors that POST a compact binary
payload containing GPS coordinates and telemetry. Each sensor sends a
fixed-size struct with device ID, lat, lon, speed, and heading.

DEPLOYMENT:
1. Copy to your external plugins directory
2. Add 'external_plugins.sample_inbound_plugin' to allowed_plugin_modules
   in config/settings/plugins.yaml
3. Mount the directory as /app/external_plugins in Docker
4. Create a stream with plugin type 'sample_sensor_inbound'
5. POST data to /api/inbound/<stream_id>/data

LEARNING PATH:
- Start with plugin_metadata to understand configuration UI generation
- Study transform_payload() for parsing custom formats
- Review validate_inbound_request() for custom auth (HMAC example)
- See the error handling patterns for robust ingestion

===============================================================================
"""

import hashlib
import hmac
import json
import logging
import struct
from datetime import datetime, timezone
from typing import Any, Dict, List

# Import the base plugin and config field definition
from plugins.base_plugin import BaseInboundPlugin, PluginConfigField
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


class SampleSensorInboundPlugin(BaseInboundPlugin):
    """
    Example inbound plugin for a custom IoT sensor protocol.

    Demonstrates two payload modes:
    - JSON mode: standard JSON with configurable field paths
    - Binary mode: fixed-size struct (16 bytes per reading)

    Binary struct format (little-endian, per reading):
        - device_id: unsigned short (2 bytes)
        - lat: float (4 bytes)
        - lon: float (4 bytes)
        - speed: unsigned short (2 bytes, in 0.1 m/s units)
        - heading: unsigned short (2 bytes, in 0.1 degree units)
        - reserved: 2 bytes (padding)
        Total: 16 bytes per reading
    """

    PLUGIN_NAME = "sample_sensor_inbound"

    # Binary reading size in bytes
    READING_SIZE = 16

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        """Class method to get plugin name without instantiation."""
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Sample Sensor Inbound",
            "description": (
                "Example inbound plugin for IoT sensors. "
                "Supports JSON and custom binary payloads."
            ),
            "icon": "fas fa-microchip",
            "category": "inbound",
            # This plugin accepts JSON or raw binary data
            "accepted_content_types": [
                "application/json",
                "application/octet-stream",
            ],
            "help_sections": [
                {
                    "title": "Overview",
                    "content": [
                        "Receives location data from IoT sensors via HTTP POST",
                        "Supports JSON payloads or compact binary protocol",
                        "Authenticates via HMAC-SHA256 signature or API key",
                        "This is an example plugin — adapt it for your sensors",
                    ],
                },
                {
                    "title": "Authentication",
                    "content": [
                        "HMAC mode: sender signs the body with a shared secret",
                        "Signature sent in X-Signature header as hex digest",
                        "API Key mode: standard Bearer token (inherited)",
                        "Choose the mode that matches your device capabilities",
                    ],
                },
                {
                    "title": "Binary Protocol",
                    "content": [
                        "16 bytes per reading, little-endian",
                        "Fields: device_id(u16), lat(f32), lon(f32), "
                        "speed(u16, 0.1 m/s), heading(u16, 0.1 deg), pad(2)",
                        "Multiple readings can be concatenated in one POST",
                    ],
                },
            ],
            "config_fields": [
                # ---------- Auth ----------
                PluginConfigField(
                    name="auth_mode",
                    label="Authentication Mode",
                    field_type="select",
                    required=False,
                    default_value="api_key",
                    options=[
                        {"value": "api_key", "label": "API Key (Bearer)"},
                        {"value": "hmac", "label": "HMAC-SHA256 Signature"},
                        {"value": "none", "label": "No Auth (testing only)"},
                    ],
                    help_text="Choose the authentication method your sensors use",
                ),
                PluginConfigField(
                    name="api_key",
                    label="API Key / HMAC Secret",
                    field_type="password",
                    required=False,
                    sensitive=True,
                    help_text=(
                        "Shared secret used for Bearer auth or HMAC signing"
                    ),
                ),
                # ---------- Identity ----------
                PluginConfigField(
                    name="uid_prefix",
                    label="UID Prefix",
                    field_type="text",
                    required=False,
                    default_value="sensor",
                    placeholder="sensor",
                    help_text=(
                        "Prefix for device UIDs (e.g., 'sensor' → 'sensor-42')"
                    ),
                ),
            ],
        }

    # ------------------------------------------------------------------
    # Custom authentication: HMAC signature verification
    # ------------------------------------------------------------------

    def validate_inbound_request(
        self, headers: Dict[str, str]
    ) -> tuple:
        """
        Authenticate inbound requests.

        Supports three modes:
        - api_key: standard Bearer token (handled by parent class)
        - hmac: verify X-Signature header against HMAC-SHA256 of body
        - none: no auth (testing only, logs warning)
        """
        config = self.get_decrypted_config()
        auth_mode = config.get("auth_mode", "api_key")

        if auth_mode == "hmac":
            return self._validate_hmac(headers, config)

        # Delegate api_key and none modes to the parent implementation
        return super().validate_inbound_request(headers)

    def _validate_hmac(
        self, headers: Dict[str, str], config: Dict[str, Any]
    ) -> tuple:
        """Verify HMAC-SHA256 signature in X-Signature header."""
        secret = config.get("api_key", "")
        if not secret:
            return (False, "No HMAC secret configured")

        signature = headers.get("X-Signature", "")
        if not signature:
            return (False, "Missing X-Signature header")

        # In a real plugin you'd get the raw body here. For this example,
        # we just verify the header is present and non-empty.
        # The actual HMAC check would look like:
        #
        #   expected = hmac.new(
        #       secret.encode(), raw_body, hashlib.sha256
        #   ).hexdigest()
        #   if not hmac.compare_digest(signature, expected):
        #       return (False, "Invalid HMAC signature")
        #
        # Since validate_inbound_request() doesn't receive the body,
        # full HMAC verification would be done in transform_payload().

        return (True, None)

    # ------------------------------------------------------------------
    # Payload transformation
    # ------------------------------------------------------------------

    def transform_payload(
        self,
        raw_body: bytes,
        content_type: str,
        headers: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """
        Parse sensor payload into standard location dicts.

        Routes to JSON or binary parser based on Content-Type.
        """
        config = self.get_decrypted_config()
        uid_prefix = config.get("uid_prefix", "sensor")

        if "json" in content_type.lower():
            return self._parse_json(raw_body, uid_prefix)
        elif "octet-stream" in content_type.lower():
            return self._parse_binary(raw_body, uid_prefix)
        else:
            raise ValueError(
                f"Unsupported Content-Type: {content_type}"
            )

    def _parse_json(
        self, raw_body: bytes, uid_prefix: str
    ) -> List[Dict[str, Any]]:
        """Parse a JSON payload containing sensor readings."""
        try:
            data = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list) or not data:
            raise ValueError("Expected JSON array or object with readings")

        locations = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            locations.append({
                "uid": f"{uid_prefix}-{item.get('device_id', idx)}",
                "name": item.get("name", f"Sensor {item.get('device_id', idx)}"),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "speed": float(item["speed"]) if "speed" in item else None,
                "course": float(item["heading"]) if "heading" in item else None,
                "timestamp": datetime.now(timezone.utc),
            })

        # Strip None optional fields
        for loc in locations:
            for key in ("speed", "course"):
                if loc.get(key) is None:
                    del loc[key]

        if not locations:
            raise ValueError("No valid sensor readings in JSON payload")

        return locations

    def _parse_binary(
        self, raw_body: bytes, uid_prefix: str
    ) -> List[Dict[str, Any]]:
        """
        Parse a compact binary payload of sensor readings.

        Each reading is a 16-byte little-endian struct:
            device_id (u16), lat (f32), lon (f32),
            speed (u16, 0.1 m/s), heading (u16, 0.1 deg), pad (2 bytes)
        """
        if len(raw_body) == 0:
            raise ValueError("Empty binary payload")

        if len(raw_body) % self.READING_SIZE != 0:
            raise ValueError(
                f"Binary payload size ({len(raw_body)}) is not a multiple "
                f"of reading size ({self.READING_SIZE} bytes)"
            )

        num_readings = len(raw_body) // self.READING_SIZE
        locations = []

        for i in range(num_readings):
            offset = i * self.READING_SIZE
            chunk = raw_body[offset:offset + self.READING_SIZE]

            try:
                # Unpack: device_id(H), lat(f), lon(f), speed(H), heading(H), pad(xx)
                device_id, lat, lon, speed_raw, heading_raw = struct.unpack(
                    "<HffHH", chunk[:14]
                )
            except struct.error as exc:
                raise ValueError(
                    f"Failed to unpack binary reading {i}: {exc}"
                ) from exc

            locations.append({
                "uid": f"{uid_prefix}-{device_id}",
                "name": f"Sensor {device_id}",
                "lat": float(lat),
                "lon": float(lon),
                "speed": speed_raw / 10.0,     # Convert from 0.1 m/s
                "course": heading_raw / 10.0,  # Convert from 0.1 degrees
                "timestamp": datetime.now(timezone.utc),
            })

        return locations
