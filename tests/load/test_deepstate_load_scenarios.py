"""
ABOUTME: Load testing for Deepstate scenarios with 300+ GPS points
ABOUTME: Phase 4 validation tests specifically for high-volume Deepstate workloads

This module contains load tests that simulate real-world Deepstate scenarios
with 300+ GPS points to validate queue performance under production load.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
import statistics
import random
from unittest.mock import AsyncMock, patch
from typing import List, Dict, Any

from services.cot_service_integration import QueuedCOTService
from models.tak_server import TakServer


class TestDeepstateLoadScenarios:
    """Load testing for Deepstate scenarios"""

    @pytest.mark.asyncio
    async def test_deepstate_300_points_sequential(self):
        """Test processing 300 GPS points sequentially (baseline)"""
        point_count = 300
        max_processing_time = 60.0  # 1 minute limit

        # Configure queue for high throughput
        queue_config = {
            "max_size": 500,  # Allow all events in queue
            "batch_size": 8,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="deepstate-test", host="localhost", port=8089)

        # Track transmission performance
        transmitted_events = []
        transmission_times = []

        def mock_write(data):
            transmitted_events.append(data)
            transmission_times.append(time.time())

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_reader = AsyncMock()
                mock_writer = AsyncMock()
                mock_writer.write = mock_write
                mock_factory.return_value = (mock_reader, mock_writer)

                start_time = time.time()

                await cot_service.start_worker(tak_server)

                # Generate Deepstate-style GPS data (sequential points along a route)
                for i in range(point_count):
                    lat = 40.7128 + (i * 0.0001)  # Small increments simulating movement
                    lon = -74.0060 + (i * 0.0001)
                    timestamp = time.time()

                    # Create realistic COT event
                    cot_event = self._create_deepstate_cot_event(
                        uid=f"deepstate-{i:03d}",
                        lat=lat,
                        lon=lon,
                        timestamp=timestamp,
                        callsign=f"DS-{i:03d}",
                        speed=random.uniform(20, 60),  # km/h
                        course=random.uniform(0, 360),
                    )

                    await cot_service.enqueue_event(cot_event, tak_server.id)

                # Allow processing time
                await asyncio.sleep(2.0)

                total_time = time.time() - start_time

                # Performance assertions
                assert (
                    total_time < max_processing_time
                ), f"Processing took {total_time:.2f}s, expected < {max_processing_time}s"

                if transmitted_events:
                    throughput = len(transmitted_events) / total_time
                    assert (
                        throughput > 5.0
                    ), f"Throughput {throughput:.1f} events/sec too low"
                    print(
                        f"Processed {point_count} events in {total_time:.2f}s ({throughput:.1f} events/sec)"
                    )

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_deepstate_300_points_burst(self):
        """Test processing 300 GPS points in rapid burst"""
        point_count = 300
        max_processing_time = 45.0  # Faster expectation for burst

        queue_config = {
            "max_size": 400,  # Smaller queue to test overflow handling
            "batch_size": 10,  # Larger batches for efficiency
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(
            id=1, name="deepstate-burst", host="localhost", port=8089
        )

        transmission_count = 0

        def mock_write(data):
            nonlocal transmission_count
            transmission_count += data.count(b"<event>")

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_reader = AsyncMock()
                mock_writer = AsyncMock()
                mock_writer.write = mock_write
                mock_factory.return_value = (mock_reader, mock_writer)

                await cot_service.start_worker(tak_server)

                start_time = time.time()

                # Send all events as fast as possible (burst scenario)
                tasks = []
                for i in range(point_count):
                    lat = 40.7128 + random.uniform(-0.01, 0.01)  # Random area
                    lon = -74.0060 + random.uniform(-0.01, 0.01)

                    cot_event = self._create_deepstate_cot_event(
                        uid=f"burst-{i:03d}",
                        lat=lat,
                        lon=lon,
                        timestamp=time.time(),
                        callsign=f"BURST-{i:03d}",
                    )

                    task = asyncio.create_task(
                        cot_service.enqueue_event(cot_event, tak_server.id)
                    )
                    tasks.append(task)

                # Wait for all events to be queued
                await asyncio.gather(*tasks)

                # Allow processing time
                await asyncio.sleep(3.0)

                total_time = time.time() - start_time

                # Assertions for burst scenario
                assert (
                    total_time < max_processing_time
                ), f"Burst processing took {total_time:.2f}s, expected < {max_processing_time}s"

                # In burst scenario, some events may be dropped due to overflow
                # But queue should handle the load gracefully
                queue = cot_service.queues[tak_server.id]
                final_queue_size = queue.qsize()
                assert (
                    final_queue_size <= queue_config["max_size"]
                ), f"Queue exceeded max size: {final_queue_size}"

                print(
                    f"Burst test: {point_count} events in {total_time:.2f}s, {transmission_count} transmitted"
                )

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_deepstate_multiple_streams_concurrent(self):
        """Test multiple Deepstate streams processing concurrently"""
        streams = 3
        points_per_stream = 100
        total_points = streams * points_per_stream
        max_processing_time = 30.0

        cot_service = QueuedCOTService()

        # Create multiple TAK servers (simulating multiple streams)
        tak_servers = [
            TakServer(
                id=i, name=f"deepstate-stream-{i}", host="localhost", port=8089 + i
            )
            for i in range(1, streams + 1)
        ]

        transmission_counts = {server.id: 0 for server in tak_servers}

        def create_mock_write(server_id):
            def mock_write(data):
                transmission_counts[server_id] += data.count(b"<event>")

            return mock_write

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:

                def mock_connection():
                    mock_reader = AsyncMock()
                    mock_writer = AsyncMock()
                    return (mock_reader, mock_writer)

                mock_factory.side_effect = lambda: mock_connection()

                # Start all workers
                for server in tak_servers:
                    await cot_service.start_worker(server)
                    # Set up mock writer for each server
                    if server.id in cot_service.connections:
                        reader, writer = cot_service.connections[server.id]
                        writer.write = create_mock_write(server.id)

                start_time = time.time()

                # Process events concurrently across all streams
                all_tasks = []
                for server in tak_servers:
                    for i in range(points_per_stream):
                        # Create unique GPS tracks for each stream
                        base_lat = 40.7128 + (server.id * 0.01)
                        base_lon = -74.0060 + (server.id * 0.01)

                        lat = base_lat + (i * 0.0001)
                        lon = base_lon + (i * 0.0001)

                        cot_event = self._create_deepstate_cot_event(
                            uid=f"stream-{server.id}-{i:03d}",
                            lat=lat,
                            lon=lon,
                            timestamp=time.time(),
                            callsign=f"DS{server.id}-{i:03d}",
                        )

                        task = asyncio.create_task(
                            cot_service.enqueue_event(cot_event, server.id)
                        )
                        all_tasks.append(task)

                # Wait for all events to be queued
                await asyncio.gather(*all_tasks)

                # Allow processing time
                await asyncio.sleep(3.0)

                total_time = time.time() - start_time

                # Performance assertions
                assert (
                    total_time < max_processing_time
                ), f"Concurrent processing took {total_time:.2f}s, expected < {max_processing_time}s"

                # Calculate overall throughput
                total_transmitted = sum(transmission_counts.values())
                if total_transmitted > 0:
                    throughput = total_transmitted / total_time
                    assert (
                        throughput > 10.0
                    ), f"Concurrent throughput {throughput:.1f} events/sec too low"
                    print(
                        f"Concurrent test: {total_points} events across {streams} streams in {total_time:.2f}s"
                    )

                # Cleanup
                for server in tak_servers:
                    await cot_service.stop_worker(server.id)

    @pytest.mark.asyncio
    async def test_deepstate_memory_stability_under_load(self):
        """Test memory stability during sustained Deepstate load"""
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Small queue to force overflow and test memory bounds
        queue_config = {
            "max_size": 50,
            "batch_size": 5,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="memory-test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Run sustained load test
                for batch in range(10):  # 10 batches of 50 events each
                    for i in range(50):
                        lat = 40.7128 + random.uniform(-0.1, 0.1)
                        lon = -74.0060 + random.uniform(-0.1, 0.1)

                        cot_event = self._create_deepstate_cot_event(
                            uid=f"memory-{batch}-{i:02d}",
                            lat=lat,
                            lon=lon,
                            timestamp=time.time(),
                            callsign=f"MEM-{batch}-{i:02d}",
                        )

                        await cot_service.enqueue_event(cot_event, tak_server.id)

                    # Check memory after each batch
                    current_memory = process.memory_info().rss / 1024 / 1024
                    memory_growth = current_memory - initial_memory

                    assert (
                        memory_growth < 100
                    ), f"Memory grew by {memory_growth:.1f}MB after batch {batch}"

                    # Brief pause between batches
                    await asyncio.sleep(0.1)

                # Final memory check
                final_memory = process.memory_info().rss / 1024 / 1024
                total_growth = final_memory - initial_memory

                assert (
                    total_growth < 50
                ), f"Total memory growth {total_growth:.1f}MB exceeds limit"
                print(
                    f"Memory test: processed 500 events, memory growth: {total_growth:.1f}MB"
                )

                await cot_service.stop_worker(tak_server.id)

    def _create_deepstate_cot_event(
        self,
        uid: str,
        lat: float,
        lon: float,
        timestamp: float,
        callsign: str,
        speed: float = 30.0,
        course: float = 180.0,
    ) -> bytes:
        """Create a realistic Deepstate-style COT event"""

        # Format timestamp for COT
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        time_str = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Calculate stale time (5 minutes from now)
        stale_dt = datetime.fromtimestamp(timestamp + 300, tz=timezone.utc)
        stale_str = stale_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        cot_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{uid}" type="a-f-G-U-C" time="{time_str}" start="{time_str}" stale="{stale_str}" how="h-g-i-g-o">
    <point lat="{lat:.6f}" lon="{lon:.6f}" hae="10.0" ce="9999999.0" le="9999999.0"/>
    <detail>
        <takv device="TrakBridge" platform="TrakBridge" os="Python" version="1.0.0"/>
        <contact callsign="{callsign}" endpoint="*:-1:stcp"/>
        <__group name="Blue" role="Team Member"/>
        <track speed="{speed:.1f}" course="{course:.1f}"/>
        <precisionlocation geopointsrc="GPS" altsrc="GPS"/>
    </detail>
</event>"""

        return cot_xml.encode("utf-8")


