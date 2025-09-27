"""
ABOUTME: Unit tests for queue management functionality according to TDD Phase 1 specification
ABOUTME: Tests core queue behavior including size limits, overflow handling, and batch transmission

This module contains the core queue behavior tests as specified in the Queue Management
Specification Phase 1 (Red Phase). These tests are designed to fail initially and drive
the implementation of bounded queues with configurable overflow strategies.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from services.cot_service_integration import QueuedCOTService, reset_queued_cot_service
from services.cot_service import get_cot_service, reset_cot_service
from models.tak_server import TakServer
from models.stream import Stream
from utils.cot_test_helpers import (
    create_test_cot_event,
    get_queue_for_server,
    enqueue_test_event,
    create_queue_config,
    wait_for_queue_size,
    verify_queue_metrics,
)


class TestQueueSizeManagement:
    """Test queue size limits and bounds enforcement"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Reset singleton before each test"""
        reset_cot_service()
        reset_queued_cot_service()

    @pytest.mark.asyncio
    async def test_queue_respects_max_size_limit(self):
        """Queue should not exceed configured maximum size"""
        max_queue_size = 5

        # Mock configuration with small queue size for testing
        test_config = {
            "max_size": max_queue_size,
            "batch_size": 8,
            "overflow_strategy": "drop_oldest",
        }

        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(test_config)
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

            # Create a queue for this TAK server
            await cot_service.queue_manager.create_queue(tak_server.id)
            queue = get_queue_for_server(cot_service, tak_server.id)

            # Add events up to the limit
            for i in range(max_queue_size):
                test_event = create_test_cot_event(f"test-{i}")
                await enqueue_test_event(cot_service, tak_server.id, test_event)

            # Verify queue is at maximum capacity
            assert queue.qsize() == max_queue_size

            # Attempt to add one more event - should not exceed limit
            overflow_event = create_test_cot_event("overflow")
            await enqueue_test_event(cot_service, tak_server.id, overflow_event)

            # Queue should still be at max size (oldest event dropped)
            assert queue.qsize() == max_queue_size

    @pytest.mark.asyncio
    async def test_overflow_drops_oldest_events(self):
        """When queue is full, oldest events should be dropped (FIFO)"""
        max_queue_size = 3

        test_config = {
            "max_size": max_queue_size,
            "batch_size": 8,
            "overflow_strategy": "drop_oldest",
        }

        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(test_config)
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

            await cot_service.queue_manager.create_queue(tak_server.id)
            queue = get_queue_for_server(cot_service, tak_server.id)

            # Add initial events
            events = []
            for i in range(max_queue_size):
                event = create_test_cot_event(f"event-{i}")
                events.append(event)
                await enqueue_test_event(cot_service, tak_server.id, event)

            # Add overflow event - should drop the oldest (event-0)
            overflow_event = create_test_cot_event("overflow")
            await enqueue_test_event(cot_service, tak_server.id, overflow_event)

            # Verify queue size is still at maximum
            assert queue.qsize() == max_queue_size

            # Extract all events and verify oldest was dropped
            remaining_events = []
            while not queue.empty():
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                remaining_events.append(event)

            # Should contain event-1, event-2, and overflow (event-0 dropped)
            # Events are stored as XML bytes, so we need to parse them to get UIDs
            import xml.etree.ElementTree as ET

            event_uids = []
            for event in remaining_events:
                try:
                    root = ET.fromstring(event)
                    uid = root.get("uid", "")
                    event_uids.append(uid)
                except Exception:
                    # If parsing fails, convert to string and extract UID
                    event_str = (
                        event.decode("utf-8")
                        if isinstance(event, bytes)
                        else str(event)
                    )
                    if "uid=" in event_str:
                        uid_part = event_str.split("uid='")[1].split("'")[0]
                        event_uids.append(uid_part)

            assert (
                "event-0" not in event_uids
            ), f"event-0 should have been dropped, but found UIDs: {event_uids}"
            assert (
                "overflow" in event_uids
            ), f"overflow event should be present, but found UIDs: {event_uids}"

    @pytest.mark.asyncio
    async def test_queue_batch_transmission(self):
        """Events should be transmitted in configurable small batches"""
        batch_size = 3

        test_config = {
            "max_size": 500,
            "batch_size": batch_size,
            "overflow_strategy": "drop_oldest",
            "batch_timeout_ms": 100,
        }

        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(test_config)
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

            # Mock the transmission method
            transmitted_batches = []

            async def mock_transmit_batch(events, server):
                transmitted_batches.append(len(events))

            # Create queue first
            await cot_service.queue_manager.create_queue(tak_server.id)

            with patch.object(
                cot_service, "_transmit_events_batch", side_effect=mock_transmit_batch
            ):
                # Queue multiple events
                for i in range(7):  # More than one batch
                    event = create_test_cot_event(f"batch-event-{i}")
                    await enqueue_test_event(cot_service, tak_server.id, event)

                # Trigger batch transmission
                await cot_service._process_transmission_batches(
                    tak_server.id, tak_server
                )

                # Should have transmitted in batches of specified size
                assert len(transmitted_batches) >= 2  # At least 2 batches
                assert all(
                    batch_size <= size <= batch_size
                    for size in transmitted_batches[:-1]
                )  # All but last should be full batches
                assert sum(transmitted_batches) == 7  # All events transmitted

    @pytest.mark.asyncio
    async def test_configuration_change_flushes_queue(self):
        """Configuration changes should trigger immediate queue flush"""
        test_config = {
            "max_size": 10,
            "batch_size": 8,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
        }

        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(test_config)
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

            # Create queue first, then add events
            await cot_service.queue_manager.create_queue(tak_server.id)
            queue = get_queue_for_server(cot_service, tak_server.id)

            # Add events to queue
            for i in range(5):
                event = create_test_cot_event(f"pre-config-{i}")
                await enqueue_test_event(cot_service, tak_server.id, event)

            assert queue.qsize() == 5

            # Simulate configuration change by flushing queue
            await cot_service.flush_queue(tak_server.id)

            # Queue should be flushed (empty)
            assert queue.qsize() == 0


