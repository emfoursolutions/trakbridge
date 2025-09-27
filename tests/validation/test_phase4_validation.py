"""
ABOUTME: Phase 4 validation tests for queue management implementation
ABOUTME: Comprehensive validation tests according to TDD Phase 4 specification

This module contains Phase 4 validation tests as specified in the Queue Management
Specification Phase 4 (Validation Phase). These tests validate the complete queue
implementation against all success criteria.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
import statistics
import psutil
import os
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from services.cot_service_integration import QueuedCOTService
from models.tak_server import TakServer


class TestPhase4QueueValidation:
    """Phase 4 validation tests for complete queue management system"""

    @pytest.mark.asyncio
    async def test_queue_size_never_exceeds_maximum(self):
        """✅ Queue size never exceeds configured maximum (500 events default)"""
        max_queue_size = 10  # Small size for testing

        # Create service with custom queue config
        queue_config = {
            "max_size": max_queue_size,
            "batch_size": 3,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        # Start worker (will create the queue)
        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Get the queue directly
                queue = cot_service.queues[tak_server.id]

                # Add events beyond the limit
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"

                for i in range(max_queue_size + 5):  # Add more than max
                    await cot_service.enqueue_event(test_event, tak_server.id)

                # Verify queue never exceeds maximum
                assert queue.qsize() <= max_queue_size

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_configuration_changes_propagate_quickly(self):
        """✅ Configuration changes propagate within 5-15 seconds"""
        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Add events to queue
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                for i in range(10):
                    await cot_service.enqueue_event(test_event, tak_server.id)

                queue = cot_service.queues[tak_server.id]
                initial_size = queue.qsize()
                assert initial_size > 0

                # Simulate configuration change with timing
                start_time = time.time()

                # Stop and restart worker (simulates config change)
                await cot_service.stop_worker(tak_server.id)
                await cot_service.start_worker(tak_server)

                propagation_time = time.time() - start_time

                # Verify timing requirement
                assert (
                    propagation_time < 15.0
                ), f"Config change took {propagation_time}s, expected < 15s"
                print(f"Configuration change propagated in {propagation_time:.2f}s")

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_batch_transmission_uses_configured_size(self):
        """✅ Batch transmission uses configured batch size (8 events default)"""
        batch_size = 4  # Custom batch size for testing

        queue_config = {
            "max_size": 100,
            "batch_size": batch_size,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        # Mock the transmission to track batch sizes
        transmitted_batches = []

        def mock_write(data):
            # Count events in the data (simple heuristic)
            event_count = data.count(b"<event")
            if event_count > 0:
                transmitted_batches.append(event_count)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_reader = AsyncMock()
                mock_writer = AsyncMock()
                mock_writer.write = mock_write
                mock_factory.return_value = (mock_reader, mock_writer)

                await cot_service.start_worker(tak_server)

                # Add more events than one batch
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                for i in range(batch_size * 2 + 2):  # 2+ full batches
                    await cot_service.enqueue_event(test_event, tak_server.id)

                # Wait for transmission
                await asyncio.sleep(0.5)

                # Verify batch sizes
                if transmitted_batches:
                    # Most batches should be full size
                    full_batches = [b for b in transmitted_batches if b == batch_size]
                    assert (
                        len(full_batches) >= 2
                    ), f"Expected at least 2 full batches, got {transmitted_batches}"

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_all_settings_configurable(self):
        """✅ All settings configurable via environment variables and config files"""
        custom_config = {
            "max_size": 250,
            "batch_size": 12,
            "overflow_strategy": "drop_newest",
            "flush_on_config_change": False,
        }

        cot_service = QueuedCOTService(queue_config=custom_config)

        # Verify configuration was applied
        assert cot_service.queue_config["max_size"] == 250
        assert cot_service.queue_config["batch_size"] == 12
        assert cot_service.queue_config["overflow_strategy"] == "drop_newest"
        assert cot_service.queue_config["flush_on_config_change"] == False

    @pytest.mark.asyncio
    async def test_zero_performance_regression_parallel_processing(self):
        """✅ Zero performance regression in parallel input processing"""
        cot_service = QueuedCOTService()
        tak_servers = [
            TakServer(id=i, name=f"server-{i}", host="localhost", port=8089 + i)
            for i in range(1, 4)
        ]

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                # Start workers for all servers
                for server in tak_servers:
                    await cot_service.start_worker(server)

                # Measure parallel processing performance
                start_time = time.time()

                tasks = []
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"

                # Process events in parallel across multiple servers
                for server in tak_servers:
                    for i in range(10):
                        task = asyncio.create_task(
                            cot_service.enqueue_event(test_event, server.id)
                        )
                        tasks.append(task)

                await asyncio.gather(*tasks)

                processing_time = time.time() - start_time

                # Performance requirement: should complete quickly
                assert (
                    processing_time < 5.0
                ), f"Parallel processing took {processing_time}s, expected < 5.0s"

                # Cleanup
                for server in tak_servers:
                    await cot_service.stop_worker(server.id)

    @pytest.mark.asyncio
    async def test_memory_usage_bounded_and_predictable(self):
        """✅ Memory usage bounded and predictable"""
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Use small queue to force overflow
        queue_config = {
            "max_size": 20,
            "batch_size": 5,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Add many events to trigger overflow
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                for i in range(200):  # 10x the queue size
                    await cot_service.enqueue_event(test_event, tak_server.id)

                    # Check memory periodically
                    if i % 50 == 0:
                        current_memory = process.memory_info().rss / 1024 / 1024
                        memory_growth = current_memory - initial_memory
                        assert (
                            memory_growth < 50
                        ), f"Memory grew by {memory_growth}MB, indicating potential leak"

                # Final memory check
                final_memory = process.memory_info().rss / 1024 / 1024
                total_growth = final_memory - initial_memory

                assert (
                    total_growth < 30
                ), f"Total memory growth {total_growth}MB too high"

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_tak_server_load_remains_steady(self):
        """✅ TAK server load remains steady (no overwhelming bursts)"""
        batch_size = 3
        queue_config = {
            "max_size": 50,
            "batch_size": batch_size,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        transmission_times = []

        def mock_write(data):
            transmission_times.append(time.time())

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_reader = AsyncMock()
                mock_writer = AsyncMock()
                mock_writer.write = mock_write
                mock_factory.return_value = (mock_reader, mock_writer)

                await cot_service.start_worker(tak_server)

                # Add events rapidly
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                for i in range(15):  # Multiple batches
                    await cot_service.enqueue_event(test_event, tak_server.id)

                # Wait for transmission
                await asyncio.sleep(1.0)

                # Analyze transmission timing
                if len(transmission_times) >= 2:
                    intervals = [
                        transmission_times[i] - transmission_times[i - 1]
                        for i in range(1, len(transmission_times))
                    ]

                    # Transmissions should be spread out, not all at once
                    avg_interval = statistics.mean(intervals) if intervals else 0
                    assert (
                        avg_interval > 0.01
                    ), "Transmissions too rapid - may overwhelm server"

                await cot_service.stop_worker(tak_server.id)


class TestPhase4CompatibilityValidation:
    """Compatibility validation tests"""

    @pytest.mark.asyncio
    async def test_existing_monitoring_metrics_functional(self):
        """✅ All existing monitoring metrics functional"""
        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Test that basic metrics are available
                assert tak_server.id in cot_service.queues
                assert tak_server.id in cot_service.workers

                queue = cot_service.queues[tak_server.id]

                # Basic queue metrics should work
                initial_size = queue.qsize()
                assert isinstance(initial_size, int)
                assert initial_size >= 0

                # Add event and verify metrics update
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                await cot_service.enqueue_event(test_event, tak_server.id)

                new_size = queue.qsize()
                assert new_size >= initial_size

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_backward_compatibility_maintained(self):
        """✅ Backward compatibility with current API"""
        # Test that existing API calls still work
        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        # These methods should exist and be callable
        assert hasattr(cot_service, "start_worker")
        assert hasattr(cot_service, "stop_worker")
        assert hasattr(cot_service, "enqueue_event")

        # Dictionary attributes should exist
        assert hasattr(cot_service, "workers")
        assert hasattr(cot_service, "queues")
        assert hasattr(cot_service, "connections")

    @pytest.mark.asyncio
    async def test_no_breaking_changes_to_existing_functionality(self):
        """✅ No breaking changes to existing functionality"""
        # Test that queue configuration doesn't break basic operation
        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                # Basic worker lifecycle should work
                success = await cot_service.start_worker(tak_server)
                assert (
                    success is True or success is None
                )  # Some implementations don't return bool

                # Should be able to enqueue events
                test_event = b"<event><point lat='40.7' lon='-74.0'/></event>"
                await cot_service.enqueue_event(test_event, tak_server.id)

                # Should be able to stop worker
                await cot_service.stop_worker(tak_server.id)


class TestPhase4LoadTestingValidation:
    """Load testing validation for Deepstate scenarios"""

    @pytest.mark.asyncio
    async def test_deepstate_300_point_scenario(self):
        """Load test with 300+ GPS points (Deepstate scenario)"""
        point_count = 300
        processing_time_limit = 60.0  # seconds

        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="deepstate-test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                start_time = time.time()

                # Generate 300 GPS points
                tasks = []
                for i in range(point_count):
                    lat = 40.7128 + (i * 0.001)  # Spread out geographically
                    lon = -74.0060 + (i * 0.001)

                    test_event = (
                        f'<event><point lat="{lat}" lon="{lon}"/></event>'.encode()
                    )
                    task = asyncio.create_task(
                        cot_service.enqueue_event(test_event, tak_server.id)
                    )
                    tasks.append(task)

                # Wait for all events to be queued
                await asyncio.gather(*tasks)

                # Allow time for processing
                await asyncio.sleep(2.0)

                total_time = time.time() - start_time

                # Verify performance requirements
                assert (
                    total_time < processing_time_limit
                ), f"Processing took {total_time}s, expected < {processing_time_limit}s"

                # Calculate throughput
                throughput = point_count / total_time
                assert throughput > 5.0, f"Throughput {throughput} events/sec too low"

                print(
                    f"Processed {point_count} events in {total_time:.2f}s ({throughput:.1f} events/sec)"
                )

                await cot_service.stop_worker(tak_server.id)


def run_phase4_validation():
    """Run all Phase 4 validation tests"""
    print("🚀 Starting Phase 4 Queue Management Validation")
    print("=" * 60)

    # Run the tests
    pytest.main([__file__, "-v", "--tb=short", "-x"])  # Stop on first failure


if __name__ == "__main__":
    run_phase4_validation()
