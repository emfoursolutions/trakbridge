"""
ABOUTME: Unit tests for queue event replacement logic - prevents event accumulation
ABOUTME: Tests follow TDD principles - all tests initially FAIL until implementation is complete
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from typing import List, Dict, Any
import xml.etree.ElementTree as ET
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from services.cot_service import PersistentCOTService
from tests.fixtures.mock_location_data import generate_mock_gps_points


class TestQueueReplacement:
    """
    TDD Tests for Generic Queue Event Replacement System
    All tests should FAIL initially until enhanced queue logic is implemented
    """

    @pytest.fixture
    def cot_service(self):
        """Create COT service instance for testing"""
        return PersistentCOTService()

    @pytest.fixture
    def sample_cot_events(self):
        """Sample COT events from different devices"""
        base_time = datetime.now(timezone.utc)
        
        # Create COT XML events with different UIDs
        events = []
        for i in range(3):
            event_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="device-{i:03d}" type="a-f-G-U-C" time="{base_time.isoformat()}" start="{base_time.isoformat()}" stale="{(base_time + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="{40.0 + i}" lon="{-74.0 + i}" hae="0.0" ce="1.0" le="1.0"/>
    <detail>
        <contact callsign="TestDevice{i:03d}"/>
    </detail>
</event>"""
            events.append(event_xml.encode('utf-8'))
        
        return events

    @pytest.fixture  
    def updated_cot_events(self):
        """Updated COT events for same devices with newer timestamps"""
        base_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        
        events = []
        for i in range(3):
            event_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="device-{i:03d}" type="a-f-G-U-C" time="{base_time.isoformat()}" start="{base_time.isoformat()}" stale="{(base_time + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="{45.0 + i}" lon="{-79.0 + i}" hae="10.0" ce="1.0" le="1.0"/>
    <detail>
        <contact callsign="TestDevice{i:03d}"/>
    </detail>
