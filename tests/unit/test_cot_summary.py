"""
ABOUTME: Unit tests for _summarise_cot_for_log — the concise INFO-line formatter
ABOUTME: used by TX log sites to avoid dumping full CoT XML at INFO level.
"""

from services.cot_service_integration import _summarise_cot_for_log

ATAK_EVENT = (
    b'<event version="2.0" uid="ANDROID-64293d86bd018739" type="a-f-G-U-C" '
    b'how="h-e" time="2026-06-29T16:19:02.555Z" start="2026-06-29T16:19:02.555Z" '
    b'stale="2026-06-29T16:20:17.555Z">'
    b'<point lat="-29.93" lon="152.52" hae="410.7" ce="9999999" le="9999999"/>'
    b"<detail>"
    b'<contact callsign="Chaos1" endpoint="10.0.10.28:4242:tcp"/>'
    b'<__group name="White" role="Team Member"/>'
    b'<takv device="SAMSUNG SM-S936B" platform="ATAK-CIV" os="36" '
    b'version="5.7.0.5 (3198049e).1778680862-CIV"/>'
    b'<status battery="23"/>'
    b'<track speed="0" course="11.5"/>'
    b'<uid Droid="Chaos1"/>'
    b"</detail>"
    b"</event>"
)

IDENTITY_EVENT = (
    b'<event version="2.0" uid="trakbridge-Taknet-580260" type="a-f-G-U-C" '
    b'time="2026-06-29T15:04:20Z" start="2026-06-29T15:04:20Z" '
    b'stale="2026-06-29T15:05:20Z" how="h-e">'
    b'<point lat="-33.73" lon="151.28" hae="0.0" ce="10.0" le="10.0"/>'
    b"<detail>"
    b'<takv os="34" version="1.2.3" device="TrakBridge" platform="TrakBridge"/>'
    b'<contact callsign="Emfour-HQ" endpoint="*:-1:stcp"/>'
    b'<uid Droid="Emfour-HQ"/>'
    b"</detail></event>"
)


class TestSummariseCoT:
    def test_atak_event_includes_callsign_platform_and_endpoint(self):
        s = _summarise_cot_for_log(ATAK_EVENT)
        assert "Chaos1" in s
        assert "ATAK-CIV" in s
        assert "10.0.10.28" in s

    def test_identity_event_includes_callsign_and_platform(self):
        s = _summarise_cot_for_log(IDENTITY_EVENT)
        assert "Emfour-HQ" in s
        assert "TrakBridge" in s

    def test_identity_event_marks_self_endpoint(self):
        # Endpoint "*:-1:stcp" is the self-marker; should be omitted or
        # rendered as "self" rather than printed verbatim.
        s = _summarise_cot_for_log(IDENTITY_EVENT)
        assert "*:-1" not in s

    def test_malformed_xml_returns_safe_placeholder(self):
        # Should never raise on garbage; logging must never crash a worker.
        s = _summarise_cot_for_log(b"not xml at all")
        assert isinstance(s, str)
        assert len(s) > 0

    def test_empty_payload_returns_safe_placeholder(self):
        s = _summarise_cot_for_log(b"")
        assert isinstance(s, str)

    def test_event_without_detail_still_returns_string(self):
        evt = (
            b'<event uid="x" type="a-f-G-U-C"><point lat="0" lon="0" hae="0" '
            b'ce="0" le="0"/></event>'
        )
        s = _summarise_cot_for_log(evt)
        assert isinstance(s, str)
        assert "x" in s  # uid as fallback identifier

    def test_event_with_only_callsign(self):
        evt = (
            b'<event uid="x" type="a-f-G-U-C">'
            b'<point lat="0" lon="0" hae="0" ce="0" le="0"/>'
            b'<detail><contact callsign="LoneWolf"/></detail></event>'
        )
        s = _summarise_cot_for_log(evt)
        assert "LoneWolf" in s
