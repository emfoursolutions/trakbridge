# ABOUTME: Unit tests for the InboundHTTP plugin.
# ABOUTME: Covers metadata, transform_payload field mapping, array/object support, validation.

import json
from datetime import datetime, timezone

import pytest

from plugins.inbound_http import InboundHTTP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plugin(config: dict = None):
    return InboundHTTP(config or {})


def _base_config():
    return {
        "lat_field": "lat",
        "lon_field": "lon",
        "uid_field": "uid",
        "callsign_field": "callsign",
        "cot_type": "a-f-G-U-C",
        "cot_stale_time": 300,
    }


def _payload(**fields):
    return json.dumps(fields).encode()


# ===================================================================
# Metadata
# ===================================================================

class TestInboundHTTPMetadata:
    def test_plugin_name(self):
        assert _make_plugin().plugin_name == "inbound_http"

    def test_category_is_inbound(self):
        assert _make_plugin().plugin_metadata["category"] == "inbound"

    def test_has_display_name(self):
        assert "display_name" in _make_plugin().plugin_metadata

    def test_accepted_content_types(self):
        types = _make_plugin().plugin_metadata["accepted_content_types"]
        assert "application/json" in types

    def test_required_config_fields_present(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        for name in ("lat_field", "lon_field", "uid_field",
                     "callsign_field", "cot_type", "cot_stale_time"):
            assert name in names

    def test_optional_config_fields_present(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        for name in (
            "items_path", "timestamp_field", "speed_field", "course_field"
        ):
            assert name in names

    def test_http_endpoint_config_fields_present(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        names = [f.name for f in fields]
        for name in ("api_key", "rate_limit", "ip_allowlist", "preview_mode"):
            assert name in names

    def test_api_key_is_sensitive(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        api_key = next(f for f in fields if f.name == "api_key")
        assert api_key.sensitive is True

    def test_rate_limit_defaults_to_60(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        rate = next(f for f in fields if f.name == "rate_limit")
        assert rate.default_value == 60

    def test_preview_mode_defaults_to_true(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        preview = next(f for f in fields if f.name == "preview_mode")
        assert preview.default_value is True

    def test_ip_allowlist_is_textarea(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        allowlist = next(f for f in fields if f.name == "ip_allowlist")
        assert allowlist.field_type == "textarea"

    def test_inbound_transport_is_http(self):
        assert _make_plugin().plugin_metadata["inbound_transport"] == "http"

    def test_default_lat_field(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        lat = next(f for f in fields if f.name == "lat_field")
        assert lat.default_value == "lat"

    def test_default_cot_type(self):
        fields = _make_plugin().plugin_metadata["config_fields"]
        cot = next(f for f in fields if f.name == "cot_type")
        assert cot.default_value == "a-f-G-U-C"

    def test_class_method_get_plugin_name(self):
        assert InboundHTTP.get_plugin_name() == "inbound_http"

    def test_has_help_sections(self):
        sections = _make_plugin().plugin_metadata.get("help_sections", [])
        assert len(sections) >= 1


# ===================================================================
# transform_payload — single object
# ===================================================================

class TestTransformPayloadSingleObject:
    def _transform(self, config, body):
        plugin = _make_plugin(config)
        return plugin.transform_payload(body, "application/json", {})

    def test_basic_flat_object(self):
        body = _payload(lat=38.9, lon=-77.0, uid="dev-1", callsign="ALPHA")
        locs = self._transform(_base_config(), body)
        assert len(locs) == 1
        assert locs[0]["lat"] == 38.9
        assert locs[0]["lon"] == -77.0
        assert locs[0]["uid"] == "dev-1"
        assert locs[0]["name"] == "ALPHA"

    def test_cot_type_and_stale_in_location(self):
        body = _payload(lat=38.9, lon=-77.0, uid="dev-1", callsign="ALPHA")
        locs = self._transform(_base_config(), body)
        assert locs[0]["cot_type"] == "a-f-G-U-C"
        assert locs[0]["cot_stale_time"] == 300

    def test_nested_field_mapping(self):
        config = {
            **_base_config(),
            "lat_field": "position.latitude",
            "lon_field": "position.longitude",
            "uid_field": "device.id",
            "callsign_field": "device.name",
        }
        body = json.dumps({
            "position": {"latitude": 38.9, "longitude": -77.0},
            "device": {"id": "nested-dev", "name": "NestUnit"},
        }).encode()
        locs = self._transform(config, body)
        assert locs[0]["lat"] == 38.9
        assert locs[0]["uid"] == "nested-dev"
        assert locs[0]["name"] == "NestUnit"

    def test_uid_fallback_when_callsign_missing(self):
        body = _payload(lat=38.9, lon=-77.0, uid="dev-99")
        locs = self._transform(_base_config(), body)
        assert locs[0]["name"] == "dev-99"

    def test_uid_fallback_when_uid_missing(self):
        body = _payload(lat=38.9, lon=-77.0)
        locs = self._transform(_base_config(), body)
        assert locs[0]["uid"] == "unknown-0"

    def test_lat_as_string_is_converted(self):
        body = _payload(lat="38.9", lon="-77.0", uid="dev-1", callsign="A")
        locs = self._transform(_base_config(), body)
        assert locs[0]["lat"] == 38.9

    def test_speed_included_when_configured(self):
        config = {**_base_config(), "speed_field": "speed"}
        body = _payload(lat=38.9, lon=-77.0, uid="d", callsign="A", speed=5.5)
        locs = self._transform(config, body)
        assert locs[0]["speed"] == 5.5

    def test_course_included_when_configured(self):
        config = {**_base_config(), "course_field": "course"}
        body = _payload(lat=38.9, lon=-77.0, uid="d", callsign="A", course=90)
        locs = self._transform(config, body)
        assert locs[0]["course"] == 90.0

    def test_optional_fields_absent_when_not_configured(self):
        body = _payload(lat=38.9, lon=-77.0, uid="d", callsign="A",
                        speed=5.5, course=90)
        locs = self._transform(_base_config(), body)
        assert "speed" not in locs[0]
        assert "course" not in locs[0]

    def test_timestamp_parsed_from_iso_string(self):
        config = {**_base_config(), "timestamp_field": "ts"}
        body = _payload(lat=38.9, lon=-77.0, uid="d", callsign="A",
                        ts="2026-05-24T10:00:00Z")
        locs = self._transform(config, body)
        assert isinstance(locs[0]["timestamp"], datetime)


# ===================================================================
# transform_payload — array payloads
# ===================================================================

class TestTransformPayloadArray:
    def _transform(self, config, body):
        plugin = _make_plugin(config)
        return plugin.transform_payload(body, "application/json", {})

    def test_root_array_produces_multiple_locations(self):
        body = json.dumps([
            {"lat": 38.9, "lon": -77.0, "uid": "d1", "callsign": "A"},
            {"lat": 39.0, "lon": -76.0, "uid": "d2", "callsign": "B"},
        ]).encode()
        locs = self._transform(_base_config(), body)
        assert len(locs) == 2
        assert locs[0]["uid"] == "d1"
        assert locs[1]["uid"] == "d2"

    def test_items_path_extracts_nested_array(self):
        config = {**_base_config(), "items_path": "data.devices"}
        body = json.dumps({
            "data": {
                "devices": [
                    {"lat": 38.9, "lon": -77.0, "uid": "d1", "callsign": "A"},
                ]
            }
        }).encode()
        locs = self._transform(config, body)
        assert len(locs) == 1
        assert locs[0]["uid"] == "d1"


# ===================================================================
# transform_payload — validation errors
# ===================================================================

class TestTransformPayloadErrors:
    def _transform(self, config, body):
        plugin = _make_plugin(config)
        return plugin.transform_payload(body, "application/json", {})

    def test_invalid_json_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            self._transform(_base_config(), b"not json {{{")

    def test_null_json_raises_value_error(self):
        with pytest.raises(ValueError, match="null"):
            self._transform(_base_config(), b"null")

    def test_missing_lat_raises_value_error(self):
        body = _payload(lon=-77.0, uid="d", callsign="A")
        with pytest.raises(ValueError, match="lat"):
            self._transform(_base_config(), body)

    def test_missing_lon_raises_value_error(self):
        body = _payload(lat=38.9, uid="d", callsign="A")
        with pytest.raises(ValueError, match="lon"):
            self._transform(_base_config(), body)

    def test_non_numeric_lat_raises_value_error(self):
        body = _payload(lat="bad", lon=-77.0, uid="d", callsign="A")
        with pytest.raises(ValueError, match="lat"):
            self._transform(_base_config(), body)

    def test_bad_items_path_raises_value_error(self):
        config = {**_base_config(), "items_path": "missing.path"}
        body = _payload(lat=38.9, lon=-77.0, uid="d", callsign="A")
        with pytest.raises(ValueError, match="items_path"):
            self._transform(config, body)

    def test_empty_array_raises_value_error(self):
        with pytest.raises(ValueError, match="No locations"):
            self._transform(_base_config(), b"[]")


# ===================================================================
# Lifecycle — HTTP plugin is stateless (no-op start/cleanup)
# ===================================================================

class TestInboundHTTPLifecycle:
    @pytest.mark.asyncio
    async def test_start_is_noop(self):
        plugin = _make_plugin()
        await plugin.start()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        plugin = _make_plugin()
        await plugin.cleanup()  # Should not raise