</event>"""
            events.append(event_xml.encode('utf-8'))
        
        return events

    def test_extract_uid_from_cot_event_method_exists(self, cot_service):
        """
        Test that extract_uid_from_cot_event method exists
        STATUS: WILL FAIL - method doesn't exist yet
        """
        assert hasattr(cot_service, 'extract_uid_from_cot_event'), \
            "Should have extract_uid_from_cot_event method"
        assert callable(cot_service.extract_uid_from_cot_event), \
            "extract_uid_from_cot_event should be callable"

    def test_extract_uid_from_cot_event_extracts_correctly(self, cot_service, sample_cot_events):
        """
        Test that UID extraction works for any plugin's COT events
        STATUS: WILL FAIL - method doesn't exist
        """
        event = sample_cot_events[0]
        uid = cot_service.extract_uid_from_cot_event(event)
        
        assert uid == "device-000", f"Should extract UID 'device-000', got '{uid}'"

    def test_extract_uid_from_invalid_cot_event(self, cot_service):
        """
        Test that UID extraction handles invalid XML gracefully
        STATUS: WILL FAIL - method doesn't exist
        """
        invalid_event = b"<invalid>not a proper COT event</invalid>"
        
        uid = cot_service.extract_uid_from_cot_event(invalid_event)
        
        assert uid is None, "Should return None for invalid COT events"

    def test_extract_timestamp_from_cot_event_method_exists(self, cot_service):
        """
        Test that extract_timestamp_from_cot_event method exists  
        STATUS: WILL FAIL - method doesn't exist yet
        """
        assert hasattr(cot_service, 'extract_timestamp_from_cot_event'), \
            "Should have extract_timestamp_from_cot_event method"
        assert callable(cot_service.extract_timestamp_from_cot_event), \
            "extract_timestamp_from_cot_event should be callable"

    def test_extract_timestamp_from_cot_event_extracts_correctly(self, cot_service, sample_cot_events):
        """
        Test that timestamp extraction works for COT events
        STATUS: WILL FAIL - method doesn't exist
        """
        event = sample_cot_events[0]
        timestamp = cot_service.extract_timestamp_from_cot_event(event)
        
        assert isinstance(timestamp, datetime), "Should return datetime object"
        assert timestamp.tzinfo is not None, "Should have timezone info"

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_method_exists(self, cot_service):
        """
        Test that enqueue_with_replacement method exists
        STATUS: WILL FAIL - method doesn't exist yet
        """
        assert hasattr(cot_service, 'enqueue_with_replacement'), \
            "Should have enqueue_with_replacement method"
        assert callable(cot_service.enqueue_with_replacement), \
            "enqueue_with_replacement should be callable"

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_adds_new_events(self, cot_service, sample_cot_events):
        """
        Test that new events are added to queue normally
        STATUS: WILL FAIL - method doesn't exist
        """
        tak_server_id = 1
        
        # Mock the queue
        mock_queue = Mock()
        mock_queue.qsize.return_value = 0
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock device state manager
        mock_device_manager = Mock()
        mock_device_manager.should_update_device.return_value = True
        mock_device_manager.device_states = {}  # Empty dict for new devices
        cot_service.device_state_manager = mock_device_manager
        
        # Mock UID extraction to return different UIDs for each event
        cot_service.extract_uid_from_cot_event = Mock(side_effect=["device-000", "device-001", "device-002"])
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=datetime.now(timezone.utc))
        
        # Test enqueueing new events
        result = await cot_service.enqueue_with_replacement(sample_cot_events, tak_server_id)
        
        assert result is True, "Should successfully enqueue new events"
        assert mock_queue.put.call_count == len(sample_cot_events), \
            f"Should call put {len(sample_cot_events)} times"

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_replaces_old_events(self, cot_service, sample_cot_events, updated_cot_events):
        """
        Test that old events are replaced by newer ones for same device
        STATUS: WILL FAIL - method doesn't exist
        """
        tak_server_id = 1
        
        # Mock the queue with existing events
        mock_queue = Mock()
        mock_queue.qsize.return_value = 3
        mock_queue.put = AsyncMock()
        # Simulate queue containing old events
        mock_queue._queue = list(sample_cot_events)  # Internal queue state
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock device state manager - devices exist and should be updated
        mock_device_manager = Mock()
        mock_device_manager.should_update_device.return_value = True
        mock_device_manager.device_states = {"device-000": {}, "device-001": {}, "device-002": {}}  # Existing devices
        cot_service.device_state_manager = mock_device_manager
        
        # Mock UID extraction to return consistent UIDs
        cot_service.extract_uid_from_cot_event = Mock(side_effect=lambda e: f"device-{len(e) % 3:03d}")
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=datetime.now(timezone.utc))
        
        # Use patch to mock remove_events_by_uid method
        with patch.object(cot_service, 'remove_events_by_uid', AsyncMock(return_value=3)) as mock_remove:
            # Test enqueueing updated events
            result = await cot_service.enqueue_with_replacement(updated_cot_events, tak_server_id)
            
            assert result is True, "Should successfully replace events"
            assert mock_remove.called, "Should call remove_events_by_uid"

    def test_remove_events_by_uid_method_exists(self, cot_service):
        """
        Test that remove_events_by_uid method exists
        STATUS: WILL FAIL - method doesn't exist yet
        """
        assert hasattr(cot_service, 'remove_events_by_uid'), \
            "Should have remove_events_by_uid method"
        assert callable(cot_service.remove_events_by_uid), \
            "remove_events_by_uid should be callable"

    @pytest.mark.asyncio
    async def test_remove_events_by_uid_removes_matching_events(self, cot_service, sample_cot_events):
        """
        Test that remove_events_by_uid removes events with matching UIDs
        STATUS: WILL FAIL - method doesn't exist
        """
        tak_server_id = 1
        
        # Mock the queue with events
        mock_queue = Mock()
        # Set up proper queue behavior - start with events, then empty
        mock_queue.empty.side_effect = [False, False, False, True]  # 3 events then empty
        mock_queue.get_nowait.side_effect = sample_cot_events  # Return the events in order
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock UID extraction to return predictable UIDs
        cot_service.extract_uid_from_cot_event = Mock(side_effect=["device-000", "device-001", "device-002"])
        
        # Remove events for specific UIDs
        uids_to_remove = ["device-000", "device-001"]
        removed_count = await cot_service.remove_events_by_uid(tak_server_id, uids_to_remove)
        
        assert removed_count == 2, f"Should remove 2 events, removed {removed_count}"

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_logs_replacement_stats(self, cot_service, sample_cot_events):
        """
        Test that replacement statistics are logged
        STATUS: WILL FAIL - logging not implemented
        """
        tak_server_id = 1
        
        # Setup mocks
        mock_queue = Mock()
        mock_queue.qsize.return_value = 0
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        mock_device_manager = Mock()
        mock_device_manager.should_update_device.return_value = True
        mock_device_manager.device_states = {"device-001": {}}  # Device exists
        cot_service.device_state_manager = mock_device_manager
        
        cot_service.extract_uid_from_cot_event = Mock(return_value="device-001")
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=datetime.now(timezone.utc))
        cot_service.remove_events_by_uid = AsyncMock(return_value=1)  # Mock removal
        
        # Test with logging capture
        with patch('services.cot_service.logger') as mock_logger:
            await cot_service.enqueue_with_replacement(sample_cot_events, tak_server_id)
            
            # Should log replacement statistics
            assert any("replacement statistics" in str(call) for call in mock_logger.info.call_args_list), \
                "Should log replacement statistics"

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_handles_mixed_new_and_updated_events(self, cot_service):
        """
        Test handling mix of completely new devices and updated existing devices
        STATUS: WILL FAIL - complex logic not implemented
        """
        tak_server_id = 1
        
        # Create mix of events - some new, some updates
        base_time = datetime.now(timezone.utc)
        mixed_events = []
        
        # New device
        new_event = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="new-device-999" type="a-f-G-U-C" time="{base_time.isoformat()}" start="{base_time.isoformat()}" stale="{(base_time + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="50.0" lon="-80.0" hae="0.0" ce="1.0" le="1.0"/>
</event>""".encode('utf-8')
        mixed_events.append(new_event)
        
        # Updated existing device
        update_event = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="device-000" type="a-f-G-U-C" time="{base_time.isoformat()}" start="{base_time.isoformat()}" stale="{(base_time + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="55.0" lon="-85.0" hae="5.0" ce="1.0" le="1.0"/>
