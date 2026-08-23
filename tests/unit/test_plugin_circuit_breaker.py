# ABOUTME: Tests for services/plugin_circuit_breaker.py — the core-side circuit breaker factory
# ABOUTME: injected into the SDK runtime registry, including CircuitOpenError translation.

from unittest.mock import patch

import pytest

from trakbridge_sdk import CircuitOpenError as SdkCircuitOpenError

from services.plugin_circuit_breaker import make_plugin_circuit_breaker


async def _healthy():
    return True


class TestMakePluginCircuitBreaker:
    @pytest.mark.asyncio
    async def test_returns_breaker_with_async_call(self):
        # Real manager path needs a running event loop (matches production:
        # the SDK invokes the factory from async fetch context)
        breaker = make_plugin_circuit_breaker("test_factory_plugin", _healthy)
        assert breaker is not None
        assert callable(breaker.call)

    def test_reads_top_level_circuit_breaker_config(self):
        with patch("config.base.get_config_loader") as mock_get_loader:
            mock_get_loader.return_value.load_config_safe.return_value = {
                "circuit_breaker": {"failure_threshold": 7}
            }
            with patch(
                "services.circuit_breaker.get_circuit_breaker_manager"
            ) as mock_manager:
                make_plugin_circuit_breaker("test_cfg_plugin", _healthy)
                config = mock_manager.return_value.get_circuit_breaker.call_args[0][1]
                assert config.failure_threshold == 7

    def test_config_load_failure_falls_back_to_defaults(self):
        with patch("config.base.get_config_loader") as mock_get_loader:
            mock_get_loader.return_value.load_config_safe.side_effect = RuntimeError(
                "no config"
            )
            with patch(
                "services.circuit_breaker.get_circuit_breaker_manager"
            ) as mock_manager:
                make_plugin_circuit_breaker("test_default_plugin", _healthy)
                config = mock_manager.return_value.get_circuit_breaker.call_args[0][1]
                assert config.failure_threshold == 3

    def test_breaker_registered_under_plugin_prefixed_name(self):
        with patch(
            "services.circuit_breaker.get_circuit_breaker_manager"
        ) as mock_manager:
            make_plugin_circuit_breaker("garmin", _healthy)
            name = mock_manager.return_value.get_circuit_breaker.call_args[0][0]
            assert name == "plugin_garmin"

    def test_health_check_is_wired(self):
        with patch(
            "services.circuit_breaker.get_circuit_breaker_manager"
        ) as mock_manager:
            make_plugin_circuit_breaker("garmin", _healthy)
            inner = mock_manager.return_value.get_circuit_breaker.return_value
            inner.set_health_check.assert_called_once_with(_healthy)

    @pytest.mark.asyncio
    async def test_open_circuit_translates_to_sdk_error(self):
        from datetime import datetime, timezone

        from services.circuit_breaker import CircuitOpenError as CoreCircuitOpenError

        class OpenInner:
            async def call(self, func, *args, **kwargs):
                raise CoreCircuitOpenError("plugin_garmin", datetime.now(timezone.utc))

            def set_health_check(self, hc):
                pass

        with patch(
            "services.circuit_breaker.get_circuit_breaker_manager"
        ) as mock_manager:
            mock_manager.return_value.get_circuit_breaker.return_value = OpenInner()
            breaker = make_plugin_circuit_breaker("garmin", _healthy)

        with pytest.raises(SdkCircuitOpenError):
            await breaker.call(_healthy)

    @pytest.mark.asyncio
    async def test_successful_call_passes_through(self):
        class PassInner:
            async def call(self, func, *args, **kwargs):
                return await func(*args, **kwargs)

            def set_health_check(self, hc):
                pass

        with patch(
            "services.circuit_breaker.get_circuit_breaker_manager"
        ) as mock_manager:
            mock_manager.return_value.get_circuit_breaker.return_value = PassInner()
            breaker = make_plugin_circuit_breaker("garmin", _healthy)

        assert await breaker.call(_healthy) is True

    @pytest.mark.asyncio
    async def test_other_exceptions_propagate_unchanged(self):
        class FailInner:
            async def call(self, func, *args, **kwargs):
                raise ValueError("boom")

            def set_health_check(self, hc):
                pass

        with patch(
            "services.circuit_breaker.get_circuit_breaker_manager"
        ) as mock_manager:
            mock_manager.return_value.get_circuit_breaker.return_value = FailInner()
            breaker = make_plugin_circuit_breaker("garmin", _healthy)

        with pytest.raises(ValueError, match="boom"):
            await breaker.call(_healthy)
