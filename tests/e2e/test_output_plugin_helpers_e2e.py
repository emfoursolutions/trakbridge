# ABOUTME: E2E tests for services/output_plugin_helpers.py
# ABOUTME: Simulates the full plugin orchestration sequence over a batch of CoT events.

import json

import pytest

# ---------------------------------------------------------------------------
# CoT event factory
# ---------------------------------------------------------------------------


def make_cot(uid, cot_type, lat, lon, callsign, group="Blue"):
    """Build a minimal but realistic CoT XML bytes for a given unit."""
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<event version="2.0" uid="{uid}" type="{cot_type}" '
        f'time="2024-06-15T10:00:00Z" start="2024-06-15T10:00:00Z" '
        f'stale="2024-06-15T10:05:00Z" how="m-g">'
        f'<point lat="{lat}" lon="{lon}" hae="10.0" ce="9999999" le="9999999"/>'
        f"<detail>"
        f'<contact callsign="{callsign}"/>'
        f'<__group name="{group}" role="Team Member"/>'
        f"</detail>"
        f"</event>"
    ).encode()


# ---------------------------------------------------------------------------
# Batch definition
# 20 events: mix of friendly/hostile, in/out geofence, duplicate UIDs
# ---------------------------------------------------------------------------

# Sydney bounding box
GEOFENCE = {
    "enabled": True,
    "bounds": {"north": -33.5, "south": -34.2, "east": 151.5, "west": 150.9},
}

MESSAGE_RULES = [
    {
        "enabled": True,
        "cot_type_pattern": "a-f-*",
        "format_template": "{callsign}:FRIENDLY",
    },
    {
        "enabled": True,
        "cot_type_pattern": "a-h-*",
        "format_template": "{callsign}:HOSTILE",
    },
]

# fmt: off
BATCH = [
    # (uid, cot_type, lat, lon, callsign, expected_pass, note)
    # 10 friendly units inside geofence
    ("UNIT-01", "a-f-G-U-C", "-33.87", "151.21", "ALPHA-1",   True,  "friendly in fence"),
    ("UNIT-02", "a-f-G-U-C", "-33.90", "151.15", "BRAVO-2",   True,  "friendly in fence"),
    ("UNIT-03", "a-f-G-U-C", "-33.95", "151.10", "CHARLIE-3", True,  "friendly in fence"),
    ("UNIT-04", "a-f-G-U-C", "-34.00", "151.20", "DELTA-4",   True,  "friendly in fence"),
    ("UNIT-05", "a-f-G-U-C", "-33.80", "151.30", "ECHO-5",    True,  "friendly in fence"),
    # 5 events outside geofence (London) — should be dropped
    ("UNIT-06", "a-f-G-U-C", "51.50",  "-0.13",  "LONDON-1",  False, "outside geofence"),
    ("UNIT-07", "a-f-G-U-C", "51.51",  "-0.12",  "LONDON-2",  False, "outside geofence"),
    ("UNIT-08", "a-f-G-U-C", "51.52",  "-0.11",  "LONDON-3",  False, "outside geofence"),
    ("UNIT-09", "a-f-G-U-C", "51.53",  "-0.10",  "LONDON-4",  False, "outside geofence"),
    ("UNIT-10", "a-f-G-U-C", "51.54",  "-0.09",  "LONDON-5",  False, "outside geofence"),
    # 3 hostile units inside geofence (matched by hostile rule)
    ("UNIT-11", "a-h-G",     "-33.88", "151.20", "HOSTILE-A", True,  "hostile in fence"),
    ("UNIT-12", "a-h-G",     "-33.89", "151.19", "HOSTILE-B", True,  "hostile in fence"),
    ("UNIT-13", "a-h-G",     "-33.91", "151.18", "HOSTILE-C", True,  "hostile in fence"),
    # 2 duplicates of UNIT-01 (same UID) — should be deduped
    ("UNIT-01", "a-f-G-U-C", "-33.87", "151.21", "ALPHA-1",   False, "dup of UNIT-01"),
    ("UNIT-01", "a-f-G-U-C", "-33.87", "151.21", "ALPHA-1",   False, "dup of UNIT-01"),
    # 5 more friendly units with unknown types — no rule matches
    ("UNIT-14", "b-m-p-s-m", "-33.82", "151.22", "SENSOR-1",  False, "no matching rule"),
    ("UNIT-15", "b-m-p-s-m", "-33.83", "151.23", "SENSOR-2",  False, "no matching rule"),
    ("UNIT-16", "b-m-p-s-m", "-33.84", "151.24", "SENSOR-3",  False, "no matching rule"),
    ("UNIT-17", "b-m-p-s-m", "-33.85", "151.25", "SENSOR-4",  False, "no matching rule"),
    ("UNIT-18", "b-m-p-s-m", "-33.86", "151.26", "SENSOR-5",  False, "no matching rule"),
]
# fmt: on

EXPECTED_PASS_COUNT = sum(1 for row in BATCH if row[5])  # 5 + 3 = 8