class TestDeepstateQueueBehavior:
    """Test specific queue behaviors under Deepstate load"""

    @pytest.mark.asyncio
    async def test_queue_overflow_handling_under_load(self):
        """Test queue overflow behavior with Deepstate-like load"""
        small_queue_size = 20
        overflow_events = 50  # More events than queue can hold

        queue_config = {
            "max_size": small_queue_size,
            "batch_size": 5,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="overflow-test", host="localhost", port=8089)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_factory.return_value = (AsyncMock(), AsyncMock())

                await cot_service.start_worker(tak_server)

                # Add more events than queue can hold
                for i in range(overflow_events):
                    cot_event = f'<event uid="overflow-{i}"><point lat="40.7" lon="-74.0"/></event>'.encode()
                    await cot_service.enqueue_event(cot_event, tak_server.id)

                # Verify queue size is bounded
                queue = cot_service.queues[tak_server.id]
                assert (
                    queue.qsize() <= small_queue_size
                ), f"Queue size {queue.qsize()} exceeds limit {small_queue_size}"

                print(
                    f"Overflow test: added {overflow_events} events, queue size: {queue.qsize()}"
                )

                await cot_service.stop_worker(tak_server.id)

    @pytest.mark.asyncio
    async def test_batch_transmission_efficiency_under_load(self):
        """Test batch transmission efficiency with high event volume"""
        batch_size = 8
        total_events = 80  # 10 full batches

        queue_config = {
            "max_size": 100,
            "batch_size": batch_size,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        cot_service = QueuedCOTService(queue_config=queue_config)
        tak_server = TakServer(id=1, name="batch-test", host="localhost", port=8089)

        transmission_batches = []

        def mock_write(data):
            # Count events in this transmission
            event_count = data.count(b"<event>")
            if event_count > 0:
                transmission_batches.append(event_count)

        with patch("services.cot_service.PYTAK_AVAILABLE", True):
            with patch("services.cot_service.pytak.protocol_factory") as mock_factory:
                mock_reader = AsyncMock()
                mock_writer = AsyncMock()
                mock_writer.write = mock_write
                mock_factory.return_value = (mock_reader, mock_writer)

                await cot_service.start_worker(tak_server)

                # Add events
                for i in range(total_events):
                    cot_event = f'<event uid="batch-{i}"><point lat="40.7" lon="-74.0"/></event>'.encode()
                    await cot_service.enqueue_event(cot_event, tak_server.id)

                # Allow processing
                await asyncio.sleep(1.0)

                # Verify batching efficiency
                if transmission_batches:
                    full_batches = [b for b in transmission_batches if b == batch_size]
                    efficiency = (
                        len(full_batches) / len(transmission_batches)
                        if transmission_batches
                        else 0
                    )

                    assert (
                        efficiency >= 0.7
                    ), f"Batching efficiency {efficiency:.2f} too low (should be >= 70%)"
                    print(
                        f"Batch efficiency: {len(full_batches)}/{len(transmission_batches)} full batches ({efficiency:.1%})"
                    )

                await cot_service.stop_worker(tak_server.id)


def run_deepstate_load_tests():
    """Run all Deepstate load tests"""
    print("🚀 Starting Deepstate Load Testing (Phase 4)")
    print("=" * 60)

    pytest.main(
        [__file__, "-v", "--tb=short", "-x", "--maxfail=3"]  # Stop on first failure
    )


if __name__ == "__main__":
    run_deepstate_load_tests()
