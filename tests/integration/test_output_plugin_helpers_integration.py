# ABOUTME: Integration tests for services/output_plugin_helpers.py
# ABOUTME: Exercises the full filter pipeline end-to-end with realistic CoT samples.

import base64
import json

import pytest

# ---------------------------------------------------------------------------
# Realistic CoT XML samples
# ---------------------------------------------------------------------------

FRIENDLY_COT = b"""<?xml version="1.0" encoding="utf-8"?>
<event version="2.0" uid="ANDROID-ALPHA-1" type="a-f-G-U-C"
       time="2024-06-15T08:30:00Z" start="2024-06-15T08:30:00Z"
       stale="2024-06-15T08:35:00Z" how="m-g">
  <point lat="-33.8688" lon="151.2093" hae="15.0" ce="9999999" le="9999999"/>
  <detail>
    <contact callsign="ALPHA-1" xmppUsername="alpha1@tak.example.mil"/>
    <remarks>Patrol sector 4</remarks>
    <__group name="Red" role="Team Member"/>
    <status battery="76"/>
    <takv device="Samsung Galaxy S22" platform="ATAK-CIV" os="31" version="4.8.1.0"/>
    <track speed="1.2" course="045.0"/>
  </detail>
</event>"""

HOSTILE_COT = b"""<?xml version="1.0" encoding="utf-8"?>
<event version="2.0" uid="SENSOR-H-99" type="a-h-G"
       time="2024-06-15T08:31:00Z" start="2024-06-15T08:31:00Z"
       stale="2024-06-15T08:36:00Z" how="m-g">
  <point lat="-33.9000" lon="151.1500" hae="10.0" ce="9999999" le="9999999"/>
  <detail>
    <contact callsign="HOSTILE-99"/>
    <remarks/>
    <__group name="Magenta" role="HQ"/>
  </detail>
</event>"""

OUTSIDE_GEOFENCE_COT = b"""<?xml version="1.0" encoding="utf-8"?>
<event version="2.0" uid="REMOTE-UNIT" type="a-f-G-U-C"
       time="2024-06-15T08:32:00Z" start="2024-06-15T08:32:00Z"
       stale="2024-06-15T08:37:00Z" how="m-g">
  <point lat="51.5074" lon="-0.1278" hae="20.0" ce="9999999" le="9999999"/>
  <detail>
    <contact callsign="LONDON-1"/>
    <__group name="Blue" role="Team Member"/>
  </detail>
</event>"""


# ---------------------------------------------------------------------------
# Geofence covering the Sydney, Australia area
# ---------------------------------------------------------------------------

