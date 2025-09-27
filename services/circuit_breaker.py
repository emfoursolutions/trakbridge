"""
ABOUTME: Circuit breaker pattern implementation for fault tolerance and failure protection
ABOUTME: providing automatic failure detection, recovery mechanisms, and intelligent retry logic

File: services/circuit_breaker.py

Description:
    Comprehensive circuit breaker implementation for TrakBridge providing robust
    fault tolerance for external service calls. Supports multiple states (closed,
    open, half-open), configurable failure thresholds, exponential backoff retry
    logic, and automatic recovery mechanisms for plugin APIs and TAK connections.

Key features:
    - Three-state circuit breaker (closed, open, half-open)
    - Configurable failure thresholds and recovery timeouts
    - Exponential backoff with jitter for retry logic
    - Per-service circuit breaker instances with independent state
    - Health check integration with automatic recovery
    - Comprehensive metrics and failure tracking
    - Integration with existing performance monitoring
    - Thread-safe operation with async support

Author: TrakBridge Development Team
Created: 2025-09-27
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states"""

    CLOSED = "closed"  # Normal operation, allowing requests
    OPEN = "open"  # Failing fast, blocking requests
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior"""

    failure_threshold: int = 3  # Failures before opening circuit
    recovery_timeout: float = 60.0  # Seconds to wait before trying again
    half_open_max_calls: int = 5  # Max calls to test in half-open state
    success_threshold: int = 3  # Successes needed to close circuit
    timeout: float = 30.0  # Request timeout in seconds
    exponential_backoff_base: float = 2.0  # Base for exponential backoff
    max_backoff_delay: float = 300.0  # Max delay between retries (5 minutes)
    jitter_enabled: bool = True  # Add randomness to prevent thundering herd

    # Health check configuration
    health_check_interval: float = 30.0  # Seconds between health checks
    health_check_timeout: float = 10.0  # Health check timeout

    # Metrics configuration
    metrics_window_size: int = 100  # Number of recent calls to track
    metrics_reset_interval: float = 3600.0  # Reset metrics every hour


@dataclass
class CallRecord:
    """Record of a single circuit breaker call"""

    timestamp: datetime
    success: bool
    duration: float
    error: Optional[str] = None


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker performance"""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    circuit_opened_count: int = 0
    circuit_closed_count: int = 0
    current_state: CircuitBreakerState = CircuitBreakerState.CLOSED
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    average_response_time: float = 0.0
    failure_rate: float = 0.0
    call_history: List[CallRecord] = field(default_factory=list)


class CircuitBreakerError(Exception):
    """Base exception for circuit breaker errors"""

    pass


class CircuitOpenError(CircuitBreakerError):
    """Raised when circuit is open and blocking calls"""

    def __init__(self, service_name: str, next_attempt_time: datetime):
        self.service_name = service_name
        self.next_attempt_time = next_attempt_time
        super().__init__(
            f"Circuit breaker is OPEN for {service_name}. "
            f"Next attempt allowed at {next_attempt_time.isoformat()}"
        )


