# ABOUTME: Factory building circuit breakers for plugins, injected into the SDK runtime registry.
# ABOUTME: Loads performance.yaml settings and translates core CircuitOpenError to the SDK's type.

from typing import Any, Callable

from trakbridge_sdk import CircuitOpenError as SdkCircuitOpenError

from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


class _BreakerAdapter:
    """Wraps a core CircuitBreaker so SDK code only ever sees SDK exception types."""

    def __init__(self, breaker: Any):
        self._breaker = breaker

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        from services.circuit_breaker import CircuitOpenError as CoreCircuitOpenError

        try:
            return await self._breaker.call(func, *args, **kwargs)
        except CoreCircuitOpenError as e:
            raise SdkCircuitOpenError(str(e)) from e


def make_plugin_circuit_breaker(plugin_name: str, health_check: Callable) -> Any:
    """Build a configured circuit breaker for a plugin.

    Registered with trakbridge_sdk.configure(circuit_breaker=...); the SDK
    calls this lazily the first time a plugin needs protection.
    """
    from services.circuit_breaker import (
        CircuitBreakerConfig,
        get_circuit_breaker_manager,
    )

    cb_config = {}
    try:
        from config.base import get_config_loader

        # performance.yaml has no schema; skip schema validation.
        perf_config = (
            get_config_loader().load_config_safe(
                "performance.yaml", validate=False
            )
            or {}
        )
        cb_config = perf_config.get("circuit_breaker", {}) or {}
    except Exception as e:
        logger.debug(f"Could not load circuit breaker config: {e}, using defaults")
        cb_config = {}

    circuit_config = CircuitBreakerConfig(
        failure_threshold=cb_config.get("failure_threshold", 3),
        recovery_timeout=cb_config.get("recovery_timeout", 60.0),
        timeout=cb_config.get("timeout", 30.0),
        half_open_max_calls=cb_config.get("half_open_max_calls", 5),
        success_threshold=cb_config.get("success_threshold", 3),
        health_check_interval=cb_config.get("health_check_interval", 30.0),
    )

    manager = get_circuit_breaker_manager()
    breaker = manager.get_circuit_breaker(f"plugin_{plugin_name}", circuit_config)
    breaker.set_health_check(health_check)

    return _BreakerAdapter(breaker)