</event>""".encode('utf-8')
        mixed_events.append(update_event)
        
        # Setup mocks
        mock_queue = Mock()
        mock_queue.qsize.return_value = 1  # One existing event
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock device state manager - new device is new, existing device should be updated
        mock_device_manager = Mock()
        def mock_should_update(uid, timestamp):
            return uid == "new-device-999" or uid == "device-000"  # Both should be processed
        mock_device_manager.should_update_device.side_effect = mock_should_update
        mock_device_manager.device_states = {"device-000": {}}  # Only device-000 exists, new-device-999 is new
        cot_service.device_state_manager = mock_device_manager
        
        # Mock UID extraction
        def mock_extract_uid(event):
            if b"new-device-999" in event:
                return "new-device-999"
            return "device-000"
        cot_service.extract_uid_from_cot_event = Mock(side_effect=mock_extract_uid)
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=base_time)
        
        # Mock removal method
        cot_service.remove_events_by_uid = AsyncMock(return_value=1)
        
        result = await cot_service.enqueue_with_replacement(mixed_events, tak_server_id)
        
        assert result is True, "Should handle mixed event types successfully"
        # Should remove old events for both devices (they both passed should_update_device)
        cot_service.remove_events_by_uid.assert_called_once_with(tak_server_id, ["new-device-999", "device-000"])

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_skips_older_events(self, cot_service):
        """
        Test that older events are skipped and not enqueued
        STATUS: WILL FAIL - timestamp comparison not implemented
        """
        tak_server_id = 1
        
        # Create old event
        old_time = datetime.now(timezone.utc) - timedelta(hours=1)
        old_event = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="device-000" type="a-f-G-U-C" time="{old_time.isoformat()}" start="{old_time.isoformat()}" stale="{(old_time + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="40.0" lon="-74.0" hae="0.0" ce="1.0" le="1.0"/>
</event>""".encode('utf-8')
        
        # Setup mocks
        mock_queue = Mock()
        mock_queue.qsize.return_value = 0
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock device state manager - should NOT update old events
        mock_device_manager = Mock()
        mock_device_manager.should_update_device.return_value = False  # Device has newer data
        cot_service.device_state_managers = {tak_server_id: mock_device_manager}
        
        cot_service.extract_uid_from_cot_event = Mock(return_value="device-000")
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=old_time)
        
        result = await cot_service.enqueue_with_replacement([old_event], tak_server_id)
        
        assert result is True, "Should complete successfully"
        # Should NOT call put since event is too old
        mock_queue.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_enqueue_with_replacement_queue_size_stabilization(self, cot_service, sample_cot_events, updated_cot_events):
        """
        Test key requirement: 300 events in → ~300 events processed (not 600+)
        STATUS: WILL FAIL - size stabilization not implemented
        """
        tak_server_id = 1
        
        # Simulate queue already has 300 events from previous fetch
        mock_queue = Mock()
        mock_queue.qsize.side_effect = [300, 300]  # Before and after should be similar
        mock_queue.put = AsyncMock()
        cot_service.queues = {tak_server_id: mock_queue}
        
        # Mock device state manager - all devices should be updated
        mock_device_manager = Mock()
        mock_device_manager.should_update_device.return_value = True
        # Create device_states dict with 300 devices to simulate existing devices
        mock_device_manager.device_states = {f"device-{i:03d}": {} for i in range(300)}
        cot_service.device_state_manager = mock_device_manager
        
        # Mock that we remove old events for all UIDs - use a counter to generate unique UIDs
        uid_counter = 0
        def generate_unique_uid(event):
            nonlocal uid_counter
            uid = f"device-{uid_counter:03d}"
            uid_counter += 1
            return uid
        
        cot_service.extract_uid_from_cot_event = Mock(side_effect=generate_unique_uid)
        cot_service.extract_timestamp_from_cot_event = Mock(return_value=datetime.now(timezone.utc))
        cot_service.remove_events_by_uid = AsyncMock(return_value=300)  # Remove 300 old events
        
        # Create 300 events (simulating Deepstate fetch)
        large_event_batch = [sample_cot_events[0]] * 300  # Each will get unique UID from mock
        
        result = await cot_service.enqueue_with_replacement(large_event_batch, tak_server_id)
        
        assert result is True, "Should handle large batch successfully"
        
        # Key test: should remove old events before adding new ones
        cot_service.remove_events_by_uid.assert_called_once()
        
        # Should add exactly the same number of new events
        assert mock_queue.put.call_count == 300, \
            f"Should add 300 new events, added {mock_queue.put.call_count}"


if __name__ == "__main__":
    # Run tests to verify they all FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])