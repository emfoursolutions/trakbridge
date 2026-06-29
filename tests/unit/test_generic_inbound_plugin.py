"""
ABOUTME: Unit tests for GenericInboundPlugin covering JSON field mapping,
ABOUTME: nested dot-notation paths, batch payloads, invalid JSON, and auth modes.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from plugins.generic_inbound_plugin import GenericInboundPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(overrides=None):
    """Create a GenericInboundPlugin with sensible test defaults."""
    config = {
        "lat_field": "lat",
        "lon_field": "lon",
        "uid_field": "id",
        "callsign_field": "name",
        "auth_mode": "api_key",
        "api_key": "test-key-123",
    }
    if overrides:
        config.update(overrides)
    plugin = GenericInboundPlugin(config)
    # Bypass encryption in tests
    with patch.object(plugin, "get_decrypted_config", return_value=config):
        pass  # config is already plain-text in tests
    return plugin


def _transform(plugin, payload, content_type="application/json"):
    """Shorthand for calling transform_payload with mocked decryption."""
    config = plugin.config.copy()
    with patch.object(plugin, "get_decrypted_config", return_value=config):
        return plugin.transform_payload(
            json.dumps(payload).encode() if not isinstance(payload, bytes) else payload,
            content_type,
            {},
        )


# ---------------------------------------------------------------------------
# Plugin identity & metadata
# ---------------------------------------------------------------------------


class TestPluginIdentity:
    """Verify plugin name, metadata, and category."""

    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "generic_json_inbound"

    def test_class_level_plugin_name(self):
        assert GenericInboundPlugin.get_plugin_name() == "generic_json_inbound"

    def test_category_is_inbound(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "inbound"

    def test_accepted_content_types(self):
        plugin = _make_plugin()
        assert "application/json" in plugin.get_accepted_content_types()

    def test_has_required_config_fields(self):
        plugin = _make_plugin()
        field_names = [f.name for f in plugin.get_config_fields()]
        for required in ("lat_field", "lon_field", "uid_field", "callsign_field"):
            assert required in field_names

    def test_api_key_is_sensitive(self):
        plugin = _make_plugin()
        sensitive = plugin.get_sensitive_fields()
        assert "api_key" in sensitive


# ---------------------------------------------------------------------------
# Single-object payloads
# ---------------------------------------------------------------------------


class TestSingleObjectPayload:
    """Transform a root-level JSON object into a single location."""

    def test_basic_flat_object(self):
        plugin = _make_plugin()
        result = _transform(plugin, {"id": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0})

        assert len(result) == 1
        loc = result[0]
        assert loc["uid"] == "dev-1"
        assert loc["name"] == "Alpha"
        assert loc["lat"] == 38.9
        assert loc["lon"] == -77.0

    def test_numeric_strings_coerced_to_float(self):
        plugin = _make_plugin()
        result = _transform(plugin, {"id": "dev-1", "name": "A", "lat": "38.9", "lon": "-77.0"})
        assert result[0]["lat"] == 38.9
        assert result[0]["lon"] == -77.0


# ---------------------------------------------------------------------------
# Array payloads
# ---------------------------------------------------------------------------


class TestArrayPayload:
    """Transform a JSON array into multiple locations."""

    def test_multiple_items(self):
        plugin = _make_plugin()
        payload = [
            {"id": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0},
            {"id": "dev-2", "name": "Bravo", "lat": 39.0, "lon": -76.5},
        ]
        result = _transform(plugin, payload)
        assert len(result) == 2
        assert result[0]["uid"] == "dev-1"
        assert result[1]["uid"] == "dev-2"

    def test_empty_array_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError, match="[Nn]o.*location"):
            _transform(plugin, [])


# ---------------------------------------------------------------------------
# Nested dot-notation field paths
# ---------------------------------------------------------------------------


class TestNestedFieldPaths:
    """Verify dot-notation resolution for deeply nested JSON."""

    def test_nested_lat_lon(self):
        plugin = _make_plugin({"lat_field": "position.latitude", "lon_field": "position.longitude"})
        payload = {
            "id": "dev-1",
            "name": "Alpha",
            "position": {"latitude": 40.7128, "longitude": -74.0060},
        }
        result = _transform(plugin, payload)
        assert result[0]["lat"] == 40.7128
        assert result[0]["lon"] == -74.0060

    def test_deeply_nested(self):
        plugin = _make_plugin({
            "lat_field": "data.gps.coords.lat",
            "lon_field": "data.gps.coords.lon",
        })
        payload = {
            "id": "x",
            "name": "X",
            "data": {"gps": {"coords": {"lat": 51.5074, "lon": -0.1278}}},
        }
        result = _transform(plugin, payload)
        assert result[0]["lat"] == 51.5074

    def test_missing_nested_path_raises(self):
        plugin = _make_plugin({"lat_field": "position.latitude"})
        payload = {"id": "dev-1", "name": "A", "lat": 38.9, "lon": -77.0}
        with pytest.raises(ValueError, match="lat"):
            _transform(plugin, payload)


# ---------------------------------------------------------------------------
# items_path — extract array from nested JSON
# ---------------------------------------------------------------------------


class TestItemsPath:
    """Verify items_path extracts the array from a nested location."""

    def test_items_path_extracts_nested_array(self):
        plugin = _make_plugin({"items_path": "data.devices"})
        payload = {
            "data": {
                "devices": [
                    {"id": "a", "name": "A", "lat": 1.0, "lon": 2.0},
                    {"id": "b", "name": "B", "lat": 3.0, "lon": 4.0},
                ]
            }
        }
        result = _transform(plugin, payload)
        assert len(result) == 2
        assert result[0]["uid"] == "a"

    def test_items_path_empty_string_uses_root(self):
        plugin = _make_plugin({"items_path": ""})
        payload = [{"id": "a", "name": "A", "lat": 1.0, "lon": 2.0}]
        result = _transform(plugin, payload)
        assert len(result) == 1

    def test_items_path_resolves_to_single_object(self):
        plugin = _make_plugin({"items_path": "device"})
        payload = {"device": {"id": "a", "name": "A", "lat": 1.0, "lon": 2.0}}
        result = _transform(plugin, payload)
        assert len(result) == 1
        assert result[0]["uid"] == "a"

    def test_items_path_not_found_raises(self):
        plugin = _make_plugin({"items_path": "nonexistent.path"})
        payload = {"data": []}
        with pytest.raises(ValueError, match="items_path"):
            _transform(plugin, payload)


# ---------------------------------------------------------------------------
# Optional fields (timestamp, speed, course, altitude)
# ---------------------------------------------------------------------------


class TestOptionalFields:
    """Verify optional field extraction."""

    def test_timestamp_extracted(self):
        plugin = _make_plugin({"timestamp_field": "ts"})
        payload = {"id": "d1", "name": "A", "lat": 1.0, "lon": 2.0, "ts": "2026-04-11T12:00:00Z"}
        result = _transform(plugin, payload)
        assert result[0].get("timestamp") is not None

    def test_speed_extracted(self):
        plugin = _make_plugin({"speed_field": "velocity"})
        payload = {"id": "d1", "name": "A", "lat": 1.0, "lon": 2.0, "velocity": 5.5}
        result = _transform(plugin, payload)
        assert result[0]["speed"] == 5.5

    def test_course_extracted(self):
        plugin = _make_plugin({"course_field": "heading"})
        payload = {"id": "d1", "name": "A", "lat": 1.0, "lon": 2.0, "heading": 180.0}
        result = _transform(plugin, payload)
        assert result[0]["course"] == 180.0

    def test_missing_optional_fields_are_absent(self):
        plugin = _make_plugin({"speed_field": "velocity"})
        payload = {"id": "d1", "name": "A", "lat": 1.0, "lon": 2.0}
        result = _transform(plugin, payload)
        assert "speed" not in result[0]

    def test_nested_optional_fields(self):
        plugin = _make_plugin({"speed_field": "telemetry.speed", "course_field": "telemetry.heading"})
        payload = {
            "id": "d1",
            "name": "A",
            "lat": 1.0,
            "lon": 2.0,
            "telemetry": {"speed": 10.0, "heading": 270.0},
        }
        result = _transform(plugin, payload)
        assert result[0]["speed"] == 10.0
        assert result[0]["course"] == 270.0


# ---------------------------------------------------------------------------
# Invalid / malformed JSON
# ---------------------------------------------------------------------------


class TestInvalidPayload:
    """Error handling for bad input."""

    def test_non_json_bytes_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError, match="[Ii]nvalid JSON"):
            _transform(plugin, b"not json at all")

    def test_non_numeric_lat_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError, match="lat"):
            _transform(plugin, {"id": "d1", "name": "A", "lat": "abc", "lon": 2.0})

    def test_null_payload_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError):
            _transform(plugin, b"null")


# ---------------------------------------------------------------------------
# Auth mode integration (inherits from BaseInboundPlugin)
# ---------------------------------------------------------------------------


class TestAuthModes:
    """Verify auth behaviour inherited from BaseInboundPlugin."""

    def test_api_key_auth_passes(self):
        plugin = _make_plugin()
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "test-key-123", "auth_mode": "api_key"
        }):
            ok, err = plugin.validate_inbound_request({"Authorization": "Bearer test-key-123"})
            assert ok is True

    def test_api_key_auth_rejects_wrong_key(self):
        plugin = _make_plugin()
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "test-key-123", "auth_mode": "api_key"
        }):
            ok, err = plugin.validate_inbound_request({"Authorization": "Bearer wrong"})
            assert ok is False

    def test_none_auth_passes(self):
        plugin = _make_plugin({"auth_mode": "none"})
        with patch.object(plugin, "get_decrypted_config", return_value={"auth_mode": "none"}):
            ok, err = plugin.validate_inbound_request({})
            assert ok is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Boundary and edge-case scenarios."""

    def test_large_batch(self):
        """100 items (the max per request) should process successfully."""
        plugin = _make_plugin()
        payload = [
            {"id": f"dev-{i}", "name": f"D{i}", "lat": float(i), "lon": float(-i)}
            for i in range(100)
        ]
        result = _transform(plugin, payload)
        assert len(result) == 100

    def test_uid_field_nested(self):
        plugin = _make_plugin({"uid_field": "device.serial"})
        payload = {"device": {"serial": "SN-123"}, "name": "A", "lat": 1.0, "lon": 2.0}
        result = _transform(plugin, payload)
        assert result[0]["uid"] == "SN-123"

    def test_extra_fields_ignored(self):
        """Unknown fields in the payload should not cause errors."""
        plugin = _make_plugin()
        payload = {"id": "d1", "name": "A", "lat": 1.0, "lon": 2.0, "battery": 85, "signal": "strong"}
        result = _transform(plugin, payload)
        assert len(result) == 1
        assert result[0]["uid"] == "d1"