SYDNEY_GEOFENCE = {
    "enabled": True,
    "bounds": {
        "north": -33.5,
        "south": -34.2,
        "east": 151.5,
        "west": 150.9,
    },
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def friendly_rules():
    """Message rules that match friendly ground units."""
    return [
        {
            "enabled": True,
            "cot_type_pattern": "a-f-*",
            "format_template": "{callsign} FRIENDLY",
            "uid_filter": "",
        }
    ]


@pytest.fixture
def multi_rules():
    """Message rules matching both friendly and hostile units."""
    return [
        {
            "enabled": True,
            "cot_type_pattern": "a-f-*",
            "format_template": "{callsign} [FRIENDLY]",
        },
        {
            "enabled": True,
            "cot_type_pattern": "a-h-*",
            "format_template": "{callsign} [HOSTILE]",
        },
    ]


# ---------------------------------------------------------------------------
# Integration: full filter pipeline
# ---------------------------------------------------------------------------


class TestFilterPipelineIntegration:
    def test_friendly_passes_all_filters(self, friendly_rules):
        from services.output_plugin_helpers import should_handle

        ok, tpl = should_handle(FRIENDLY_COT, "", SYDNEY_GEOFENCE, friendly_rules)
        assert ok is True
        assert tpl == "{callsign} FRIENDLY"

    def test_outside_geofence_dropped(self, friendly_rules):
        from services.output_plugin_helpers import should_handle

        ok, _ = should_handle(OUTSIDE_GEOFENCE_COT, "", SYDNEY_GEOFENCE, friendly_rules)
        assert ok is False

    def test_hostile_not_matched_by_friendly_rules(self, friendly_rules):
        from services.output_plugin_helpers import should_handle

        ok, _ = should_handle(HOSTILE_COT, "", SYDNEY_GEOFENCE, friendly_rules)
        assert ok is False

    def test_uid_filter_restricts_to_android_prefix(self, multi_rules):
        from services.output_plugin_helpers import should_handle

        ok, _ = should_handle(FRIENDLY_COT, "ANDROID-.*", SYDNEY_GEOFENCE, multi_rules)
        assert ok is True

    def test_uid_filter_drops_non_android(self, multi_rules):
        from services.output_plugin_helpers import should_handle

        ok, _ = should_handle(HOSTILE_COT, "ANDROID-.*", {}, multi_rules)
        assert ok is False


# ---------------------------------------------------------------------------
# Integration: extract → should_handle → build_payload round-trip (JSON)
# ---------------------------------------------------------------------------


class TestExtractHandlePayloadRoundTrip:
    def test_friendly_json_payload_shape(self, friendly_rules):
        from services.output_plugin_helpers import (
            extract_cot_variables,
            should_handle,
            build_payload,
        )

        ok, _ = should_handle(FRIENDLY_COT, "", SYDNEY_GEOFENCE, friendly_rules)
        assert ok is True

        variables = extract_cot_variables(FRIENDLY_COT)
        payload_str = build_payload(variables, "json", "", False, FRIENDLY_COT)
        payload = json.loads(payload_str)

        assert payload["source"] == "trakbridge"
        assert payload["contact"]["callsign"] == "ALPHA-1"
        assert payload["position"]["lat"] == "-33.8688"
        assert payload["cot"]["uid"] == "ANDROID-ALPHA-1"
        assert payload["group"]["name"] == "Red"
        assert payload["device"]["platform"] == "ATAK-CIV"

    def test_xml_passthrough_payload(self, friendly_rules):
        from services.output_plugin_helpers import (
            extract_cot_variables,
            should_handle,
            build_payload,
        )

        ok, _ = should_handle(FRIENDLY_COT, "", SYDNEY_GEOFENCE, friendly_rules)
        assert ok is True

        variables = extract_cot_variables(FRIENDLY_COT)
        result = build_payload(variables, "xml", "", False, FRIENDLY_COT)
        assert result == FRIENDLY_COT

    def test_raw_xml_base64_included(self, friendly_rules):
        from services.output_plugin_helpers import (
            extract_cot_variables,
            build_payload,
        )

        variables = extract_cot_variables(FRIENDLY_COT)
        payload_str = build_payload(variables, "json", "", True, FRIENDLY_COT)
        payload = json.loads(payload_str)

        assert "raw_xml" in payload
        decoded = base64.b64decode(payload["raw_xml"])
        assert decoded == FRIENDLY_COT


# ---------------------------------------------------------------------------
# Integration: format_message round-trip for custom_template path
# ---------------------------------------------------------------------------


class TestCustomTemplateRoundTrip:
    def test_custom_template_with_real_variables(self):
        from services.output_plugin_helpers import (
            extract_cot_variables,
            format_message,
            build_payload,
        )

        variables = extract_cot_variables(FRIENDLY_COT)
        template = "Unit {callsign} at {lat},{lon} — group {group_name}"

        # Via format_message directly
        direct = format_message(template, variables)
        assert direct == "Unit ALPHA-1 at -33.8688,151.2093 — group Red"

        # Via build_payload with custom_template format
        via_payload = build_payload(variables, "custom_template", template, False, b"")
        assert via_payload == direct

    def test_multi_rule_template_selection(self, multi_rules):
        from services.output_plugin_helpers import (
            extract_cot_variables,
            should_handle,
            format_message,
        )

        ok, tpl = should_handle(HOSTILE_COT, "", {}, multi_rules)
        assert ok is True
        assert tpl == "{callsign} [HOSTILE]"

        variables = extract_cot_variables(HOSTILE_COT)
        msg = format_message(tpl, variables)
        assert msg == "HOSTILE-99 [HOSTILE]"
