"""
ABOUTME: TDD tests for Phase 1 - Per-server DeviceStateManager fix for multi-server distribution
ABOUTME: Tests the core bug fix where shared DeviceStateManager prevents events reaching subsequent servers
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from services.cot_service_integration import QueuedCOTService
from services.device_state_manager import DeviceStateManager


class TestPersistentCOTMultiServer:
    """
    TDD Tests for Phase 1: Multi-server DeviceStateManager fix
    These tests will FAIL initially until per-server DeviceStateManager is implemented
    """

    @pytest.fixture
    def persistent_cot_service(self):
        """Create QueuedCOTService instance for testing"""
        from services.cot_service import get_cot_service, reset_cot_service

        # Reset singleton to ensure clean state
        reset_cot_service()
        return get_cot_service()

    @pytest.fixture
    def sample_cot_events(self):
        """Sample COT events for testing multi-server distribution"""
        base_time = datetime.now(timezone.utc)

        # Create COT events with embedded UIDs and timestamps
        events = []
        for i in range(3):
            cot_xml = f"""<?xml version="1.0"?>
<event version="2.0" uid="device-{i:03d}" type="a-f-G-U-C" how="m-g" 
       time="{base_time.isoformat()}" start="{base_time.isoformat()}" 
       stale="{(base_time + timedelta(hours=1)).isoformat()}">
    <point lat="{40.7589 + i*0.001}" lon="{-73.9851 + i*0.001}" hae="15.0" ce="10.0" le="10.0"/>
    <detail>
        <contact callsign="Test-Device-{i:03d}"/>
    </detail>
</event>"""
            events.append(cot_xml.encode("utf-8"))

        return events

    @pytest.fixture
    def mock_tak_servers(self):
        """Mock TAK servers for testing"""
        servers = []
        for i in range(3):
            server = Mock()
            server.id = i + 1
            server.name = f"TAK-Server-{i+1}"
            server.host = f"tak{i+1}.example.com"
            server.port = 8087
            servers.append(server)
        return servers

    @pytest.mark.xfail(
        reason="TDD test - per-server DeviceStateManager not implemented"
    )
    def test_multi_server_event_distribution(
        self, persistent_cot_service, sample_cot_events, mock_tak_servers
    ):
        """
        FAIL initially - Test that same COT events reach all configured TAK servers

        This is the core bug: shared DeviceStateManager causes events to be skipped
        for subsequent servers because timestamps are already "seen"
        """

        # Setup queues for multiple servers
        for server in mock_tak_servers:
            persistent_cot_service.queues[server.id] = asyncio.Queue()

        async def run_test():
            # Enqueue same events for all servers (this is the problematic scenario)
            results = []
            for server in mock_tak_servers:
                result = await persistent_cot_service.enqueue_with_replacement(
                    sample_cot_events, server.id
                )
                results.append(result)

            # All servers should receive all events
            for server in mock_tak_servers:
                queue_size = persistent_cot_service.queues[server.id].qsize()
                assert queue_size == len(sample_cot_events), (
                    f"Server {server.id} should have received {len(sample_cot_events)} events, "
                    f"but queue size is {queue_size}. This indicates the shared DeviceStateManager bug."
                )

            # All operations should succeed
            assert all(results), "All enqueue operations should succeed"

        # This test will FAIL with current implementation due to shared device state
        asyncio.run(run_test())

    @pytest.mark.xfail(
        reason="TDD test - per-server DeviceStateManager not implemented"
    )
    def test_per_server_isolation(
        self, persistent_cot_service, sample_cot_events, mock_tak_servers
    ):
        """
        FAIL initially - Test that each server maintains independent device state

        Each server should track device state independently - updating device state
        for one server should not affect device state decisions for other servers
        """

        # Setup queues for multiple servers
        for server in mock_tak_servers:
            persistent_cot_service.queues[server.id] = asyncio.Queue()

        async def run_test():
            # Send initial events to first server
            await persistent_cot_service.enqueue_with_replacement(
                sample_cot_events, mock_tak_servers[0].id
            )

            # Create newer events for same devices
            newer_time = datetime.now(timezone.utc) + timedelta(minutes=5)
            newer_events = []
            for i in range(3):
                cot_xml = f"""<?xml version="1.0"?>
<event version="2.0" uid="device-{i:03d}" type="a-f-G-U-C" how="m-g" 
       time="{newer_time.isoformat()}" start="{newer_time.isoformat()}" 
       stale="{(newer_time + timedelta(hours=1)).isoformat()}">
    <point lat="{40.7589 + i*0.001 + 0.01}" lon="{-73.9851 + i*0.001 + 0.01}" hae="15.0" ce="10.0" le="10.0"/>
    <detail>
        <contact callsign="Test-Device-{i:03d}"/>
    </detail>
