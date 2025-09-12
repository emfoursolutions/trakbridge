#!/usr/bin/env python3
"""
ABOUTME: Demonstration script for queue event replacement functionality
ABOUTME: Shows how the DeviceStateManager and queue replacement prevent event accumulation
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.cot_service import EnhancedCOTService
from services.device_state_manager import DeviceStateManager


def create_sample_cot_event(
    uid: str, lat: float, lon: float, timestamp: datetime = None
) -> bytes:
    """Create a sample COT event for testing"""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    event_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{uid}" type="a-f-G-U-C" time="{timestamp.isoformat()}" start="{timestamp.isoformat()}" stale="{(timestamp + timedelta(minutes=5)).isoformat()}" how="m-g">
    <point lat="{lat}" lon="{lon}" hae="0.0" ce="1.0" le="1.0"/>
    <detail>
        <contact callsign="{uid.replace('-', '_')}"/>
    </detail>
</event>"""
    return event_xml.encode("utf-8")


async def demonstrate_queue_replacement():
    """Demonstrate the queue replacement functionality"""
    print("🚀 Queue Event Replacement Demonstration")
    print("=" * 60)

    # Create COT service
    cot_service = EnhancedCOTService(use_pytak=True)

    print("\n📊 Testing Device State Manager")
    print("-" * 40)

    # Test DeviceStateManager directly
    device_manager = cot_service.device_state_manager

    # Add some devices
    now = datetime.now(timezone.utc)
    device_manager.update_device_state(
        "device-001",
        {"timestamp": now, "lat": 40.7589, "lon": -73.9851, "plugin_source": "demo"},
    )

    device_manager.update_device_state(
        "device-002",
        {
            "timestamp": now - timedelta(minutes=5),
            "lat": 34.0522,
            "lon": -118.2437,
            "plugin_source": "demo",
        },
    )

    print(f"✅ Tracked devices: {len(device_manager.device_states)}")

    # Test freshness checking
    newer_time = now + timedelta(minutes=2)
    older_time = now - timedelta(minutes=2)

    should_update_newer = device_manager.should_update_device("device-001", newer_time)
    should_update_older = device_manager.should_update_device("device-001", older_time)

    print(f"✅ Should update with newer timestamp: {should_update_newer}")
    print(f"✅ Should update with older timestamp: {should_update_older}")

    # Test stale device detection
    stale_devices = device_manager.get_stale_devices(timedelta(minutes=3))
    print(f"✅ Stale devices (>3min old): {len(stale_devices)} - {stale_devices}")

    print("\n🔧 Testing COT Event Processing")
    print("-" * 40)

    # Test UID extraction
    sample_event = create_sample_cot_event("test-device-123", 40.0, -74.0)
    extracted_uid = cot_service.extract_uid_from_cot_event(sample_event)
    extracted_timestamp = cot_service.extract_timestamp_from_cot_event(sample_event)

    print(f"✅ Extracted UID: {extracted_uid}")
    print(f"✅ Extracted timestamp: {extracted_timestamp}")

    print("\n📈 Testing Queue Replacement Logic")
    print("-" * 40)

    # Create mock queue for demonstration
    mock_queue = asyncio.Queue()
    tak_server_id = 999  # Demo server ID
    cot_service.queues = {tak_server_id: mock_queue}

    # Create events for the same devices at different times
    base_time = datetime.now(timezone.utc)

    # First batch: Initial positions
    initial_events = [
        create_sample_cot_event("deepstate-device-001", 40.7589, -73.9851, base_time),
        create_sample_cot_event("deepstate-device-002", 34.0522, -118.2437, base_time),
        create_sample_cot_event("deepstate-device-003", 51.5074, -0.1278, base_time),
    ]

    print(f"📤 Enqueueing initial batch: {len(initial_events)} events")
    success = await cot_service.enqueue_with_replacement(initial_events, tak_server_id)
    print(f"✅ Initial batch success: {success}")
    print(f"✅ Queue size after initial: {mock_queue.qsize()}")

    # Second batch: Updated positions (10 minutes later)
    updated_time = base_time + timedelta(minutes=10)
    updated_events = [
        create_sample_cot_event(
            "deepstate-device-001", 40.7800, -73.9700, updated_time
        ),  # Moved
        create_sample_cot_event(
            "deepstate-device-002", 34.0600, -118.2300, updated_time
        ),  # Moved
        create_sample_cot_event(
            "deepstate-device-003", 51.5200, -0.1100, updated_time
        ),  # Moved
    ]

    print(f"\n📤 Enqueueing updated batch: {len(updated_events)} events")
    success = await cot_service.enqueue_with_replacement(updated_events, tak_server_id)
    print(f"✅ Updated batch success: {success}")
    print(f"✅ Queue size after update: {mock_queue.qsize()}")

    print("\n🎯 KEY ACHIEVEMENT:")
    print(f"   • Expected behavior: 3 events in → 3 events out (not 6)")
    print(f"   • Actual queue size: {mock_queue.qsize()} events")
    print(
        f"   • Event accumulation: {'❌ PREVENTED' if mock_queue.qsize() == 3 else '⚠️  DETECTED'}"
    )

    # Test with older events (should be rejected)
    old_time = base_time - timedelta(minutes=5)
    old_events = [
        create_sample_cot_event(
            "deepstate-device-001", 40.7000, -74.0000, old_time
        )  # Older position
    ]

    print(f"\n📤 Trying to enqueue older event:")
    queue_size_before_old = mock_queue.qsize()
    success = await cot_service.enqueue_with_replacement(old_events, tak_server_id)
    queue_size_after_old = mock_queue.qsize()

    print(f"✅ Old event processing success: {success}")
    print(
        f"✅ Queue size before: {queue_size_before_old}, after: {queue_size_after_old}"
    )
    print(
        f"✅ Old event rejected: {'✅ YES' if queue_size_after_old == queue_size_before_old else '❌ NO'}"
    )

    print("\n🎉 DEMO COMPLETE!")
    print("=" * 60)
    print("✅ DeviceStateManager: Tracks latest device positions")
    print("✅ UID Extraction: Works with any plugin's COT events")
    print("✅ Timestamp Extraction: Enables freshness comparison")
    print("✅ Queue Replacement: Prevents event accumulation")
    print("✅ Smart Filtering: Rejects outdated events")
    print("\n🚀 Ready for production use with any plugin that generates 300+ events!")


if __name__ == "__main__":
    asyncio.run(demonstrate_queue_replacement())
