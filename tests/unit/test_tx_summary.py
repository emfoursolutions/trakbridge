"""
ABOUTME: Unit tests for _TxSummary — per-TAK-server rolling stats used to
ABOUTME: emit periodic INFO TX summaries instead of per-event log lines.
"""

import logging

from services.cot_service_integration import QueuedCOTService, _TxSummary


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


class TestTxSummaryRollup:
    """The 30s window is DEBUG noise; rollups give the periodic INFO signal."""

    def _summary(self, clock, rollup=600.0):
        return _TxSummary(
            interval_seconds=30,
            max_events=100,
            rollup_interval_seconds=rollup,
            now=lambda: clock[0],
        )

    def test_reset_folds_window_stats_into_rollup(self):
        clock = [0.0]
        s = self._summary(clock)
        s.record("Chaos1")
        s.record("Bravo2")
        s.reset()
        assert s.rollup_event_count == 2
        assert s.rollup_callsigns == {"Chaos1", "Bravo2"}
        # Window itself is cleared
        assert s.event_count == 0

    def test_rollup_accumulates_across_windows(self):
        clock = [0.0]
        s = self._summary(clock)
        s.record("Chaos1")
        s.reset()
        s.record("Bravo2")
        s.record("Bravo2")
        s.reset()
        assert s.rollup_event_count == 3
        assert s.rollup_callsigns == {"Chaos1", "Bravo2"}

    def test_should_flush_rollup_false_before_interval(self):
        clock = [0.0]
        s = self._summary(clock, rollup=600.0)
        s.record("Chaos1")
        s.reset()
        clock[0] = 599.0
        assert s.should_flush_rollup() is False

    def test_should_flush_rollup_true_after_interval_with_events(self):
        clock = [0.0]
        s = self._summary(clock, rollup=600.0)
        s.record("Chaos1")
        s.reset()
        clock[0] = 600.1
        assert s.should_flush_rollup() is True

    def test_should_flush_rollup_false_when_no_events(self):
        clock = [0.0]
        s = self._summary(clock, rollup=600.0)
        clock[0] = 1200.0
        assert s.should_flush_rollup() is False

    def test_reset_rollup_clears_and_rearms(self):
        clock = [0.0]
        s = self._summary(clock, rollup=600.0)
        s.record("Chaos1")
        s.reset()
        clock[0] = 600.1
        assert s.should_flush_rollup() is True
        s.reset_rollup()
        assert s.rollup_event_count == 0
        assert s.rollup_callsigns == set()
        assert s.should_flush_rollup() is False

    def test_render_rollup_includes_count_and_unique(self):
        clock = [0.0]
        s = self._summary(clock)
        s.record("Chaos1")
        s.record("Bravo2")
        s.reset()
        clock[0] = 600.0
        line = s.render_rollup()
        assert "2 events" in line
        assert "2 unique" in line
        assert "Chaos1" in line


class TestTxSummarySilenceDetection:
    def test_first_record_is_not_a_resume(self):
        clock = [0.0]
        s = _TxSummary(rollup_interval_seconds=600.0, now=lambda: clock[0])
        s.record("Chaos1")
        assert s.resumed_after_silence is False

    def test_record_after_long_gap_sets_resumed_flag(self):
        clock = [0.0]
        s = _TxSummary(rollup_interval_seconds=600.0, now=lambda: clock[0])
        s.record("Chaos1")
        clock[0] = 601.0
        s.record("Chaos1")
        assert s.resumed_after_silence is True

    def test_record_within_gap_threshold_does_not_set_flag(self):
        clock = [0.0]
        s = _TxSummary(rollup_interval_seconds=600.0, now=lambda: clock[0])
        s.record("Chaos1")
        clock[0] = 30.0
        s.record("Chaos1")
        assert s.resumed_after_silence is False


class TestFlushTxSummaryLogLevels:
    """Window flushes are DEBUG; rollups and resume-after-silence are INFO."""

    LOGGER_NAME = "services.cot_service_integration"

    def _service_with(self, summary):
        svc = QueuedCOTService.__new__(QueuedCOTService)
        svc._tx_summaries = {1: summary}
        return svc

    def test_window_flush_logs_at_debug_not_info(self, caplog):
        clock = [0.0]
        s = _TxSummary(interval_seconds=30, now=lambda: clock[0])
        s.record("Chaos1")
        clock[0] = 30.1
        svc = self._service_with(s)
        with caplog.at_level(logging.DEBUG, logger=self.LOGGER_NAME):
            svc._flush_tx_summary(1, "Taknet")
        tx_records = [r for r in caplog.records if "TX -> Taknet" in r.message]
        assert tx_records, "expected a window flush log line"
        assert all(r.levelno == logging.DEBUG for r in tx_records)

    def test_rollup_flush_logs_at_info(self, caplog):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            rollup_interval_seconds=600.0,
            now=lambda: clock[0],
        )
        s.record("Chaos1")
        clock[0] = 601.0  # window AND rollup both due
        svc = self._service_with(s)
        with caplog.at_level(logging.DEBUG, logger=self.LOGGER_NAME):
            svc._flush_tx_summary(1, "Taknet")
        info_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "TX -> Taknet" in r.message
        ]
        assert info_records, "expected an INFO rollup log line"
        assert s.rollup_event_count == 0  # rollup rearmed after flush

    def test_resume_after_silence_logs_at_info(self, caplog):
        clock = [0.0]
        s = _TxSummary(
            interval_seconds=30,
            rollup_interval_seconds=600.0,
            now=lambda: clock[0],
        )
        s.record("Chaos1")
        s.reset()
        s.reset_rollup()
        clock[0] = 700.0
        s.record("Chaos1")  # resume after >600s of silence
        svc = self._service_with(s)
        with caplog.at_level(logging.DEBUG, logger=self.LOGGER_NAME):
            svc._flush_tx_summary(1, "Taknet")
        resume_records = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "resumed" in r.message.lower()
        ]
        assert resume_records, "expected an INFO resume log line"
        assert s.resumed_after_silence is False  # flag consumed
