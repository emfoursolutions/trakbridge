# ABOUTME: Tests for plugins/sdk_wiring.py — wiring core services into the SDK runtime registry.
# ABOUTME: Verifies provider registration, idempotency, and real provider behavior.

import pytest

from trakbridge_sdk import runtime

from plugins.sdk_wiring import configure_sdk


class TestConfigureSdk:
    def test_registers_all_four_providers(self):
        configure_sdk()
        assert runtime._runtime.encryption_factory is not None
        assert runtime._runtime.plugin_metadata_lookup is not None
        assert runtime._runtime.circuit_breaker_factory is not None
        assert runtime._runtime.cot_service_lookup is not None

    def test_encryption_provider_returns_encryption_service(self):
        configure_sdk()
        from services.encryption_service import EncryptionService

        assert isinstance(runtime.get_encryption(), EncryptionService)

    def test_plugin_metadata_provider_queries_plugin_manager(self):
        configure_sdk()
        metadata = runtime.get_plugin_metadata("garmin")
        assert metadata is not None
        assert "config_fields" in metadata

    @pytest.mark.asyncio
    async def test_circuit_breaker_provider_builds_breaker(self):
        # Needs a running loop: the real CircuitBreaker registers async tasks
        configure_sdk()

        async def health():
            return True

        breaker = runtime.get_circuit_breaker("test_wiring_plugin", health)
        assert breaker is not None
        assert callable(breaker.call)

    def test_idempotent(self):
        configure_sdk()
        first = runtime._runtime.encryption_factory
        configure_sdk()
        assert runtime._runtime.encryption_factory is first