</event>"""
                newer_events.append(cot_xml.encode("utf-8"))

            # Send newer events to second server - should be accepted since device state is independent
            result = await persistent_cot_service.enqueue_with_replacement(
                newer_events, mock_tak_servers[1].id
            )

            assert (
                result
            ), "Second server should accept newer events with independent device state"

            # Second server should have received all newer events
            queue_size = persistent_cot_service.queues[mock_tak_servers[1].id].qsize()
            assert queue_size == len(newer_events), (
                f"Second server should have received {len(newer_events)} newer events, "
                f"but queue size is {queue_size}. This indicates device state is shared, not per-server."
            )

        # This test will FAIL with current implementation due to shared device state
        asyncio.run(run_test())

    @pytest.mark.xfail(
        reason="TDD test - per-server DeviceStateManager not implemented"
    )
    def test_backward_compatibility(self, persistent_cot_service, sample_cot_events):
        """
        FAIL initially - Test that single-server configurations continue working unchanged

        Single server usage should work exactly as before - no behavior changes
        """

        single_server = Mock()
        single_server.id = 1
        single_server.name = "Single-TAK-Server"

        # Setup single server queue
        persistent_cot_service.queues[single_server.id] = asyncio.Queue()

        async def run_test():
            # Single server operations should work exactly as before
            result = await persistent_cot_service.enqueue_with_replacement(
                sample_cot_events, single_server.id
            )

            assert result, "Single server operations should continue working"

            queue_size = persistent_cot_service.queues[single_server.id].qsize()
            assert queue_size == len(sample_cot_events), (
                f"Single server should receive all {len(sample_cot_events)} events, "
                f"got {queue_size}"
            )

            # Test event replacement behavior still works
            duplicate_events = sample_cot_events.copy()
            result2 = await persistent_cot_service.enqueue_with_replacement(
                duplicate_events, single_server.id
            )

            assert result2, "Duplicate event handling should work"

            # Queue size should not increase (events replaced, not added)
            final_queue_size = persistent_cot_service.queues[single_server.id].qsize()
            assert final_queue_size == len(sample_cot_events), (
                f"Queue size should remain {len(sample_cot_events)} after duplicate events, "
                f"got {final_queue_size}. Event replacement should still work."
            )

        # This test should pass even with current implementation
        asyncio.run(run_test())

    @pytest.mark.xfail(
        reason="TDD test - per-server DeviceStateManager not implemented"
    )
    def test_event_ordering(self, persistent_cot_service, mock_tak_servers):
        """
        FAIL initially - Test that timestamps and UID handling remain correct across servers

        Event ordering and timestamp comparison should work correctly per server
        """

        # Setup queues for multiple servers
        for server in mock_tak_servers:
            persistent_cot_service.queues[server.id] = asyncio.Queue()

        async def run_test():
            base_time = datetime.now(timezone.utc)

            # Create events with different timestamps for same device
            old_event_xml = f"""<?xml version="1.0"?>
<event version="2.0" uid="test-device" type="a-f-G-U-C" how="m-g" 
       time="{base_time.isoformat()}" start="{base_time.isoformat()}" 
       stale="{(base_time + timedelta(hours=1)).isoformat()}">
    <point lat="40.7589" lon="-73.9851" hae="15.0" ce="10.0" le="10.0"/>
    <detail>
        <contact callsign="Test-Device"/>
    </detail>
</event>"""

            new_time = base_time + timedelta(minutes=10)
            new_event_xml = f"""<?xml version="1.0"?>
<event version="2.0" uid="test-device" type="a-f-G-U-C" how="m-g" 
       time="{new_time.isoformat()}" start="{new_time.isoformat()}" 
       stale="{(new_time + timedelta(hours=1)).isoformat()}">
    <point lat="40.7690" lon="-73.9750" hae="15.0" ce="10.0" le="10.0"/>
    <detail>
        <contact callsign="Test-Device"/>
    </detail>
