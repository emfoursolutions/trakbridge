"""
ABOUTME: Unit tests for CircuitBreaker service covering state transitions, failure thresholds,
ABOUTME: recovery timeout, health checks, metrics, and manager lifecycle.
"""

import asyncio
import pytest
from datetime import datetime, timezone

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerManager,
    CircuitBreakerState,
    CircuitBreakerError,
    CircuitOpenError,
)


# Shared config with short timeouts for fast tests
TEST_CONFIG = CircuitBreakerConfig(
    failure_threshold=3,
    recovery_timeout=0.1,
    timeout=5.0,
    jitter_enabled=False,
)


async def async_success(*args, **kwargs):
    """Async helper that succeeds."""
    return "ok"


async def async_failure(*args, **kwargs):
    """Async helper that raises."""
    raise RuntimeError("boom")


def sync_success(*args, **kwargs):
    """Sync helper that succeeds."""
    return "sync_ok"


def sync_failure(*args, **kwargs):
    """Sync helper that raises."""
    raise RuntimeError("sync_boom")


async def slow_function():
    """Async helper that takes too long."""
    await asyncio.sleep(60)
    return "never"


class TestCircuitBreakerInitialState:
    """Verify the circuit breaker starts in the expected default state."""

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_initial_counts_are_zero(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.consecutive_failures == 0
        assert cb.half_open_calls == 0

    @pytest.mark.asyncio
    async def test_initial_backoff_delay(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.backoff_delay == 1.0

    @pytest.mark.asyncio
    async def test_default_config_used_when_none(self):
        cb = CircuitBreaker("test-svc")
        assert cb.config.failure_threshold == 3
        assert cb.config.recovery_timeout == 60.0
        assert cb.config.timeout == 30.0


class TestCircuitBreakerStateEnum:
    """Validate the CircuitBreakerState enum values."""

    def test_enum_values(self):
        assert CircuitBreakerState.CLOSED.value == "closed"
        assert CircuitBreakerState.OPEN.value == "open"
        assert CircuitBreakerState.HALF_OPEN.value == "half_open"


class TestCircuitBreakerConfigDefaults:
    """Validate default values of CircuitBreakerConfig."""

    def test_default_values(self):
        cfg = CircuitBreakerConfig()
        assert cfg.failure_threshold == 3
        assert cfg.recovery_timeout == 60.0
        assert cfg.half_open_max_calls == 5
        assert cfg.success_threshold == 3
        assert cfg.timeout == 30.0
        assert cfg.exponential_backoff_base == 2.0
        assert cfg.max_backoff_delay == 300.0
        assert cfg.jitter_enabled is True
        assert cfg.health_check_interval == 30.0
        assert cfg.health_check_timeout == 10.0
        assert cfg.metrics_window_size == 100
        assert cfg.metrics_reset_interval == 3600.0


class TestClosedState:
    """Tests for circuit breaker behavior while in the CLOSED state."""

    @pytest.mark.asyncio
    async def test_successful_calls_stay_closed(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(5):
            result = await cb.call(async_success)
            assert result == "ok"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold - 1):
            with pytest.raises(RuntimeError, match="boom"):
                await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == TEST_CONFIG.failure_threshold - 1

    @pytest.mark.asyncio
    async def test_reaching_threshold_opens_circuit(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError, match="boom"):
                await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_failure_count_tracks_correctly(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.failure_count == 1
        assert cb.consecutive_failures == 1


class TestOpenState:
    """Tests for circuit breaker behavior while in the OPEN state."""

    @pytest.mark.asyncio
    async def test_open_circuit_raises_circuit_open_error(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        # Trip the circuit
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(async_success)
        assert exc_info.value.service_name == "test-svc"
        assert isinstance(exc_info.value.next_attempt_time, datetime)

    @pytest.mark.asyncio
    async def test_circuit_open_error_is_circuit_breaker_error(self):
        """CircuitOpenError inherits from CircuitBreakerError."""
        err = CircuitOpenError("svc", datetime.now(timezone.utc))
        assert isinstance(err, CircuitBreakerError)

    @pytest.mark.asyncio
    async def test_transition_to_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        # Trip the circuit
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN

        # Wait for recovery_timeout to pass
        await asyncio.sleep(TEST_CONFIG.recovery_timeout + 0.05)

        # Next call should transition to HALF_OPEN and execute
        result = await cb.call(async_success)
        assert result == "ok"
        assert cb.state == CircuitBreakerState.HALF_OPEN


class TestHalfOpenState:
    """Tests for circuit breaker behavior while in the HALF_OPEN state."""

    async def _get_half_open_breaker(self) -> CircuitBreaker:
        """Helper to produce a breaker in HALF_OPEN state."""
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        await asyncio.sleep(TEST_CONFIG.recovery_timeout + 0.05)
        # This call transitions to HALF_OPEN
        await cb.call(async_success)
        assert cb.state == CircuitBreakerState.HALF_OPEN
        return cb

    @pytest.mark.asyncio
    async def test_successes_close_circuit(self):
        cb = await self._get_half_open_breaker()
        # Already got 1 success from _get_half_open_breaker transition call.
        # success_count was reset to 0 on transition to HALF_OPEN,
        # then incremented by the successful call, so it's 1.
        remaining = TEST_CONFIG.success_threshold - cb.success_count
        for _ in range(remaining):
            await cb.call(async_success)
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_any_failure_reopens_circuit(self):
        cb = await self._get_half_open_breaker()
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_resets_success_count(self):
        """Transitioning to HALF_OPEN resets success_count to 0."""
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        # Accumulate some successes first
        await cb.call(async_success)
        assert cb.success_count == 1
        # Trip to OPEN
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        await asyncio.sleep(TEST_CONFIG.recovery_timeout + 0.05)
        # Transition to HALF_OPEN resets success_count
        await cb.call(async_success)
        # success_count should be 1 (reset to 0 on transition, then +1 for the call)
        assert cb.success_count == 1


class TestTransitionSideEffects:
    """Verify counters and metrics are updated correctly on state transitions."""

    @pytest.mark.asyncio
    async def test_open_increments_opened_count(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.metrics.circuit_opened_count == 1

    @pytest.mark.asyncio
    async def test_closed_increments_closed_count(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
            success_threshold=1,
        )
        cb = CircuitBreaker("test-svc", config)
        # Trip to OPEN
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN
        await asyncio.sleep(0.15)
        # Transition to HALF_OPEN then to CLOSED with one success
        await cb.call(async_success)
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.metrics.circuit_closed_count == 1

    @pytest.mark.asyncio
    async def test_closed_transition_resets_counts(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
            success_threshold=1,
        )
        cb = CircuitBreaker("test-svc", config)
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        await asyncio.sleep(0.15)
        await cb.call(async_success)
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.half_open_calls == 0


class TestManualControls:
    """Tests for manual_reset and force_open."""

    @pytest.mark.asyncio
    async def test_manual_reset_returns_to_closed(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        # Trip to OPEN
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.state == CircuitBreakerState.OPEN
        await cb.manual_reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.consecutive_failures == 0
        assert cb.backoff_delay == 1.0

    @pytest.mark.asyncio
    async def test_manual_reset_resets_failure_count(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        await cb.manual_reset()
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_force_open_opens_circuit(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.state == CircuitBreakerState.CLOSED
        await cb.force_open()
        assert cb.state == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_force_open_blocks_calls(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        await cb.force_open()
        with pytest.raises(CircuitOpenError):
            await cb.call(async_success)


class TestBackoffDelay:
    """Tests for exponential backoff behavior on consecutive failures."""

    @pytest.mark.asyncio
    async def test_backoff_increases_on_consecutive_failures(self):
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
            exponential_backoff_base=2.0,
        )
        cb = CircuitBreaker("test-svc", config)
        # Initial backoff is 1.0
        assert cb.backoff_delay == 1.0

        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        # 1.0 * 2.0 = 2.0
        assert cb.backoff_delay == 2.0

        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        # 2.0 * 2.0 = 4.0
        assert cb.backoff_delay == 4.0

        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        # 4.0 * 2.0 = 8.0
        assert cb.backoff_delay == 8.0

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max(self):
        config = CircuitBreakerConfig(
            failure_threshold=20,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
            exponential_backoff_base=2.0,
            max_backoff_delay=10.0,
        )
        cb = CircuitBreaker("test-svc", config)
        # Drive backoff past the cap: 1 -> 2 -> 4 -> 8 -> 10(capped)
        for _ in range(5):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.backoff_delay == 10.0

    @pytest.mark.asyncio
    async def test_backoff_resets_on_success(self):
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
        )
        cb = CircuitBreaker("test-svc", config)
        # Cause some failures to increase backoff
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.backoff_delay > 1.0

        # A success resets it
        await cb.call(async_success)
        assert cb.backoff_delay == 1.0
        assert cb.consecutive_failures == 0


class TestMetricsTracking:
    """Tests for metrics recording."""

    @pytest.mark.asyncio
    async def test_total_calls_counted(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        await cb.call(async_success)
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.metrics.total_calls == 2

    @pytest.mark.asyncio
    async def test_successful_and_failed_calls(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        await cb.call(async_success)
        await cb.call(async_success)
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.metrics.successful_calls == 2
        assert cb.metrics.failed_calls == 1

    @pytest.mark.asyncio
    async def test_failure_rate_calculation(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        await cb.call(async_success)
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        # 1 fail out of 2 total = 0.5
        assert cb.metrics.failure_rate == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_average_response_time_tracked(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        await cb.call(async_success)
        assert cb.metrics.average_response_time >= 0.0

    @pytest.mark.asyncio
    async def test_call_history_capped_at_window_size(self):
        config = CircuitBreakerConfig(
            failure_threshold=200,
            recovery_timeout=0.1,
            timeout=5.0,
            jitter_enabled=False,
            metrics_window_size=5,
        )
        cb = CircuitBreaker("test-svc", config)
        for _ in range(10):
            await cb.call(async_success)
        assert len(cb.metrics.call_history) == 5

    @pytest.mark.asyncio
    async def test_last_failure_time_set_on_failure(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.metrics.last_failure_time is None
        with pytest.raises(RuntimeError):
            await cb.call(async_failure)
        assert cb.metrics.last_failure_time is not None

    @pytest.mark.asyncio
    async def test_last_success_time_set_on_success(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.metrics.last_success_time is None
        await cb.call(async_success)
        assert cb.metrics.last_success_time is not None


class TestSyncAndAsyncSupport:
    """Tests for both sync and async function handling."""

    @pytest.mark.asyncio
    async def test_async_function_execution(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        result = await cb.call(async_success)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_sync_function_execution(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        result = await cb.call(sync_success)
        assert result == "sync_ok"

    @pytest.mark.asyncio
    async def test_sync_failure_recorded(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        with pytest.raises(RuntimeError, match="sync_boom"):
            await cb.call(sync_failure)
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_args_passed_to_function(self):
        async def adder(a, b):
            return a + b

        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        result = await cb.call(adder, 3, 7)
        assert result == 10

    @pytest.mark.asyncio
    async def test_kwargs_passed_to_function(self):
        async def greeter(name="world"):
            return f"hello {name}"

        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        result = await cb.call(greeter, name="Poults")
        assert result == "hello Poults"


class TestTimeoutHandling:
    """Tests for function call timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_raises_and_records_failure(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=0.1,
            timeout=0.1,
            jitter_enabled=False,
        )
        cb = CircuitBreaker("test-svc", config)
        with pytest.raises(asyncio.TimeoutError):
            await cb.call(slow_function)
        assert cb.failure_count == 1


class TestGetStatus:
    """Tests for the get_status method."""

    @pytest.mark.asyncio
    async def test_status_has_all_expected_keys(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        status = cb.get_status()

        expected_top_keys = {
            "service_name",
            "state",
            "failure_count",
            "success_count",
            "consecutive_failures",
            "last_failure_time",
            "last_state_change",
            "next_attempt_time",
            "backoff_delay",
            "half_open_calls",
            "metrics",
            "config",
        }
        assert set(status.keys()) == expected_top_keys

    @pytest.mark.asyncio
    async def test_status_metrics_keys(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        metrics = cb.get_status()["metrics"]
        expected_metric_keys = {
            "total_calls",
            "successful_calls",
            "failed_calls",
            "failure_rate",
            "average_response_time",
            "circuit_opened_count",
            "circuit_closed_count",
        }
        assert set(metrics.keys()) == expected_metric_keys

    @pytest.mark.asyncio
    async def test_status_config_keys(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        config = cb.get_status()["config"]
        expected_config_keys = {
            "failure_threshold",
            "recovery_timeout",
            "timeout",
            "max_backoff_delay",
        }
        assert set(config.keys()) == expected_config_keys

    @pytest.mark.asyncio
    async def test_status_reflects_current_state(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.get_status()["state"] == "closed"
        assert cb.get_status()["service_name"] == "test-svc"

    @pytest.mark.asyncio
    async def test_status_next_attempt_time_none_when_closed(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        assert cb.get_status()["next_attempt_time"] is None

    @pytest.mark.asyncio
    async def test_status_next_attempt_time_set_when_open(self):
        cb = CircuitBreaker("test-svc", TEST_CONFIG)
        for _ in range(TEST_CONFIG.failure_threshold):
            with pytest.raises(RuntimeError):
                await cb.call(async_failure)
        assert cb.get_status()["next_attempt_time"] is not None


class TestCircuitBreakerManagerCreate:
    """Tests for CircuitBreakerManager creation and retrieval."""

    @pytest.mark.asyncio
    async def test_create_new_breaker(self):
        mgr = CircuitBreakerManager()
        cb = mgr.get_circuit_breaker("svc-a")
        assert cb.service_name == "svc-a"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_get_existing_breaker(self):
        mgr = CircuitBreakerManager()
        cb1 = mgr.get_circuit_breaker("svc-a")
        cb2 = mgr.get_circuit_breaker("svc-a")
        assert cb1 is cb2

    @pytest.mark.asyncio
    async def test_different_names_different_breakers(self):
        mgr = CircuitBreakerManager()
        cb1 = mgr.get_circuit_breaker("svc-a")
        cb2 = mgr.get_circuit_breaker("svc-b")
        assert cb1 is not cb2

    @pytest.mark.asyncio
    async def test_custom_config_applied(self):
        mgr = CircuitBreakerManager()
        custom = CircuitBreakerConfig(failure_threshold=10)
        cb = mgr.get_circuit_breaker("svc-a", custom)
        assert cb.config.failure_threshold == 10


class TestCircuitBreakerManagerOperations:
    """Tests for CircuitBreakerManager status, reset, and cleanup."""

    @pytest.mark.asyncio
    async def test_get_all_status(self):
        mgr = CircuitBreakerManager()
        mgr.get_circuit_breaker("svc-a")
        mgr.get_circuit_breaker("svc-b")
        all_status = mgr.get_all_status()
        assert "svc-a" in all_status
        assert "svc-b" in all_status
        assert all_status["svc-a"]["service_name"] == "svc-a"
        assert all_status["svc-b"]["service_name"] == "svc-b"

    @pytest.mark.asyncio
    async def test_reset_all(self):
        mgr = CircuitBreakerManager()
        cb1 = mgr.get_circuit_breaker("svc-a", TEST_CONFIG)
        cb2 = mgr.get_circuit_breaker("svc-b", TEST_CONFIG)
        # Trip both
        for cb in (cb1, cb2):
            for _ in range(TEST_CONFIG.failure_threshold):
                with pytest.raises(RuntimeError):
                    await cb.call(async_failure)
            assert cb.state == CircuitBreakerState.OPEN

        await mgr.reset_all()
        assert cb1.state == CircuitBreakerState.CLOSED
        assert cb2.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_cleanup_all_clears_breakers(self):
        mgr = CircuitBreakerManager()
        mgr.get_circuit_breaker("svc-a")
        mgr.get_circuit_breaker("svc-b")
        assert len(mgr.circuit_breakers) == 2
        await mgr.cleanup_all()
        assert len(mgr.circuit_breakers) == 0

    @pytest.mark.asyncio
    async def test_get_all_status_empty(self):
        mgr = CircuitBreakerManager()
        assert mgr.get_all_status() == {}


class TestCircuitBreakerErrors:
    """Tests for error classes."""

    def test_circuit_open_error_attributes(self):
        now = datetime.now(timezone.utc)
        err = CircuitOpenError("my-service", now)
        assert err.service_name == "my-service"
        assert err.next_attempt_time == now
        assert "my-service" in str(err)

    def test_circuit_open_error_inherits_base(self):
        err = CircuitOpenError("svc", datetime.now(timezone.utc))
        assert isinstance(err, CircuitBreakerError)
        assert isinstance(err, Exception)
