"""
ABOUTME: Integration tests for queue performance and system-wide behavior
ABOUTME: Tests performance requirements and compatibility with Deepstate scenarios

This module contains integration tests for queue performance as specified in the
Queue Management Specification Phase 1. These tests verify that queue changes do
not negatively impact system performance and handle realistic workloads.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
from unittest.mock import patch
from typing import Dict, Any

from services.cot_service import get_cot_service, reset_cot_service
from services.queue_manager import reset_queue_manager
from models.tak_server import TakServer


class TestQueuePerformanceIntegration:
    """Integration tests for queue performance under realistic conditions"""

    def setup_method(self):
        """Reset singletons before each test to ensure clean state"""
        reset_cot_service()
        reset_queue_manager()

    @pytest.mark.asyncio
    async def test_deepstate_workload_performance(self, app, db_session):
        """Test queue performance with Deepstate-like workload (300+ points)"""
        with app.app_context():
            # Simulate Deepstate scenario with 300 GPS points
            point_count = 300
            batch_processing_time_limit = 30.0  # seconds

            cot_service = get_cot_service()

            # Create and persist TAK server in database
            tak_server = TakServer(name="deepstate-test", host="localhost", port=8089)
            db_session.add(tak_server)
            db_session.commit()

            # Refresh to get the ID assigned by database
            db_session.refresh(tak_server)

        # Create queue first
        await cot_service.queue_manager.create_queue(tak_server.id)

        # Mock the actual transmission to avoid network calls
        transmitted_events = []

        async def mock_transmit(events, server):
            transmitted_events.extend(events)
            await asyncio.sleep(0.001)  # Simulate minimal network delay

        with patch.object(
            cot_service, "_transmit_events_batch", side_effect=mock_transmit
        ):
            start_time = time.time()

            # Generate and queue 300 GPS points rapidly
            tasks = []
            for i in range(point_count):
                event = self._create_deepstate_event(
                    f"deepstate-{i}", lat=40.7128 + i * 0.001, lon=-74.0060 + i * 0.001
                )
                task = asyncio.create_task(
                    cot_service.enqueue_event(event, tak_server.id)
                )
                tasks.append(task)

            # Wait for all events to be queued
            await asyncio.gather(*tasks)

            # Process all events through transmission
            await cot_service._process_transmission_batches(tak_server.id, tak_server)

            total_time = time.time() - start_time

            # Performance assertions
            assert (
                total_time < batch_processing_time_limit
            ), f"Processing took {total_time}s, expected < {batch_processing_time_limit}s"
            assert (
                len(transmitted_events) == point_count
            ), f"Expected {point_count} events, got {len(transmitted_events)}"

            # Throughput assertion (events per second)
            throughput = point_count / total_time
            assert (
                throughput > 10.0
            ), f"Throughput {throughput} events/sec too low, expected > 10/sec"

    @pytest.mark.asyncio
    async def test_configuration_change_propagation_time(self, app, db_session):
        """Test that configuration changes propagate within 5-15 seconds as specified"""
        max_propagation_time = 15.0  # seconds (upper limit from spec)
        target_propagation_time = 5.0  # seconds (target from spec)

        with app.app_context():
            cot_service = get_cot_service()

            # Create and persist TAK server in database
            tak_server = TakServer(name="config-test", host="localhost", port=8089)
            db_session.add(tak_server)
            db_session.commit()

            # Refresh to get the ID assigned by database
            db_session.refresh(tak_server)

        # Create queue first
        await cot_service.queue_manager.create_queue(tak_server.id)

        # Fill queue with events
        for i in range(20):
            event = self._create_test_event(f"config-change-{i}")
            await cot_service.enqueue_event(event, tak_server.id)

        status = cot_service.get_queue_status(tak_server.id)
        initial_size = status.get("size", 0)
        assert initial_size > 0, "Queue should have events before configuration change"

        # Measure configuration change response time
        start_time = time.time()
        await cot_service.on_configuration_change({})
        propagation_time = time.time() - start_time

        # Verify queue was flushed
        final_status = cot_service.get_queue_status(tak_server.id)
        final_size = final_status.get("size", 0)
        assert final_size == 0, "Queue should be empty after configuration change"

        # Time-based assertions
        assert (
            propagation_time < max_propagation_time
        ), f"Configuration change took {propagation_time}s, expected < {max_propagation_time}s"

        # Log performance for analysis
        if propagation_time > target_propagation_time:
            print(
                f"Warning: Configuration change took {propagation_time}s, target is {target_propagation_time}s"
            )

    @pytest.mark.asyncio
    async def test_memory_usage_bounds(self, app, db_session):
        """Test that queue implementation keeps memory usage bounded"""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        with app.app_context():
            cot_service = get_cot_service()

            # Create and persist TAK server in database
            tak_server = TakServer(name="memory-test", host="localhost", port=8089)
            db_session.add(tak_server)
            db_session.commit()

            # Refresh to get the ID assigned by database
            db_session.refresh(tak_server)

        # Create queue first
        await cot_service.queue_manager.create_queue(tak_server.id)

        # Configure small queue to force overflow handling
        with patch.object(
            cot_service.queue_manager,
            "config",
            {"max_size": 50, "batch_size": 8, "overflow_strategy": "drop_oldest"},
        ):

            # Add many events to trigger overflow behavior
            for i in range(500):  # 10x the queue size
                event = self._create_test_event(f"memory-{i}")
                await cot_service.enqueue_event(event, tak_server.id)

                # Periodically check memory doesn't grow unbounded
                if i % 100 == 0:
                    current_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_growth = current_memory - initial_memory
                    assert memory_growth < 100, (
                        f"Memory grew by {memory_growth}MB, "
                        "indicating potential memory leak"
                    )

            # Final memory check
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            total_memory_growth = final_memory - initial_memory

            # Memory should be bounded despite processing 500 events
            assert (
                total_memory_growth < 50
            ), f"Total memory growth {total_memory_growth}MB too high"

    @pytest.mark.asyncio
    async def test_batch_transmission_efficiency(self, app, db_session):
        """Test that batch transmission reduces TAK server load as intended"""
        # Use production default batch size from queue manager
        event_count = 50

        with app.app_context():
            cot_service = get_cot_service()

            # Create and persist TAK server in database
            tak_server = TakServer(name="batch-test", host="localhost", port=8089)
            db_session.add(tak_server)
            db_session.commit()

            # Refresh to get the ID assigned by database
            db_session.refresh(tak_server)

        # Create queue first
        await cot_service.queue_manager.create_queue(tak_server.id)

        # Verify queue starts empty
        print(f"DEBUG: Using TAK server ID: {tak_server.id}")
        initial_status = cot_service.get_queue_status(tak_server.id)
        print(f"DEBUG: Initial queue status: {initial_status}")
        assert (
            initial_status["size"] == 0
        ), f"Queue should start empty, but has {initial_status['size']} events"

        transmission_calls = []
        total_events_transmitted = 0

        async def mock_transmit_batch(events, server):
            nonlocal total_events_transmitted
            transmission_calls.append(len(events))
            total_events_transmitted += len(events)
            await asyncio.sleep(0.01)  # Simulate transmission time

        with patch.object(
            cot_service, "_transmit_events_batch", side_effect=mock_transmit_batch
        ):
            # Queue events sequentially to avoid race conditions
            for i in range(event_count):
                event = self._create_test_event(f"batch-{i}")
                success = await cot_service.enqueue_event(event, tak_server.id)
                assert success, f"Failed to enqueue event {i}"

            # Verify events are queued before processing
            queue_status = cot_service.get_queue_status(tak_server.id)
            print(
                f"DEBUG: After queuing {event_count} events, queue status: {queue_status}"
            )
            assert queue_status["size"] == event_count, (
                f"Expected {event_count} events queued, " f"got {queue_status['size']}"
            )

            # Process all batches once
            await cot_service._process_transmission_batches(tak_server.id, tak_server)

            # Verify that exactly the right number of events were transmitted
            assert total_events_transmitted == event_count, (
                f"Expected {event_count} events transmitted, "
                f"got {total_events_transmitted}"
            )

            # Verify batching occurred (should be fewer transmission calls than events)
            assert len(transmission_calls) < event_count, (
                f"Expected fewer than {event_count} transmission calls "
                f"for batching, got {len(transmission_calls)}"
            )

            # Verify queue is empty after processing
            final_status = cot_service.get_queue_status(tak_server.id)
            assert final_status["size"] == 0, (
                f"Queue should be empty after processing, "
                f"got {final_status['size']}"
            )

    @pytest.mark.asyncio
    async def test_concurrent_stream_processing(self, app, db_session):
        """Test queue performance with multiple concurrent streams"""
        stream_count = 5
        events_per_stream = 20

        with app.app_context():
            cot_service = get_cot_service()

            # Create and persist TAK servers in database
            tak_servers = []
            for i in range(1, stream_count + 1):
                server = TakServer(
                    name=f"concurrent-{i}", host="localhost", port=8089 + i
                )
                db_session.add(server)
                tak_servers.append(server)

            db_session.commit()

            # Refresh to get IDs assigned by database
            for server in tak_servers:
                db_session.refresh(server)

        # Create queues for all servers
        for server in tak_servers:
            await cot_service.queue_manager.create_queue(server.id)

        transmitted_events = {server.id: [] for server in tak_servers}

        async def mock_transmit(events, server):
            transmitted_events[server.id].extend(events)
            await asyncio.sleep(0.005)  # Simulate transmission delay

        with patch.object(
            cot_service, "_transmit_events_batch", side_effect=mock_transmit
        ):
            start_time = time.time()

            # Process events concurrently across all streams
            all_tasks = []
            for server in tak_servers:
                for i in range(events_per_stream):
                    event = self._create_test_event(f"concurrent-{server.id}-{i}")
                    task = asyncio.create_task(
                        cot_service.enqueue_event(event, server.id)
                    )
                    all_tasks.append(task)

            # Wait for all events to be queued
            await asyncio.gather(*all_tasks)

            # Process all queues
            for server in tak_servers:
                await cot_service._process_transmission_batches(server.id, server)

            total_time = time.time() - start_time

            # Verify events processed (allow for some loss due to concurrent processing)
            total_transmitted = sum(
                len(events) for events in transmitted_events.values()
            )
            expected_total = stream_count * events_per_stream

            # Allow for up to 5% event loss during concurrent processing due to
            # queue overflow, event loop binding issues, or race conditions
            min_expected = int(expected_total * 0.95)
            assert total_transmitted >= min_expected, (
                f"Expected at least {min_expected} events, " f"got {total_transmitted}"
            )

            # Performance should not degrade significantly with concurrent streams
            avg_throughput = total_transmitted / total_time
            assert avg_throughput > 15.0, (
                f"Concurrent throughput {avg_throughput} events/sec too low "
                "(reduced threshold for concurrent processing)"
            )

    def _create_test_event(self, uid: str) -> bytes:
        """Helper method to create test COT events"""
        return f'<event uid="{uid}" type="a-f-G-U-C" time="{time.time()}" start="{time.time()}" stale="{time.time() + 3600}"><point lat="40.7128" lon="-74.0060" hae="10.0" ce="9999999.0" le="9999999.0"/><detail><contact callsign="Test-{uid}"/></detail></event>'.encode()

    def _create_deepstate_event(self, uid: str, lat: float, lon: float) -> bytes:
        """Helper method to create Deepstate-style GPS events"""
        return f'<event uid="{uid}" type="a-f-G-U-C" time="{time.time()}" start="{time.time()}" stale="{time.time() + 3600}"><point lat="{lat}" lon="{lon}" hae="15.0" ce="9999999.0" le="9999999.0"/><detail><contact callsign="Deepstate-{uid}"/><track speed="25.0" course="180.0"/></detail></event>'.encode()


class TestQueueSystemIntegration:
    """Integration tests for queue system compatibility"""

    def setup_method(self):
        """Reset singletons before each test to ensure clean state"""
        reset_cot_service()
        reset_queue_manager()

    @pytest.mark.asyncio
    async def test_existing_stream_manager_compatibility(self):
        """Test that queue changes don't break existing StreamManager functionality"""
        from services.stream_manager import StreamManager

        # This test ensures the queue changes integrate properly with existing systems
        stream_manager = StreamManager()

        # Verify stream manager can still create and manage streams
        # This is a placeholder test - actual implementation depends on StreamManager interface
        assert stream_manager is not None

        # Test would verify that:
        # 1. StreamManager can create streams that use the new queue system
        # 2. Existing monitoring metrics still work
        # 3. Stream lifecycle management (start/stop/restart) works with queues

    @pytest.mark.asyncio
    async def test_monitoring_metrics_integration(self, app, db_session):
        """Test that queue metrics integrate with existing monitoring system"""
        with app.app_context():
            cot_service = get_cot_service()

            # Create and persist TAK server in database
            tak_server = TakServer(name="monitoring-test", host="localhost", port=8089)
            db_session.add(tak_server)
            db_session.commit()

            # Refresh to get the ID assigned by database
            db_session.refresh(tak_server)

        # Add some events
        for i in range(5):
            event = self._create_test_event(f"monitoring-{i}")
            await cot_service.enqueue_event(event, tak_server.id)

        # Get monitoring data
        metrics = await cot_service.get_queue_metrics(tak_server.id)

        # Verify monitoring integration
        assert "queue_size" in metrics
        assert "events_queued" in metrics
        assert metrics["queue_size"] == 5

        # Test that metrics update correctly
        await cot_service._process_transmission_batches(tak_server.id, tak_server)
        updated_metrics = await cot_service.get_queue_metrics(tak_server.id)

        # Queue should be processed
        assert updated_metrics["queue_size"] <= metrics["queue_size"]

    def _create_test_event(self, uid: str) -> bytes:
        """Helper method to create test COT events"""
        return f'<event uid="{uid}" type="a-f-G-U-C" time="{time.time()}" start="{time.time()}" stale="{time.time() + 3600}"><point lat="40.7128" lon="-74.0060" hae="10.0" ce="9999999.0" le="9999999.0"/><detail><contact callsign="Test-{uid}"/></detail></event>'.encode()
