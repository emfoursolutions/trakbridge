"""
ABOUTME: Unit tests for parallel processing fallback mechanisms in Phase 1B  
ABOUTME: Tests follow TDD principles - all tests initially FAIL until fallback system is implemented
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from services.cot_service import get_cot_service
from tests.fixtures.mock_location_data import generate_performance_test_datasets


class TestFallbackMechanisms:
    """
    Phase 1B: Fallback & Error Handling Tests
    All tests should FAIL initially until fallback mechanisms are implemented
    """

    @pytest.fixture
    def cot_service(self):
        """Create COT service instance for testing"""
        service = get_cot_service()
        # Set up for fallback testing
        service.parallel_config = {
            "enabled": True,
            "batch_size_threshold": 10,
            "fallback_on_error": True,
            "enable_performance_logging": True,
        }
        return service

    @pytest.fixture
    def performance_datasets(self):
        """Load standardized test datasets"""
        return generate_performance_test_datasets()

    @pytest.mark.asyncio
    async def test_graceful_fallback_to_serial_on_parallel_error(
        self, cot_service, performance_datasets
    ):
        """
        Test that parallel processing failures automatically fallback to serial
        REQUIREMENT: Graceful fallback to serial processing on error
        STATUS: WILL FAIL - fallback mechanism doesn't exist
        """
        large_dataset = performance_datasets["large"]  # 300 points
        cot_type = "a-f-G-U-C"
        stale_time = 300
        cot_type_mode = "stream"

        # Mock parallel processing to raise an exception
        async def failing_parallel(*args, **kwargs):
            raise RuntimeError("Simulated parallel processing error")

        # Mock serial processing to succeed
        async def working_serial(*args, **kwargs):
            return [b"<event>serial_fallback</event>"] * len(args[0])

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=failing_parallel
        )
        cot_service._create_pytak_events = AsyncMock(side_effect=working_serial)

        # Should automatically fallback to serial and succeed
        # The fallback logic is built into create_cot_events when parallel processing fails
        result = await cot_service.create_cot_events(
            large_dataset, cot_type, stale_time, cot_type_mode
        )

        assert result is not None, "Should return result even after fallback"
        assert len(result) == 300, "Should process all events via serial fallback"

        # Verify parallel was attempted first
        cot_service._create_parallel_pytak_events.assert_called_once()
        # Verify fallback to serial occurred
        cot_service._create_pytak_events.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_disabled_propagates_errors(
        self, cot_service, performance_datasets
    ):
        """
        Test that when fallback is disabled, errors are propagated
        STATUS: WILL FAIL - fallback configuration doesn't exist
        """
        large_dataset = performance_datasets["large"]

        # Disable fallback
        cot_service.parallel_config["fallback_on_error"] = False

        # Mock parallel processing to fail
        async def failing_parallel(*args, **kwargs):
            raise RuntimeError("Simulated parallel processing error")

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=failing_parallel
        )
        cot_service._create_pytak_events = AsyncMock()  # Should not be called

        # Should propagate the error instead of falling back
        with pytest.raises(RuntimeError, match="Simulated parallel processing error"):
            await cot_service.create_cot_events(
                large_dataset, "a-f-G-U-C", 300, "stream"
            )

        # Verify serial was not called (no fallback)
        cot_service._create_pytak_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_maintains_data_integrity(
        self, cot_service, performance_datasets
    ):
        """
        Test that fallback produces identical results to direct serial processing
        STATUS: WILL FAIL - fallback with integrity checking doesn't exist
        """
        medium_dataset = performance_datasets["medium"]  # 50 points
        cot_type = "a-f-G-U-C"
        stale_time = 300
        cot_type_mode = "stream"

        # Get expected result from direct serial processing
        expected_result = await cot_service._create_pytak_events(
            medium_dataset, cot_type, stale_time, cot_type_mode
        )

        # Mock parallel processing to fail
        async def failing_parallel(*args, **kwargs):
            raise Exception("Parallel processing failed")

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=failing_parallel
        )

        # Test fallback result
        fallback_result = await cot_service.create_cot_events(
            medium_dataset, cot_type, stale_time, cot_type_mode
        )

        # Results should be identical
        assert len(fallback_result) == len(
            expected_result
        ), "Fallback should produce same number of events"
        assert set(fallback_result) == set(
            expected_result
        ), "Fallback should produce identical events"

    @pytest.mark.xfail(
        reason="TDD test - will pass when RC6 parallel config is implemented"
    )
    def test_fallback_error_logging(self, cot_service, performance_datasets):
        """
        Test that fallback events are properly logged for monitoring
        STATUS: WILL FAIL - fallback logging doesn't exist
        """
        large_dataset = performance_datasets["large"]

        # Use the actual logger from the module
        import services.cot_service_integration

        with patch.object(services.cot_service_integration, "logger") as mock_logger:
            # Mock parallel processing to fail
            async def failing_parallel(*args, **kwargs):
                raise ValueError("Mock parallel error")

            cot_service._create_parallel_pytak_events = AsyncMock(
                side_effect=failing_parallel
            )
            cot_service._create_pytak_events = AsyncMock(return_value=[b"fallback"])

            # Trigger fallback
            asyncio.run(
                cot_service.create_cot_events(large_dataset, "a-f-G-U-C", 300, "stream")
            )

            # Should log the fallback event
            assert any(
                "falling back" in str(call).lower()
                for call in mock_logger.warning.call_args_list
            ), "Should log fallback warning"
            assert any(
                "parallel processing failed" in str(call).lower()
                for call in mock_logger.warning.call_args_list
            ), "Should log the original error as warning"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="TDD test - will pass when RC6 parallel config is implemented"
    )
    async def test_partial_failure_handling(self, cot_service):
        """
        Test handling of partial failures in parallel processing
        STATUS: WILL FAIL - partial failure detection doesn't exist
        """
        # Create dataset that might cause partial failures
        problematic_dataset = [
            {"name": "good1", "lat": 40.0, "lon": -74.0, "uid": "good-001"},
            {
                "name": "bad1",
                "lat": None,
                "lon": -74.0,
                "uid": "bad-001",
            },  # Missing lat
            {"name": "good2", "lat": 41.0, "lon": -75.0, "uid": "good-002"},
        ]

        # Force parallel processing by adjusting config
        original_threshold = cot_service.parallel_config.get("batch_size_threshold", 10)
        cot_service.parallel_config["batch_size_threshold"] = (
            2  # Lower threshold to force parallel
        )

        # Mock partial success scenario
        async def partially_failing_parallel(locations, *args, **kwargs):
            # Return results for good locations only
            results = []
            for loc in locations:
                if loc["lat"] is not None:
                    results.append(b"<event>good</event>")
            return results

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=partially_failing_parallel
        )

        try:
            result = await cot_service.create_cot_events(
                problematic_dataset, "a-f-G-U-C", 300, "stream"
            )

            # Should handle partial success gracefully
            assert len(result) == 2, "Should return events for good locations only"
            assert all(
                isinstance(event, bytes) for event in result
            ), "All results should be valid events"
        finally:
            # Restore original threshold
            cot_service.parallel_config["batch_size_threshold"] = original_threshold

    @pytest.mark.asyncio
    async def test_timeout_fallback(self, cot_service, performance_datasets):
        """
        Test that processing timeouts trigger fallback to serial
        STATUS: WILL FAIL - timeout handling doesn't exist
        """
        large_dataset = performance_datasets["large"]

        # Configure short timeout
        cot_service.parallel_config["processing_timeout"] = 0.1  # 100ms timeout

        # Mock parallel processing to raise TimeoutError directly
        async def timeout_parallel(*args, **kwargs):
            raise asyncio.TimeoutError("Simulated timeout")

        # Mock fast serial processing (fallback)
        async def fast_serial(*args, **kwargs):
            return [b"fast"] * len(args[0])

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=timeout_parallel
        )
        cot_service._create_pytak_events = AsyncMock(side_effect=fast_serial)

        result = await cot_service.create_cot_events(
            large_dataset, "a-f-G-U-C", 300, "stream"
        )

        # Should fallback due to timeout
        assert len(result) == 300, "Should complete via serial fallback"
        cot_service._create_pytak_events.assert_called_once()  # Fallback occurred

    def test_fallback_statistics_tracking(self, cot_service):
        """
        Test that fallback events are tracked for monitoring and alerting
        STATUS: WILL FAIL - statistics tracking doesn't exist
        """
        # Initially no fallbacks
        stats = cot_service.get_fallback_statistics()
        assert stats["total_fallbacks"] == 0, "Should start with zero fallbacks"
        assert stats["fallback_rate"] == 0.0, "Should have zero fallback rate initially"

        # Simulate some fallbacks
        cot_service.record_fallback_event("parallel_error", "RuntimeError: Test error")
        cot_service.record_fallback_event("timeout", "Processing timeout exceeded")

        updated_stats = cot_service.get_fallback_statistics()
        assert updated_stats["total_fallbacks"] == 2, "Should track fallback count"
        assert (
            "parallel_error" in updated_stats["fallback_reasons"]
        ), "Should categorize fallback reasons"
        assert (
            "timeout" in updated_stats["fallback_reasons"]
        ), "Should track different fallback types"

    @pytest.mark.asyncio
    async def test_fallback_performance_impact(self, cot_service, performance_datasets):
        """
        Test that fallback doesn't significantly impact performance
        STATUS: WILL FAIL - performance impact measurement doesn't exist
        """
        medium_dataset = performance_datasets["medium"]

        # Time direct serial processing
        import time

        start_time = time.perf_counter()
        serial_result = await cot_service._create_pytak_events(
            medium_dataset, "a-f-G-U-C", 300, "stream"
        )
        serial_time = time.perf_counter() - start_time

        # Time fallback processing (with fast mock failure)
        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=RuntimeError("Mock failure for fallback test")
        )

        start_time = time.perf_counter()
        fallback_result = await cot_service.create_cot_events(
            medium_dataset, "a-f-G-U-C", 300, "stream"
        )
        fallback_time = time.perf_counter() - start_time

        # Fallback should not be significantly slower (allow more overhead in test environment)
        overhead_ratio = fallback_time / serial_time
        assert (
            overhead_ratio
            < 10.0  # Relaxed for test environment where timing can be unpredictable
        ), f"Fallback overhead too high: {overhead_ratio:.2f}x slower than direct serial"

        # Results should be identical
        assert len(fallback_result) == len(
            serial_result
        ), "Should produce same number of events"

    def test_fallback_recovery_detection(self, cot_service):
        """
        Test that the system can detect when parallel processing recovers
        STATUS: WILL FAIL - recovery detection doesn't exist
        """
        # Simulate several failures followed by recovery
        cot_service.record_fallback_event("parallel_error", "Error 1")
        cot_service.record_fallback_event("parallel_error", "Error 2")
        cot_service.record_fallback_event("parallel_error", "Error 3")

        # System should be considered unhealthy
        assert (
            not cot_service.is_parallel_processing_healthy()
        ), "Should detect unhealthy parallel processing after multiple failures"

        # Simulate successful parallel processing
        cot_service.record_successful_parallel_processing()
        cot_service.record_successful_parallel_processing()
        cot_service.record_successful_parallel_processing()

        # System should recover
        assert (
            cot_service.is_parallel_processing_healthy()
        ), "Should detect recovery after successful parallel processing"

    @pytest.mark.asyncio
    async def test_circuit_breaker_pattern(self, cot_service, performance_datasets):
        """
        Test circuit breaker pattern to avoid repeated failures
        STATUS: WILL FAIL - circuit breaker doesn't exist
        """
        large_dataset = performance_datasets["large"]

        # Configure circuit breaker
        cot_service.parallel_config["circuit_breaker"] = {
            "failure_threshold": 3,
            "recovery_timeout": 1.0,
        }

        # Mock consistently failing parallel processing
        failure_count = 0

        async def consistently_failing_parallel(*args, **kwargs):
            nonlocal failure_count
            failure_count += 1
            raise RuntimeError(f"Consistent failure #{failure_count}")

        cot_service._create_parallel_pytak_events = AsyncMock(
            side_effect=consistently_failing_parallel
        )
        cot_service._create_pytak_events = AsyncMock(return_value=[b"serial"] * 300)

        # First few attempts should try parallel and fallback
        for i in range(3):
            await cot_service.create_cot_events(
                large_dataset, "a-f-G-U-C", 300, "stream"
            )

        # After threshold failures, should open circuit and skip parallel
        assert (
            cot_service.is_circuit_breaker_open()
        ), "Circuit breaker should be open after repeated failures"

        # Next attempt should skip parallel entirely
        cot_service._create_parallel_pytak_events.reset_mock()
        await cot_service.create_cot_events(large_dataset, "a-f-G-U-C", 300, "stream")

        # Parallel should not have been attempted (circuit open)
        cot_service._create_parallel_pytak_events.assert_not_called()


if __name__ == "__main__":
    # Run tests to verify they all FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])