class TestOrchestrationBatch:
    """Simulate the plugin orchestration: should_handle → Dedup → RateLimit → build_payload."""

    def _run_batch(self, max_rate=None):
        from services.output_plugin_helpers import (
            Deduplicator,
            RateLimiter,
            build_payload,
            extract_cot_variables,
            should_handle,
        )

        dedup = Deduplicator(ttl_seconds=60)
        rate = RateLimiter(max_rate_per_sec=max_rate)

        results = []

        for uid, cot_type, lat, lon, callsign, _expected, note in BATCH:
            cot_xml = make_cot(uid, cot_type, lat, lon, callsign)

            # Gate 1: filtering
            ok, tpl = should_handle(cot_xml, "", GEOFENCE, MESSAGE_RULES)
            if not ok:
                results.append(("dropped:filter", note, None))
                continue

            # Gate 2: deduplication
            dedup_key = f"{uid}:{cot_type}"
            if not dedup.check(dedup_key):
                results.append(("dropped:dedup", note, None))
                continue

            # Gate 3: rate limit (unlimited in baseline)
            if not rate.check():
                results.append(("dropped:rate", note, None))
                continue

            # Build payload
            variables = extract_cot_variables(cot_xml)
            payload_str = build_payload(variables, "json", tpl, False, cot_xml)

            results.append(("accepted", note, payload_str))

        return results

    def test_correct_events_accepted(self):
        results = self._run_batch()
        accepted = [r for r in results if r[0] == "accepted"]
        assert len(accepted) == EXPECTED_PASS_COUNT, (
            f"Expected {EXPECTED_PASS_COUNT} accepted, got {len(accepted)}: "
            f"{[r[1] for r in accepted]}"
        )

    def test_geofence_drops_counted(self):
        results = self._run_batch()
        geo_drops = [r for r in results if r[0] == "dropped:filter" and "outside" in r[1]]
        assert len(geo_drops) == 5

    def test_dedup_drops_counted(self):
        results = self._run_batch()
        dedup_drops = [r for r in results if r[0] == "dropped:dedup"]
        assert len(dedup_drops) == 2

    def test_no_rule_drops_counted(self):
        results = self._run_batch()
        no_rule_drops = [r for r in results if r[0] == "dropped:filter" and "no matching" in r[1]]
        assert len(no_rule_drops) == 5

    def test_each_accepted_payload_is_well_formed_json(self):
        results = self._run_batch()
        for status, note, payload_str in results:
            if status == "accepted":
                try:
                    parsed = json.loads(payload_str)
                except (json.JSONDecodeError, TypeError) as exc:
                    pytest.fail(f"Payload for '{note}' is not valid JSON: {exc}")
                assert "source" in parsed
                assert parsed["source"] == "trakbridge"
                assert "contact" in parsed
                assert "position" in parsed

    def test_rate_limiter_drops_when_enabled(self):
        """With a very low rate limit, some events are rate-dropped."""
        from services.output_plugin_helpers import (
            Deduplicator,
            RateLimiter,
            build_payload,
            extract_cot_variables,
            should_handle,
        )

        # Only process the 8 events that would normally pass filters/dedup
        # Use a rate of 1 event/second — only the first will pass
        dedup = Deduplicator(ttl_seconds=60)
        rate = RateLimiter(max_rate_per_sec=1.0)

        accepted = 0
        rate_dropped = 0

        for uid, cot_type, lat, lon, callsign, expected_pass, _ in BATCH:
            cot_xml = make_cot(uid, cot_type, lat, lon, callsign)

            ok, tpl = should_handle(cot_xml, "", GEOFENCE, MESSAGE_RULES)
            if not ok:
                continue

            dedup_key = f"{uid}:{cot_type}"
            if not dedup.check(dedup_key):
                continue

            if not rate.check():
                rate_dropped += 1
                continue

            variables = extract_cot_variables(cot_xml)
            build_payload(variables, "json", tpl, False, cot_xml)
            accepted += 1

        # With 1 event/sec rate limit and 8 qualifying events processed instantly,
        # the first is allowed, the rest are rate-dropped
        assert accepted == 1
        assert rate_dropped == EXPECTED_PASS_COUNT - 1

    def test_dedup_second_pass_all_new(self):
        """After TTL expiry (fresh Deduplicator), all qualifying events are new."""
        from services.output_plugin_helpers import (
            Deduplicator,
            RateLimiter,
            build_payload,
            extract_cot_variables,
            should_handle,
        )

        # Fresh dedup with long TTL — UNIT-01 dups still caught
        dedup = Deduplicator(ttl_seconds=60)
        rate = RateLimiter(max_rate_per_sec=None)

        accepted_uids = []

        for uid, cot_type, lat, lon, callsign, _, _ in BATCH:
            cot_xml = make_cot(uid, cot_type, lat, lon, callsign)

            ok, tpl = should_handle(cot_xml, "", GEOFENCE, MESSAGE_RULES)
            if not ok:
                continue

            dedup_key = f"{uid}:{cot_type}"
            if not dedup.check(dedup_key):
                continue

            if not rate.check():
                continue

            variables = extract_cot_variables(cot_xml)
            payload_str = build_payload(variables, "json", tpl, False, cot_xml)
            parsed = json.loads(payload_str)
            accepted_uids.append(parsed["cot"]["uid"])

        # Each accepted UID should be unique — dedup caught the UNIT-01 repeats
        assert len(accepted_uids) == len(set(accepted_uids)), (
            f"Duplicate UIDs found in accepted events: {accepted_uids}"
        )