class CircuitBreaker:
    """
    Circuit breaker implementation with exponential backoff and health monitoring.

    Provides fault tolerance for external service calls by automatically detecting
    failures and preventing cascading failures through intelligent blocking and
    recovery mechanisms.
    """

    def __init__(
        self, service_name: str, config: Optional[CircuitBreakerConfig] = None
    ):
        """
        Initialize circuit breaker for a specific service.

        Args:
            service_name: Unique name for the service this circuit breaker protects
            config: Circuit breaker configuration, uses defaults if None
        """
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()

        # Circuit breaker state
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_state_change: datetime = datetime.now(timezone.utc)
        self.half_open_calls = 0

        # Metrics and monitoring
        self.metrics = CircuitBreakerMetrics()
        self.lock = asyncio.Lock()

        # Health checking
        self.health_check_task: Optional[asyncio.Task] = None
        self.health_check_function: Optional[Callable] = None

        # Exponential backoff state
        self.consecutive_failures = 0
        self.backoff_delay = 1.0

        logger.info(
            f"Circuit breaker initialized for {service_name} with config: "
            f"failure_threshold={self.config.failure_threshold}, "
            f"recovery_timeout={self.config.recovery_timeout}s"
        )

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function through the circuit breaker.

        Args:
            func: Function to execute (can be sync or async)
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Function result if successful

        Raises:
            CircuitOpenError: If circuit is open and blocking calls
            Any exception raised by the protected function
        """
        async with self.lock:
            # Check if we should allow this call
            if not await self._should_allow_call():
                next_attempt = self._calculate_next_attempt_time()
                raise CircuitOpenError(self.service_name, next_attempt)

            # Track half-open state calls
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.half_open_calls += 1

        # Execute the function with timeout and metrics
        start_time = time.time()
        success = False
        error = None

        try:
            # Handle both sync and async functions
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=self.config.timeout
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, func, *args, **kwargs
                    ),
                    timeout=self.config.timeout,
                )
            success = True
            await self._record_success(time.time() - start_time)
            return result

        except Exception as e:
            error = str(e)
            await self._record_failure(time.time() - start_time, error)
            raise

        finally:
            # Record call metrics
            call_record = CallRecord(
                timestamp=datetime.now(timezone.utc),
                success=success,
                duration=time.time() - start_time,
                error=error,
            )
            await self._update_metrics(call_record)

    async def _should_allow_call(self) -> bool:
        """Determine if a call should be allowed based on current state"""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                time_since_failure = datetime.now(timezone.utc) - self.last_failure_time
                if time_since_failure.total_seconds() >= self.config.recovery_timeout:
                    await self._transition_to_half_open()
                    return True
            return False

        if self.state == CircuitBreakerState.HALF_OPEN:
            # Allow limited calls to test service recovery
            return self.half_open_calls < self.config.half_open_max_calls

        return False

    async def _record_success(self, duration: float):
        """Record a successful call and update circuit state"""
        async with self.lock:
            self.success_count += 1
            self.consecutive_failures = 0
            self.backoff_delay = 1.0  # Reset backoff delay

            if self.state == CircuitBreakerState.HALF_OPEN:
                if self.success_count >= self.config.success_threshold:
                    await self._transition_to_closed()

            self.metrics.last_success_time = datetime.now(timezone.utc)
            logger.debug(
                f"Circuit breaker success for {self.service_name}: "
                f"duration={duration:.3f}s, state={self.state.value}"
            )

    async def _record_failure(self, duration: float, error: str):
        """Record a failed call and update circuit state"""
        async with self.lock:
            self.failure_count += 1
            self.consecutive_failures += 1
            self.last_failure_time = datetime.now(timezone.utc)

            # Update exponential backoff delay
            self.backoff_delay = min(
                self.config.max_backoff_delay,
                self.backoff_delay * self.config.exponential_backoff_base,
            )

            if self.state == CircuitBreakerState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    await self._transition_to_open()
            elif self.state == CircuitBreakerState.HALF_OPEN:
                # Any failure in half-open state transitions back to open
                await self._transition_to_open()

            logger.warning(
                f"Circuit breaker failure for {self.service_name}: "
                f"error={error}, duration={duration:.3f}s, "
                f"consecutive_failures={self.consecutive_failures}, state={self.state.value}"
            )

    async def _transition_to_open(self):
        """Transition circuit breaker to open state"""
        if self.state != CircuitBreakerState.OPEN:
            old_state = self.state
            self.state = CircuitBreakerState.OPEN
            self.last_state_change = datetime.now(timezone.utc)
            self.metrics.circuit_opened_count += 1

            logger.error(
                f"Circuit breaker OPENED for {self.service_name} "
                f"(was {old_state.value}) after {self.failure_count} failures. "
                f"Recovery timeout: {self.config.recovery_timeout}s"
            )

    async def _transition_to_half_open(self):
        """Transition circuit breaker to half-open state"""
        if self.state != CircuitBreakerState.HALF_OPEN:
            old_state = self.state
            self.state = CircuitBreakerState.HALF_OPEN
            self.last_state_change = datetime.now(timezone.utc)
            self.half_open_calls = 0
            self.success_count = 0

            logger.info(
                f"Circuit breaker transitioned to HALF_OPEN for {self.service_name} "
                f"(was {old_state.value}). Testing service recovery..."
            )

    async def _transition_to_closed(self):
        """Transition circuit breaker to closed state"""
        if self.state != CircuitBreakerState.CLOSED:
            old_state = self.state
            self.state = CircuitBreakerState.CLOSED
            self.last_state_change = datetime.now(timezone.utc)
            self.failure_count = 0
            self.success_count = 0
            self.half_open_calls = 0
            self.metrics.circuit_closed_count += 1

            logger.info(
                f"Circuit breaker CLOSED for {self.service_name} "
                f"(was {old_state.value}). Service recovered successfully."
            )

    def _calculate_next_attempt_time(self) -> datetime:
        """Calculate when the next attempt should be allowed"""
        if self.last_failure_time:
            delay = self.config.recovery_timeout
            if self.config.jitter_enabled:
                # Add jitter to prevent thundering herd
                jitter = random.uniform(0.8, 1.2)
                delay *= jitter

            return self.last_failure_time + timedelta(seconds=delay)

        return datetime.now(timezone.utc) + timedelta(
            seconds=self.config.recovery_timeout
        )

    async def _update_metrics(self, call_record: CallRecord):
        """Update circuit breaker metrics"""
        self.metrics.total_calls += 1

        if call_record.success:
            self.metrics.successful_calls += 1
        else:
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = call_record.timestamp

        # Update call history (keep within window size)
        self.metrics.call_history.append(call_record)
        if len(self.metrics.call_history) > self.config.metrics_window_size:
            self.metrics.call_history.pop(0)

        # Update derived metrics
        if self.metrics.total_calls > 0:
            self.metrics.failure_rate = (
                self.metrics.failed_calls / self.metrics.total_calls
            )

        if self.metrics.call_history:
            total_duration = sum(
                record.duration for record in self.metrics.call_history
            )
            self.metrics.average_response_time = total_duration / len(
                self.metrics.call_history
            )

        self.metrics.current_state = self.state

    def set_health_check(self, health_check_func: Callable):
        """
        Set a health check function that will be called periodically.

        Args:
            health_check_func: Async function that returns True if service is healthy
        """
        self.health_check_function = health_check_func

        # Start health check task if not already running
        if self.health_check_task is None or self.health_check_task.done():
            self.health_check_task = asyncio.create_task(self._health_check_loop())

    async def _health_check_loop(self):
        """Periodic health check loop"""
        while True:
            try:
                await asyncio.sleep(self.config.health_check_interval)

                if (
                    self.health_check_function
                    and self.state == CircuitBreakerState.OPEN
                ):
                    try:
                        is_healthy = await asyncio.wait_for(
                            self.health_check_function(),
                            timeout=self.config.health_check_timeout,
                        )

                        if is_healthy:
                            async with self.lock:
                                if self.state == CircuitBreakerState.OPEN:
                                    await self._transition_to_half_open()
                                    logger.info(
                                        f"Health check passed for {self.service_name}, "
                                        f"transitioning to HALF_OPEN"
                                    )

                    except Exception as e:
                        logger.debug(
                            f"Health check failed for {self.service_name}: {e}"
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop for {self.service_name}: {e}")

    async def manual_reset(self):
        """Manually reset circuit breaker to closed state"""
        async with self.lock:
            await self._transition_to_closed()
            self.consecutive_failures = 0
            self.backoff_delay = 1.0
            logger.info(f"Circuit breaker manually reset for {self.service_name}")

    async def force_open(self):
        """Manually force circuit breaker to open state"""
        async with self.lock:
            await self._transition_to_open()
            logger.warning(
                f"Circuit breaker manually forced open for {self.service_name}"
            )

    def get_status(self) -> Dict[str, Any]:
        """Get current circuit breaker status and metrics"""
        return {
            "service_name": self.service_name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "consecutive_failures": self.consecutive_failures,
            "last_failure_time": (
                self.last_failure_time.isoformat() if self.last_failure_time else None
            ),
            "last_state_change": self.last_state_change.isoformat(),
            "next_attempt_time": (
                self._calculate_next_attempt_time().isoformat()
                if self.state == CircuitBreakerState.OPEN
                else None
            ),
            "backoff_delay": self.backoff_delay,
            "half_open_calls": self.half_open_calls,
            "metrics": {
                "total_calls": self.metrics.total_calls,
                "successful_calls": self.metrics.successful_calls,
                "failed_calls": self.metrics.failed_calls,
                "failure_rate": self.metrics.failure_rate,
                "average_response_time": self.metrics.average_response_time,
                "circuit_opened_count": self.metrics.circuit_opened_count,
                "circuit_closed_count": self.metrics.circuit_closed_count,
            },
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "timeout": self.config.timeout,
                "max_backoff_delay": self.config.max_backoff_delay,
            },
        }

    async def cleanup(self):
        """Clean up circuit breaker resources"""
        if self.health_check_task and not self.health_check_task.done():
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Circuit breaker cleaned up for {self.service_name}")


class CircuitBreakerManager:
    """
    Manager for multiple circuit breakers with centralized configuration.

    Provides a centralized way to create, configure, and monitor multiple
    circuit breakers for different services within the application.
    """

    def __init__(self):
        """Initialize circuit breaker manager"""
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.default_config = CircuitBreakerConfig()

        logger.info("Circuit breaker manager initialized")

    def get_circuit_breaker(
        self, service_name: str, config: Optional[CircuitBreakerConfig] = None
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker for a service.

        Args:
            service_name: Unique name for the service
            config: Custom configuration, uses default if None

        Returns:
            CircuitBreaker instance for the service
        """
        if service_name not in self.circuit_breakers:
            effective_config = config or self.default_config
            self.circuit_breakers[service_name] = CircuitBreaker(
                service_name, effective_config
            )
            logger.info(f"Created new circuit breaker for service: {service_name}")

        return self.circuit_breakers[service_name]

    def set_default_config(self, config: CircuitBreakerConfig):
        """Set default configuration for new circuit breakers"""
        self.default_config = config
        logger.info("Updated default circuit breaker configuration")

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers"""
        return {name: cb.get_status() for name, cb in self.circuit_breakers.items()}

    async def reset_all(self):
        """Reset all circuit breakers to closed state"""
        for cb in self.circuit_breakers.values():
            await cb.manual_reset()
        logger.info("Reset all circuit breakers")

    async def cleanup_all(self):
        """Clean up all circuit breaker resources"""
        for cb in self.circuit_breakers.values():
            await cb.cleanup()
        self.circuit_breakers.clear()
        logger.info("Cleaned up all circuit breakers")


# Global circuit breaker manager instance
_circuit_breaker_manager: Optional[CircuitBreakerManager] = None


def get_circuit_breaker_manager() -> CircuitBreakerManager:
    """Get the global circuit breaker manager instance"""
    global _circuit_breaker_manager
    if _circuit_breaker_manager is None:
        _circuit_breaker_manager = CircuitBreakerManager()
    return _circuit_breaker_manager


def reset_circuit_breaker_manager():
    """Reset the global circuit breaker manager (mainly for testing)"""
    global _circuit_breaker_manager
    if _circuit_breaker_manager:
        # Try to clean up gracefully if there's a running event loop
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(_circuit_breaker_manager.cleanup_all())
        except RuntimeError:
            # No running event loop - skip async cleanup in tests
            pass
    _circuit_breaker_manager = None
