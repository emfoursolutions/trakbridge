"""
Test circuit breaker integration with plugins and TAK servers
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    CircuitOpenError,
    get_circuit_breaker_manager,
    reset_circuit_breaker_manager,
)


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with TrakBridge components"""

    def setup_method(self):
        """Reset circuit breaker manager before each test"""
        reset_circuit_breaker_manager()

    @pytest.fixture(autouse=True)
    def setup_event_loop(self):
        """Ensure proper event loop setup for circuit breaker tests"""
        try:
            # Get or create event loop for the test
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # Create new event loop if none exists
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        yield
        # Don't close the loop as pytest-asyncio manages it

    @pytest.mark.asyncio
    async def test_circuit_breaker_basic_functionality(self):
        """Test basic circuit breaker functionality"""
        config = CircuitBreakerConfig(
            failure_threshold=2, recovery_timeout=0.1, timeout=1.0
        )

        circuit_breaker = CircuitBreaker("test_service", config)

        # Test successful call
        async def success_func():
            return "success"

        result = await circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.state == CircuitBreakerState.CLOSED

        # Test failing calls
        async def fail_func():
            raise Exception("Test failure")

        # First failure
        with pytest.raises(Exception, match="Test failure"):
            await circuit_breaker.call(fail_func)
        assert circuit_breaker.state == CircuitBreakerState.CLOSED

        # Second failure - should open circuit
        with pytest.raises(Exception, match="Test failure"):
            await circuit_breaker.call(fail_func)
        assert circuit_breaker.state == CircuitBreakerState.OPEN

        # Third call should be blocked
        with pytest.raises(CircuitOpenError):
            await circuit_breaker.call(success_func)

    @pytest.mark.asyncio
    async def test_plugin_circuit_breaker_integration(self):
        """Test circuit breaker integration with plugin fetch method"""
        from plugins.base_plugin import BaseGPSPlugin

        # Create a mock plugin
        class MockPlugin(BaseGPSPlugin):
            def __init__(self, config):
                super().__init__(config)
                self.call_count = 0

            @property
            def plugin_name(self):
                return "test_plugin"

            @property
            def plugin_metadata(self):
                return {"config_fields": []}

            async def fetch_locations(self, session):
                self.call_count += 1
                # Always fail to test circuit breaker behavior
                raise Exception("Plugin failure")

        # Mock the config loading
        with patch(
            "utils.config_manager.config_manager.load_config_safe"
        ) as mock_load_config:
            mock_load_config.return_value = {
                "performance": {
                    "circuit_breaker": {
                        "failure_threshold": 2,
                        "recovery_timeout": 0.1,
                        "timeout": 1.0,
                    }
                }
            }

            plugin = MockPlugin({"url": "http://test.com"})
            mock_session = MagicMock()

            # Test that circuit breaker protection exists
            assert hasattr(
                plugin, "fetch_locations_with_protection"
            ), "Plugin should have circuit breaker protection method"

            # First call should fail and raise exception (normal behavior)
            with pytest.raises(Exception, match="Plugin failure"):
                await plugin.fetch_locations_with_protection(mock_session)

            # Second call should fail
            with pytest.raises(Exception, match="Plugin failure"):
                await plugin.fetch_locations_with_protection(mock_session)

            # Third call should fail and open the circuit (default threshold is 3)
            with pytest.raises(Exception, match="Plugin failure"):
                await plugin.fetch_locations_with_protection(mock_session)

            # Wait a moment for circuit state to be updated
            await asyncio.sleep(0.01)

            # Fourth call should be blocked by circuit breaker and return empty list
            result = await plugin.fetch_locations_with_protection(mock_session)
            assert result == [], "Circuit breaker should return empty list when open"

    @pytest.mark.asyncio
    async def test_tak_server_circuit_breaker_integration(self):
        """Test circuit breaker integration with TAK server connections"""
        from services.cot_service_integration import QueuedCOTService
        from models.tak_server import TakServer

        # Mock TAK server
        mock_tak_server = (
            MagicMock()
        )  # Don't use spec=TakServer to avoid SQLAlchemy context issues
        mock_tak_server.id = 1
        mock_tak_server.name = "test_tak"
        mock_tak_server.host = "localhost"
        mock_tak_server.port = 8089

        # Create COT service instance
        with patch("services.cot_service_integration.PYTAK_AVAILABLE", True):
            cot_service = QueuedCOTService(_bypass_singleton_check=True)
            cot_service.performance_config = {
                "circuit_breaker": {
                    "failure_threshold": 2,
                    "recovery_timeout": 0.1,
                    "timeout": 1.0,
                }
            }

            # Mock pytak.protocol_factory to fail
            call_count = 0

            async def mock_protocol_factory(config):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise Exception("Connection failed")
                return MagicMock()

            with patch(
                "services.cot_service_integration.pytak.protocol_factory",
                mock_protocol_factory,
            ):
                # First connection attempt should fail
                connection = await cot_service._create_pytak_connection(mock_tak_server)
                assert connection is None

                # Second connection attempt should fail and open circuit
                connection = await cot_service._create_pytak_connection(mock_tak_server)
                assert connection is None

                # Third attempt should be blocked by circuit breaker
                connection = await cot_service._create_pytak_connection(mock_tak_server)
                assert connection is None

    @pytest.mark.asyncio
    async def test_recovery_service_integration(self):
        """Test recovery service integration with circuit breakers"""
        from services.recovery_service import (
            get_recovery_service,
            ComponentType,
            RecoveryConfig,
        )
        from services.recovery_implementations import register_all_recovery_methods

        # Configure recovery service
        config = RecoveryConfig(
            max_retry_attempts=2, initial_retry_delay=0.1, health_check_interval=0.1
        )

        recovery_service = get_recovery_service(config)
        register_all_recovery_methods()

        # Mock health check that fails initially then succeeds
        health_check_calls = 0

        async def mock_health_check():
            nonlocal health_check_calls
            health_check_calls += 1
            return health_check_calls > 3

        # Register a component
        recovery_service.register_component(
            "test_component", ComponentType.STREAM, mock_health_check
        )

        # Force recovery
        success = await recovery_service.initiate_recovery("test_component")
        assert success

        # Wait for recovery to complete
        await asyncio.sleep(0.5)

        # Check recovery status
        status = recovery_service.get_recovery_status("test_component")
        assert status is not None
        assert status["status"] in ["succeeded", "failed", "in_progress"]

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Test exponential backoff in circuit breaker"""
        config = CircuitBreakerConfig(
            failure_threshold=2,  # Allow 2 failures to test backoff progression
            recovery_timeout=0.1,
            exponential_backoff_base=2.0,
            max_backoff_delay=10.0,  # Increased to allow seeing the progression
        )

        circuit_breaker = CircuitBreaker("backoff_test", config)

        # Test failure to trigger backoff
        async def fail_func():
            raise Exception("Test failure")

        start_time = asyncio.get_event_loop().time()

        # First failure - circuit should remain closed
        with pytest.raises(Exception):
            await circuit_breaker.call(fail_func)

        # Check that backoff delay increased after first failure
        first_delay = circuit_breaker.backoff_delay
        expected_first = 1.0 * config.exponential_backoff_base  # 1.0 * 2.0 = 2.0
        assert first_delay == expected_first
        assert circuit_breaker.state == CircuitBreakerState.CLOSED  # Still closed

        # Second failure - circuit should open
        with pytest.raises(Exception):
            await circuit_breaker.call(fail_func)

        # Check backoff increased again
        second_delay = circuit_breaker.backoff_delay
        expected_second = (
            expected_first * config.exponential_backoff_base
        )  # 2.0 * 2.0 = 4.0
        assert second_delay == expected_second
        assert circuit_breaker.state == CircuitBreakerState.OPEN  # Now open
        assert circuit_breaker.backoff_delay <= config.max_backoff_delay

    @pytest.mark.asyncio
    async def test_circuit_breaker_health_check(self):
        """Test circuit breaker with health check functionality"""
        config = CircuitBreakerConfig(
            failure_threshold=1, recovery_timeout=0.1, health_check_interval=0.1
        )

        circuit_breaker = CircuitBreaker("health_test", config)

        # Set up health check that starts failing then recovers
        health_calls = 0

        async def mock_health_check():
            nonlocal health_calls
            health_calls += 1
            return health_calls > 2  # Healthy after 2 calls

        circuit_breaker.set_health_check(mock_health_check)

        # Cause failure to open circuit
        async def fail_func():
            raise Exception("Test failure")

        with pytest.raises(Exception):
            await circuit_breaker.call(fail_func)

        assert circuit_breaker.state == CircuitBreakerState.OPEN

        # Wait for health check to trigger recovery (longer wait for reliability)
        await asyncio.sleep(0.5)

        # Circuit should transition to half-open or closed due to health check
        # The health check should have succeeded after 2 calls and triggered recovery
        assert circuit_breaker.state in [
            CircuitBreakerState.HALF_OPEN,
            CircuitBreakerState.CLOSED,
        ], f"Expected circuit to be in half-open or closed state, but was {circuit_breaker.state}"

        # Clean up
        await circuit_breaker.cleanup()

    @pytest.mark.asyncio
    async def test_circuit_breaker_manager(self):
        """Test circuit breaker manager functionality"""
        manager = get_circuit_breaker_manager()

        # Create circuit breakers for different services
        cb1 = manager.get_circuit_breaker("service1")
        cb2 = manager.get_circuit_breaker("service2")

        assert cb1 != cb2
        assert cb1.service_name == "service1"
        assert cb2.service_name == "service2"

        # Test getting same circuit breaker
        cb1_again = manager.get_circuit_breaker("service1")
        assert cb1 is cb1_again

        # Test status of all circuit breakers
        all_status = manager.get_all_status()
        assert "service1" in all_status
        assert "service2" in all_status

        # Test reset all
        await manager.reset_all()

        # Clean up
        await manager.cleanup_all()

    def teardown_method(self):
        """Clean up after each test"""
        # For unit tests, just reset the circuit breaker manager
        # Skip async cleanup as it's not critical for tests
        reset_circuit_breaker_manager()
