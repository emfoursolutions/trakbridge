# ABOUTME: Unit tests for services/output_plugin_helpers.py
# ABOUTME: Covers every public symbol: extract, format, filter, geofence, payload, dedup, rate.

import base64
import json
import time

# ---------------------------------------------------------------------------
# Helper XML strings
# ---------------------------------------------------------------------------

FULL_COT_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<event version="2.0" uid="ANDROID-12345" type="a-f-G-U-C"
       time="2024-01-01T00:00:00Z" start="2024-01-01T00:00:00Z"
       stale="2024-01-01T00:05:00Z" how="m-g">
  <point lat="-33.8688" lon="151.2093" hae="42.0" ce="9999999" le="9999999"/>
  <detail>
    <contact callsign="ALPHA-1" xmppUsername="alpha@tak.mil"/>
    <remarks>On patrol</remarks>
    <__group name="Cyan" role="Team Member"/>
    <status battery="87"/>
    <takv device="Samsung S21" platform="ATAK-CIV" os="31" version="4.8.0.0"/>
    <track speed="1.5" course="270.0"/>
  </detail>
</event>"""

MINIMAL_COT_XML = b"""<event version="2.0" uid="UNIT-001" type="a-h-G"
       time="2024-06-01T12:00:00Z" start="2024-06-01T12:00:00Z"
       stale="2024-06-01T12:05:00Z" how="m-g">
  <point lat="0.0" lon="0.0" hae="0.0" ce="9999999" le="9999999"/>
