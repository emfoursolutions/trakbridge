"""
ABOUTME: Unit tests for StreamWorker's retry persistence: consecutive poll
ABOUTME: errors must back off and keep retrying, never permanently deactivate.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from plugins.base_plugin import BaseGPSPlugin
from services.stream_worker import StreamWorker

# Captured before any patching: the patch target below is an attribute on the
# shared asyncio module, so the test's own timeout guard must not go through it.
_real_wait_for = asyncio.wait_for


async def _guarded(coro, timeout=5.0):
    return await _real_wait_for(coro, timeout)


def _make_stream(poll_interval=0.001):
    stream = Mock()
    stream.id = 1
    stream.name = "Retry Test Stream"
    stream.plugin_type = "garmin"
    stream.poll_interval = poll_interval
    stream.enable_callsign_mapping = False
    return stream


def _make_worker(poll_interval=0.001):
    worker = StreamWorker(_make_stream(poll_interval), Mock(), Mock())
    worker.plugin = Mock(spec=BaseGPSPlugin)
    worker.running = True
    worker._stop_event = asyncio.Event()
    worker._tak_worker_ensured = False
    worker._update_stream_status_async = AsyncMock()
    worker._apply_callsign_mapping = AsyncMock()
    return worker


def _instant_timeout():
    """Fake for asyncio.wait_for that records backoff delays and times out
    immediately, fast-forwarding the retry sleeps."""
    delays = []

    async def fake_wait_for(awaitable, timeout=None):
        delays.append(timeout)
        # Close the un-awaited coroutine to keep test output pristine.
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.TimeoutError

    return delays, fake_wait_for


class TestStreamWorkerRetryPersistence:

    async def test_six_consecutive_errors_do_not_deactivate(self):
        worker = _make_worker()
        fetch_calls = {"n": 0}

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] >= 7:
                worker.running = False
                return []
            raise RuntimeError("plugin down")

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        assert fetch_calls["n"] >= 7, (
            f"loop stopped after {fetch_calls['n']} polls; it must keep "
            "retrying past max_consecutive_errors"
        )
        deactivations = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("is_active") is False
        ]
        assert not deactivations, (
            f"stream was deactivated on consecutive errors: {deactivations}"
        )

    async def test_stream_recovers_after_errors(self):
        worker = _make_worker()
        fetch_calls = {"n": 0}

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] <= 7:
                raise RuntimeError("plugin down")
            worker.running = False
            return [{"lat": 1.0, "lon": 2.0, "name": "t1", "uid": "t-1"}]

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        assert worker._consecutive_errors == 0, (
            "error counter not reset after successful poll"
        )
        success_updates = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("last_error", "sentinel") is None
        ]
        assert success_updates, "recovery never recorded last_error=None"

    async def test_backoff_caps_at_max(self):
        worker = _make_worker(poll_interval=100)
        fetch_calls = {"n": 0}

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] >= 7:
                worker.running = False
                return []
            raise RuntimeError("plugin down")

        worker.plugin.fetch_locations_with_protection = fetch
        delays, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        # poll_interval * 2^(n-1) capped at 300: 100, 200, then 300 forever.
        assert delays[:5] == [100, 200, 300, 300, 300], (
            f"backoff sequence wrong or truncated: {delays}"
        )

    async def test_error_logged_at_error_past_threshold_with_last_error_persisted(
        self, caplog
    ):
        worker = _make_worker()
        fetch_calls = {"n": 0}

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] >= 7:
                worker.running = False
                return []
            raise RuntimeError("plugin down")

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with (
            patch("services.stream_worker.asyncio.wait_for", fake_wait_for),
            caplog.at_level(logging.ERROR),
        ):
            await _guarded(worker._run_loop())

        threshold_errors = [
            r.message
            for r in caplog.records
            if r.levelno >= logging.ERROR and "consecutive" in r.message.lower()
        ]
        assert threshold_errors, (
            "no ERROR log about sustained consecutive failures"
        )
        # last_error persisted on every failed poll so the UI shows degraded
        error_updates = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("last_error")
        ]
        assert len(error_updates) >= 6


class TestSentinelErrorDetection:
    """Plugins signal feed failure with [{"_error": ...}] sentinels (built
    for the connection-test UI). The poll loop must treat sentinel-only
    results as failed polls, not successful data retrieval — otherwise a
    total feed outage shows a healthy stream with no retry machinery."""

    async def test_sentinel_only_fetch_counts_as_error(self):
        worker = _make_worker()
        fetch_calls = {"n": 0}
        sentinel = [
            {"_error": "connection_failed", "_error_message": "Network is unreachable"}
        ]

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] >= 4:
                worker.running = False
                return []
            return sentinel

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        assert fetch_calls["n"] >= 4, "loop stopped instead of retrying"
        error_updates = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("last_error")
            and "Network is unreachable" in c.kwargs["last_error"]
        ]
        assert error_updates, (
            "sentinel-only fetch was not recorded as a poll failure with "
            "the sentinel's message in last_error"
        )
        deactivations = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("is_active") is False
        ]
        assert not deactivations

    async def test_mixed_sentinel_and_real_locations_is_success(self):
        worker = _make_worker()

        async def fetch(session):
            worker.running = False
            return [
                {"_error": "connection_failed", "_error_message": "partial"},
                {"lat": 1.0, "lon": 2.0, "name": "t1", "uid": "t-1"},
            ]

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        assert worker._consecutive_errors == 0, (
            "partial data (mixed sentinel + real) must count as success"
        )

    async def test_empty_list_is_not_an_error(self):
        worker = _make_worker()

        async def fetch(session):
            worker.running = False
            return []

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with patch("services.stream_worker.asyncio.wait_for", fake_wait_for):
            await _guarded(worker._run_loop())

        assert worker._consecutive_errors == 0
        error_updates = [
            c
            for c in worker._update_stream_status_async.await_args_list
            if c.kwargs.get("last_error")
        ]
        assert not error_updates, (
            "an empty feed is a legitimate state, not a failure"
        )


class TestFeedErrorLogNoise:
    """A classified feed outage is an operational state, not a crash —
    log it as a one-liner. Unexpected exceptions keep their tracebacks."""

    async def test_feed_error_logged_without_traceback(self, caplog):
        worker = _make_worker()
        fired = {"n": 0}

        async def fetch(session):
            fired["n"] += 1
            if fired["n"] >= 2:
                worker.running = False
                return []
            return [{"_error": "connection_failed", "_error_message": "down"}]

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with (
            patch("services.stream_worker.asyncio.wait_for", fake_wait_for),
            caplog.at_level(logging.ERROR),
        ):
            await _guarded(worker._run_loop())

        feed_records = [
            r for r in caplog.records if "Feed error" in r.message
        ]
        assert feed_records, "feed error was not logged"
        # exc_info may be None or literal False depending on how the logger
        # forwards it; either way no traceback is formatted.
        assert all(not r.exc_info for r in feed_records), (
            "feed outages must not log tracebacks — they read like crashes"
        )

    async def test_unexpected_error_keeps_traceback(self, caplog):
        worker = _make_worker()
        fired = {"n": 0}

        async def fetch(session):
            fired["n"] += 1
            if fired["n"] >= 2:
                worker.running = False
                return []
            raise RuntimeError("actual bug")

        worker.plugin.fetch_locations_with_protection = fetch
        _, fake_wait_for = _instant_timeout()

        with (
            patch("services.stream_worker.asyncio.wait_for", fake_wait_for),
            caplog.at_level(logging.ERROR),
        ):
            await _guarded(worker._run_loop())

        loop_records = [
            r
            for r in caplog.records
            if "Error in stream loop" in r.message and "actual bug" in r.message
        ]
        assert loop_records
        assert any(r.exc_info for r in loop_records), (
            "unexpected exceptions must keep their tracebacks"
        )
