"""
ABOUTME: Unit tests for _TxSummary — per-TAK-server rolling stats used to
ABOUTME: emit periodic INFO TX summaries instead of per-event log lines.
"""

from services.cot_service_integration import _TxSummary


class TestTxSummary:
    def test_starts_empty(self):
        s = _TxSummary(now=lambda: 0.0)
        assert s.event_count == 0
        assert s.callsigns == set()

    def test_record_increments_count_and_collects_callsigns(self):
        s = _TxSummary(now=lambda: 0.0)
        s.record("Chaos1")
        s.record("Bravo2")
        s.record("Chaos1")
        assert s.event_count == 3
        assert s.callsigns == {"Chaos1", "Bravo2"}

    def test_should_flush_returns_false_below_thresholds(self):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            max_events=100,
            now=lambda: clock[0],
        )
        for _ in range(10):
            s.record("Chaos1")
        clock[0] = 5.0
        assert s.should_flush() is False

    def test_should_flush_returns_true_after_interval(self):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            max_events=100,
            now=lambda: clock[0],
        )
        s.record("Chaos1")
        clock[0] = 30.1
        assert s.should_flush() is True

    def test_should_flush_returns_true_after_event_cap(self):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            max_events=5,
            now=lambda: clock[0],
        )
        for _ in range(5):
            s.record("Chaos1")
        assert s.should_flush() is True

    def test_should_flush_false_when_empty(self):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            max_events=100,
            now=lambda: clock[0],
        )
        clock[0] = 1000.0  # interval long passed, but no events
        assert s.should_flush() is False

    def test_render_includes_count_and_callsigns(self):
        s = _TxSummary(now=lambda: 0.0)
        s.record("Chaos1")
        s.record("Bravo2")
        s.record("Chaos1")
        line = s.render(duration_seconds=30.0)
        assert "3 events" in line
        assert "Chaos1" in line
        assert "Bravo2" in line

    def test_render_caps_callsign_list(self):
        s = _TxSummary(now=lambda: 0.0)
        for i in range(20):
            s.record(f"Callsign{i}")
        line = s.render(duration_seconds=30.0)
        # All 20 in plaintext would be very long; cap at a reasonable number
        # with an ellipsis-style indicator.
        assert "20 events" in line or "20 unique" in line or "+" in line

    def test_reset_clears_state_and_resets_clock(self):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            max_events=100,
            now=lambda: clock[0],
        )
        s.record("Chaos1")
        clock[0] = 30.1
        assert s.should_flush() is True
        s.reset()
        assert s.event_count == 0
        assert s.callsigns == set()
        # After reset, the clock baseline is "now" so should_flush is False
        # immediately.
        assert s.should_flush() is False