</event>"""

MALFORMED_XML = b"<not valid xml"


# ---------------------------------------------------------------------------
# extract_cot_variables
# ---------------------------------------------------------------------------


class TestExtractCotVariables:
    def test_full_cot_returns_all_fields(self):
        from services.output_plugin_helpers import extract_cot_variables

        result = extract_cot_variables(FULL_COT_XML)

        assert result["uid"] == "ANDROID-12345"
        assert result["type"] == "a-f-G-U-C"
        assert result["time"] == "2024-01-01T00:00:00Z"
        assert result["stale"] == "2024-01-01T00:05:00Z"
        assert result["lat"] == "-33.8688"
        assert result["lon"] == "151.2093"
        assert result["hae"] == "42.0"
        assert result["callsign"] == "ALPHA-1"
        assert result["xmpp_username"] == "alpha@tak.mil"
        assert result["remarks"] == "On patrol"
        assert result["group_name"] == "Cyan"
        assert result["group_role"] == "Team Member"
        assert result["battery"] == "87"
        assert result["device"] == "Samsung S21"
        assert result["platform"] == "ATAK-CIV"
        assert result["os"] == "31"
        assert result["version"] == "4.8.0.0"
        assert result["speed"] == "1.5"
        assert result["course"] == "270.0"

    def test_mgrs_computed_for_valid_coords(self):
        from services.output_plugin_helpers import extract_cot_variables

        result = extract_cot_variables(FULL_COT_XML)
        # MGRS should be a non-empty string when lat/lon are valid
        assert isinstance(result["mgrs"], str)
        assert len(result["mgrs"]) > 0

    def test_minimal_cot_returns_sensible_defaults(self):
        from services.output_plugin_helpers import extract_cot_variables

        result = extract_cot_variables(MINIMAL_COT_XML)

        assert result["uid"] == "UNIT-001"
        assert result["callsign"] == "Unknown"
        assert result["remarks"] == ""
        assert result["group_name"] == ""
        assert result["battery"] == ""
        assert result["speed"] == ""

    def test_malformed_xml_returns_empty_dict_or_defaults(self):
        from services.output_plugin_helpers import extract_cot_variables

        # Should not raise — return a safe default dict or empty dict
        result = extract_cot_variables(MALFORMED_XML)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# format_message
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_substitutes_all_variables(self):
        from services.output_plugin_helpers import format_message

        template = "{callsign} at {lat},{lon}"
        variables = {"callsign": "BRAVO-2", "lat": "1.0", "lon": "2.0"}
        result = format_message(template, variables)
        assert result == "BRAVO-2 at 1.0,2.0"

    def test_missing_variable_does_not_crash(self):
        from services.output_plugin_helpers import format_message

        template = "{callsign} at {lat}"
        variables = {"callsign": "X"}  # lat is missing
        result = format_message(template, variables)
        # Should not raise; result is a string
        assert isinstance(result, str)

    def test_empty_template_returns_empty_string(self):
        from services.output_plugin_helpers import format_message

        result = format_message("", {"callsign": "X"})
        assert result == ""

    def test_non_string_values_coerced(self):
        from services.output_plugin_helpers import format_message

        template = "speed={speed}"
        variables = {"speed": 1.5}
        # Should work via format() natural coercion
        result = format_message(template, variables)
        assert "1.5" in result


# ---------------------------------------------------------------------------
# matches_cot_pattern
# ---------------------------------------------------------------------------


class TestMatchesCotPattern:
    def test_exact_match(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-f-G-U-C", "a-f-G-U-C") is True

    def test_wildcard_prefix_match(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-f-G-U-C", "a-f-*") is True

    def test_wildcard_star_matches_all(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-h-G", "*") is True

    def test_mismatch_returns_false(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-h-G", "a-f-*") is False

    def test_exact_mismatch_returns_false(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-h-G", "a-f-G-U-C") is False

    def test_empty_pattern_no_match(self):
        from services.output_plugin_helpers import matches_cot_pattern

        assert matches_cot_pattern("a-f-G", "") is False


# ---------------------------------------------------------------------------
# is_within_geofence
# ---------------------------------------------------------------------------


class TestIsWithinGeofence:
    BOUNDS = {"north": 10.0, "south": -10.0, "east": 10.0, "west": -10.0}

    def test_point_inside_bbox(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(5.0, 5.0, self.BOUNDS) is True

    def test_point_on_north_edge(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(10.0, 0.0, self.BOUNDS) is True

    def test_point_outside_north(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(10.1, 0.0, self.BOUNDS) is False

    def test_point_outside_south(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(-10.1, 0.0, self.BOUNDS) is False

    def test_point_outside_east(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(0.0, 10.1, self.BOUNDS) is False

    def test_point_outside_west(self):
        from services.output_plugin_helpers import is_within_geofence

        assert is_within_geofence(0.0, -10.1, self.BOUNDS) is False

    def test_empty_geofence_dict_defaults_to_globe(self):
        from services.output_plugin_helpers import is_within_geofence

        # Empty dict → defaults to the full globe range; valid coords pass
        assert is_within_geofence(0.0, 0.0, {}) is True
        assert is_within_geofence(-33.8, 151.2, {}) is True

    def test_malformed_geofence_fails_open(self):
        from services.output_plugin_helpers import is_within_geofence

        # Non-numeric values → fail open (return True)
        assert is_within_geofence(
            5.0,
            5.0,
            {"north": "bad", "south": -10.0, "east": 10.0, "west": -10.0},
        ) is True


# ---------------------------------------------------------------------------
# should_handle
# ---------------------------------------------------------------------------


class TestShouldHandle:
    def _make_cot(
        self,
        uid="TEST-1",
        cot_type="a-f-G-U-C",
        lat="-33.0",
        lon="151.0",
    ):
        return (
            f'<event uid="{uid}" type="{cot_type}" '
            f'time="2024-01-01T00:00:00Z" stale="2024-01-01T00:05:00Z">'
            f'<point lat="{lat}" lon="{lon}" hae="0" ce="9999999" le="9999999"/>'
            f"</event>"
        ).encode()

    def test_no_filters_no_message_rules_returns_false(self):
        from services.output_plugin_helpers import should_handle

        ok, tpl = should_handle(self._make_cot(), "", {}, [])
        assert ok is False

    def test_uid_filter_match_passes(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {
                "enabled": True,
                "cot_type_pattern": "a-f-*",
                "format_template": "",
            }
        ]
        ok, tpl = should_handle(
            self._make_cot(uid="ANDROID-99"), "ANDROID-.*", {}, rules
        )
        assert ok is True

    def test_uid_filter_non_match_drops(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {
                "enabled": True,
                "cot_type_pattern": "a-f-*",
                "format_template": "",
            }
        ]
        ok, _ = should_handle(
            self._make_cot(uid="OTHER-99"), "ANDROID-.*", {}, rules
        )
        assert ok is False

    def test_geofence_in_passes(self):
        from services.output_plugin_helpers import should_handle

        geofence = {
            "enabled": True,
            "bounds": {
                "north": 0.0,
                "south": -90.0,
                "east": 180.0,
                "west": 0.0,
            },
        }
        rules = [
            {"enabled": True, "cot_type_pattern": "*", "format_template": "t"}
        ]
        ok, _ = should_handle(
            self._make_cot(lat="-33.0", lon="151.0"), "", geofence, rules
        )
        assert ok is True

    def test_geofence_out_drops(self):
        from services.output_plugin_helpers import should_handle

        geofence = {
            "enabled": True,
            "bounds": {
                "north": 0.0,
                "south": -10.0,
                "east": 10.0,
                "west": 0.0,
            },
        }
        rules = [
            {"enabled": True, "cot_type_pattern": "*", "format_template": "t"}
        ]
        ok, _ = should_handle(
            self._make_cot(lat="50.0", lon="5.0"), "", geofence, rules
        )
        assert ok is False

    def test_first_matching_rule_wins(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {
                "enabled": True,
                "cot_type_pattern": "a-f-*",
                "format_template": "first",
            },
            {
                "enabled": True,
                "cot_type_pattern": "*",
                "format_template": "second",
            },
        ]
        ok, tpl = should_handle(
            self._make_cot(cot_type="a-f-G-U-C"), "", {}, rules
        )
        assert ok is True
        assert tpl == "first"

    def test_no_matching_rules_returns_false(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {
                "enabled": True,
                "cot_type_pattern": "a-h-*",
                "format_template": "x",
            }
        ]
        ok, _ = should_handle(
            self._make_cot(cot_type="a-f-G-U-C"), "", {}, rules
        )
        assert ok is False

    def test_disabled_rule_skipped(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {
                "enabled": False,
                "cot_type_pattern": "*",
                "format_template": "skip",
            },
        ]
        ok, _ = should_handle(self._make_cot(), "", {}, rules)
        assert ok is False

    def test_invalid_uid_filter_regex_drops(self):
        from services.output_plugin_helpers import should_handle

        rules = [
            {"enabled": True, "cot_type_pattern": "*", "format_template": ""}
        ]
        # Invalid regex should cause uid filter to drop the message
        ok, _ = should_handle(
            self._make_cot(uid="TEST-1"), "[invalid", {}, rules
        )
        assert ok is False


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def _vars(self):
        return {
            "uid": "X-1",
            "type": "a-f-G-U-C",
            "time": "2024-01-01T00:00:00Z",
            "stale": "2024-01-01T00:05:00Z",
            "callsign": "CHARLIE-3",
            "lat": "-33.0",
            "lon": "151.0",
            "hae": "10.0",
            "mgrs": "55HBU1234567890",
            "speed": "2.0",
            "course": "180.0",
            "group_name": "Blue",
            "group_role": "Team Lead",
            "device": "Pixel 7",
            "platform": "ATAK-CIV",
            "os": "33",
            "version": "4.9.0.0",
            "battery": "72",
            "remarks": "All clear",
            "xmpp_username": "",
        }

    def test_json_format_returns_valid_json(self):
        from services.output_plugin_helpers import build_payload

        result = build_payload(self._vars(), "json", "", False, b"")
        parsed = json.loads(result)
        assert parsed["source"] == "trakbridge"
        assert parsed["contact"]["callsign"] == "CHARLIE-3"

    def test_xml_format_returns_raw_xml(self):
        from services.output_plugin_helpers import build_payload

        raw = b"<event/>"
        result = build_payload(self._vars(), "xml", "", False, raw)
        assert result == raw

    def test_custom_template_applies_template(self):
        from services.output_plugin_helpers import build_payload

        result = build_payload(
            self._vars(), "custom_template", "{callsign} at {lat}", False, b""
        )
        assert result == "CHARLIE-3 at -33.0"

    def test_include_raw_xml_adds_base64_in_json(self):
        from services.output_plugin_helpers import build_payload

        raw = b"<event/>"
        result = build_payload(self._vars(), "json", "", True, raw)
        parsed = json.loads(result)
        assert "raw_xml" in parsed
        decoded = base64.b64decode(parsed["raw_xml"])
        assert decoded == raw

    def test_json_without_raw_xml_excludes_field(self):
        from services.output_plugin_helpers import build_payload

        result = build_payload(self._vars(), "json", "", False, b"")
        parsed = json.loads(result)
        assert "raw_xml" not in parsed


# ---------------------------------------------------------------------------
# parse_custom_headers
# ---------------------------------------------------------------------------


class TestParseCustomHeaders:
    def test_multiple_lines_parsed(self):
        from services.output_plugin_helpers import parse_custom_headers

        raw = "X-Token: abc123\nContent-Type: application/json"
        result = parse_custom_headers(raw)
        assert result["X-Token"] == "abc123"
        assert result["Content-Type"] == "application/json"

    def test_blank_lines_ignored(self):
        from services.output_plugin_helpers import parse_custom_headers

        raw = "\nX-Api-Key: secret\n\n"
        result = parse_custom_headers(raw)
        assert "X-Api-Key" in result
        assert len(result) == 1

    def test_malformed_lines_skipped(self):
        from services.output_plugin_helpers import parse_custom_headers

        # Lines without ':' should be skipped
        raw = "NotAHeader\nX-Good: value"
        result = parse_custom_headers(raw)
        assert "NotAHeader" not in result
        assert result.get("X-Good") == "value"

    def test_whitespace_trimmed(self):
        from services.output_plugin_helpers import parse_custom_headers

        raw = "  X-Custom :  trimmed  "
        result = parse_custom_headers(raw)
        assert result.get("X-Custom") == "trimmed"

    def test_empty_string_returns_empty_dict(self):
        from services.output_plugin_helpers import parse_custom_headers

        assert parse_custom_headers("") == {}

    def test_none_returns_empty_dict(self):
        from services.output_plugin_helpers import parse_custom_headers

        assert parse_custom_headers(None) == {}

    def test_value_with_colon_preserved(self):
        from services.output_plugin_helpers import parse_custom_headers

        raw = "Authorization: Bearer tok:en"
        result = parse_custom_headers(raw)
        assert result["Authorization"] == "Bearer tok:en"


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------


class TestDeduplicator:
    def test_first_key_is_new(self):
        from services.output_plugin_helpers import Deduplicator

        d = Deduplicator(ttl_seconds=60)
        assert d.check("uid:type") is True  # new → True

    def test_repeated_key_within_ttl_is_dup(self):
        from services.output_plugin_helpers import Deduplicator

        d = Deduplicator(ttl_seconds=60)
        d.check("uid:type")
        assert d.check("uid:type") is False  # dup → False

    def test_key_after_ttl_is_new(self, monkeypatch):
        from unittest.mock import patch

        from services.output_plugin_helpers import Deduplicator

        with patch("services.output_plugin_helpers.time") as mock_time:
            # t=0.0: first check (key added), t=1.0: explicit prune, t=1.0: second check (TTL=0.5s expired)
            mock_time.time.side_effect = [0.0, 1.0, 1.0]
            d = Deduplicator(ttl_seconds=0.5)
            d.check("uid:type")
            d.prune()
            assert d.check("uid:type") is True

    def test_prune_removes_expired_entries(self, monkeypatch):
        from unittest.mock import patch

        from services.output_plugin_helpers import Deduplicator

        with patch("services.output_plugin_helpers.time") as mock_time:
            # t=0.0: check key1, t=0.0: check key2, t=1.0: prune, t=1.0: re-check key1, t=1.0: re-check key2
            mock_time.time.side_effect = [0.0, 0.0, 1.0, 1.0, 1.0]
            d = Deduplicator(ttl_seconds=0.5)
            d.check("key1")
            d.check("key2")
            d.prune()
            # After prune, both keys should be gone so they appear new
            assert d.check("key1") is True
            assert d.check("key2") is True

    def test_different_keys_are_independent(self):
        from services.output_plugin_helpers import Deduplicator

        d = Deduplicator(ttl_seconds=60)
        assert d.check("key-A") is True
        assert d.check("key-B") is True  # Different key — still new


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_none_rate_is_unlimited(self):
        from services.output_plugin_helpers import RateLimiter

        rl = RateLimiter(max_rate_per_sec=None)
        for _ in range(100):
            assert rl.check() is True

    def test_zero_rate_is_unlimited(self):
        from services.output_plugin_helpers import RateLimiter

        rl = RateLimiter(max_rate_per_sec=0)
        for _ in range(100):
            assert rl.check() is True

    def test_positive_rate_allows_first_then_blocks(self):
        from services.output_plugin_helpers import RateLimiter

        rl = RateLimiter(max_rate_per_sec=1.0)
        # First call is always allowed
        assert rl.check() is True
        # Immediate second call should be blocked
        assert rl.check() is False

    def test_allows_again_after_interval(self):
        """Use clock mock to verify rate-limit reset without sleeping."""
        from unittest.mock import patch

        from services.output_plugin_helpers import RateLimiter

        with patch("services.output_plugin_helpers.time") as mock_time:
            # t=0.0: first check (allowed), t=0.005: second check (blocked, < 10ms),
            # t=0.015: third check (allowed, > 10ms)
            mock_time.time.side_effect = [0.0, 0.005, 0.015]
            rl = RateLimiter(max_rate_per_sec=100.0)  # min_interval = 10ms
            assert rl.check() is True
            assert rl.check() is False  # Too fast
            assert rl.check() is True   # Interval elapsed

    def test_rate_limiter_with_clock_mock(self):
        """Use time mock to verify rate gate without sleeping."""
        from unittest.mock import patch

        from services.output_plugin_helpers import RateLimiter

        with patch("services.output_plugin_helpers.time") as mock_time:
            # Simulate: t=0.0 (init), t=0.0 (check1), t=0.3 (check2 blocked),
            # t=1.1 (check3 allowed)
            mock_time.time.side_effect = [0.0, 0.3, 1.1]

            rl = RateLimiter(max_rate_per_sec=2.0)  # min_interval = 0.5s
            # First call: _last_event_time is 0.0, so 0.0 >= 0.5 is False
            # but initial state triggers first-call path
            assert rl.check() is True   # t=0.0, allowed (first call)
            assert rl.check() is False  # t=0.3, 0.3 < 0.5, blocked
            assert rl.check() is True   # t=1.1, 1.1 >= 0.5, allowed