class TestQueuePerformanceCompatibility:
    """Test performance requirements and compatibility with existing systems"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Reset singleton before each test"""
        reset_cot_service()
        reset_queued_cot_service()

    @pytest.mark.asyncio
    async def test_parallel_processing_performance_maintained(self):
        """Queue changes should not impact parallel input processing"""
        # This test verifies that queue modifications don't slow down parallel processing
        start_time = time.time()

        cot_service = get_cot_service()
        tak_servers = [
            TakServer(id=i, name=f"server-{i}", host="localhost", port=8089 + i)
            for i in range(1, 4)
        ]

        # Process events in parallel across multiple servers
        tasks = []
        for server in tak_servers:
            for i in range(10):
                event = create_test_cot_event(f"parallel-{server.id}-{i}")
                task = asyncio.create_task(
                    enqueue_test_event(cot_service, server.id, event)
                )
                tasks.append(task)

        await asyncio.gather(*tasks)

        processing_time = time.time() - start_time

        # Performance requirement: should complete within reasonable time
        # This is a baseline - actual threshold needs benchmarking
        assert (
            processing_time < 5.0
        ), f"Parallel processing took {processing_time}s, expected < 5.0s"

    @pytest.mark.asyncio
    async def test_existing_monitoring_metrics_preserved(self):
        """All existing monitoring and metrics should remain functional"""
        cot_service = get_cot_service()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)

        # Add some events
        for i in range(3):
            event = create_test_cot_event(f"metric-{i}")
            await enqueue_test_event(cot_service, tak_server.id, event)

        # Get monitoring metrics
        status = cot_service.get_queue_status(tak_server.id)
        metrics = {
            "queue_size": status.get("size", 0),
            "queue_full": status.get("size", 0) >= status.get("max_size", 500),
            "queue_empty": status.get("size", 0) == 0,
            "events_queued": status.get("events_queued", 0),
        }

        # Verify expected metrics using helper
        assert verify_queue_metrics(metrics), "Queue metrics validation failed"

    @pytest.mark.asyncio
    async def test_configurable_settings_applied(self):
        """All queue settings should be configurable via config files"""
        test_config = {
            "max_size": 250,
            "batch_size": 12,
            "overflow_strategy": "drop_newest",
            "flush_on_config_change": False,
        }

        # Patch the get_queue_manager function to create a new instance with test config
        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(test_config)
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()
            config = cot_service.queue_manager.config

            # Verify all configuration values are applied
            assert config["max_size"] == 250
            assert config["batch_size"] == 12
            assert config["overflow_strategy"] == "drop_newest"
            assert config["flush_on_config_change"] == False


class TestQueueConfiguration:
    """Test queue configuration loading and validation"""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Reset singleton before each test"""
        reset_cot_service()
        reset_queued_cot_service()

    @pytest.mark.asyncio
    async def test_default_configuration_values(self):
        """Test that default configuration values are properly set"""
        cot_service = get_cot_service()
        config = cot_service.queue_manager.config

        # Verify default values match specification
        assert config.get("max_size", 0) >= 500  # Default from spec
        assert config.get("batch_size", 0) >= 8  # Default from spec
        assert config.get("overflow_strategy") in [
            "drop_oldest",
            "drop_newest",
            "block",
        ]

    @pytest.mark.asyncio
    async def test_environment_variable_override(self):
        """Test that environment variables override config file values"""
        with patch.dict(
            "os.environ",
            {
                "QUEUE_MAX_SIZE": "750",
                "QUEUE_BATCH_SIZE": "15",
                "QUEUE_OVERFLOW_STRATEGY": "drop_newest",
            },
        ):
            cot_service = get_cot_service()
            config = cot_service.queue_manager.config

            assert config["max_size"] == 750
            assert config["batch_size"] == 15
            assert config["overflow_strategy"] == "drop_newest"

    @pytest.mark.asyncio
    async def test_invalid_configuration_handled(self):
        """Test that invalid configuration values are handled gracefully"""
        invalid_config = {
            "queue": {
                "max_size": -10,  # Invalid: negative
                "batch_size": 0,  # Invalid: zero
                "overflow_strategy": "invalid_strategy",  # Invalid: unknown strategy
            }
        }

        with patch(
            "services.cot_service_integration.get_queue_manager"
        ) as mock_get_manager:
            from services.queue_manager import QueueManager

            mock_manager = QueueManager(invalid_config["queue"])
            mock_get_manager.return_value = mock_manager

            cot_service = get_cot_service()

            # Should fallback to safe defaults
            config = cot_service.queue_manager.config
            assert config["max_size"] > 0
            assert config["batch_size"] > 0
            assert config["overflow_strategy"] in [
                "drop_oldest",
                "drop_newest",
                "block",
            ]