</event>"""

            old_events = [old_event_xml.encode("utf-8")]
            new_events = [new_event_xml.encode("utf-8")]

            # Send old event to first server
            await persistent_cot_service.enqueue_with_replacement(
                old_events, mock_tak_servers[0].id
            )

            # Send new event to same server - should replace old event
            await persistent_cot_service.enqueue_with_replacement(
                new_events, mock_tak_servers[0].id
            )

            # First server should have only 1 event (new one replaced old one)
            queue_size_1 = persistent_cot_service.queues[mock_tak_servers[0].id].qsize()
            assert (
                queue_size_1 == 1
            ), f"First server should have 1 event after replacement, got {queue_size_1}"

            # Send old event to second server - should be rejected due to independent per-server state
            # But with current shared state, this might be accepted incorrectly
            await persistent_cot_service.enqueue_with_replacement(
                old_events, mock_tak_servers[1].id
            )

            # Second server should accept old event since it has independent device state
            queue_size_2 = persistent_cot_service.queues[mock_tak_servers[1].id].qsize()
            assert queue_size_2 == 1, (
                f"Second server should accept old event with independent device state, "
                f"queue size: {queue_size_2}"
            )

        # This test will FAIL with current shared device state implementation
        asyncio.run(run_test())

    def test_device_state_manager_per_server_access(
        self, persistent_cot_service, mock_tak_servers
    ):
        """
        FAIL initially - Test that QueuedCOTService has per-server DeviceStateManager instances

        This tests the actual implementation change from single device_state_manager
        to device_state_managers dict
        """

        # This test will FAIL until the implementation is changed
        # Current implementation has single device_state_manager
        # New implementation should have device_state_managers dict

        # Test that device_state_managers attribute exists and is a dict
        assert hasattr(
            persistent_cot_service, "device_state_managers"
        ), "QueuedCOTService should have device_state_managers dict attribute"

        assert isinstance(
            persistent_cot_service.device_state_managers, dict
        ), "device_state_managers should be a dictionary"

        # Test lazy initialization - accessing manager for server should create it
        server_id = mock_tak_servers[0].id

        # Initially should be empty
        assert (
            len(persistent_cot_service.device_state_managers) == 0
        ), "device_state_managers should start empty"

        # After accessing for a server, should have entry for that server
        # This would be done internally in enqueue_with_replacement, but we can test the concept

        # Simulate accessing device state manager for server
        if server_id not in persistent_cot_service.device_state_managers:
            persistent_cot_service.device_state_managers[server_id] = (
                DeviceStateManager()
            )

        assert (
            server_id in persistent_cot_service.device_state_managers
        ), f"Server {server_id} should have device state manager after access"

        assert isinstance(
            persistent_cot_service.device_state_managers[server_id], DeviceStateManager
        ), "Each server should have DeviceStateManager instance"

        # Test that different servers have different DeviceStateManager instances
        server_id_2 = mock_tak_servers[1].id
        if server_id_2 not in persistent_cot_service.device_state_managers:
            persistent_cot_service.device_state_managers[server_id_2] = (
                DeviceStateManager()
            )

        assert (
            persistent_cot_service.device_state_managers[server_id]
            is not persistent_cot_service.device_state_managers[server_id_2]
        ), "Different servers should have separate DeviceStateManager instances"

    @pytest.mark.xfail(
        reason="TDD test - per-server DeviceStateManager not implemented"
    )
    def test_memory_usage_acceptable(
        self, persistent_cot_service, mock_tak_servers, sample_cot_events
    ):
        """
        FAIL initially - Test that memory usage scales reasonably with O(devices × servers)

        This validates the memory impact mentioned in the spec
        """

        # Setup queues for all servers
        for server in mock_tak_servers:
            persistent_cot_service.queues[server.id] = asyncio.Queue()

        async def run_test():
            # Send events to all servers
            for server in mock_tak_servers:
                await persistent_cot_service.enqueue_with_replacement(
                    sample_cot_events, server.id
                )

            # Check that we have device state managers for each server
            expected_servers = len(mock_tak_servers)
            actual_managers = len(persistent_cot_service.device_state_managers)

            assert (
                actual_managers == expected_servers
            ), f"Should have {expected_servers} device state managers, got {actual_managers}"

            # Check that each manager has device states
            devices_per_manager = len(sample_cot_events)
            for server in mock_tak_servers:
                manager = persistent_cot_service.device_state_managers[server.id]
                device_count = len(manager.device_states)

                assert device_count == devices_per_manager, (
                    f"Server {server.id} manager should track {devices_per_manager} devices, "
                    f"got {device_count}"
                )

            # Total memory usage should be O(devices × servers)
            # This is acceptable for hundreds of servers as mentioned in spec
            total_device_states = sum(
                len(manager.device_states)
                for manager in persistent_cot_service.device_state_managers.values()
            )

            expected_total = len(sample_cot_events) * len(mock_tak_servers)
            assert total_device_states == expected_total, (
                f"Total device states should be {expected_total} (devices × servers), "
                f"got {total_device_states}"
            )

        # This test will FAIL until per-server implementation is complete
        asyncio.run(run_test())


if __name__ == "__main__":
    # Run tests to verify they FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])
