"""
ABOUTME: Unit tests for DeviceStateManager - generic device state tracking for queue deduplication
ABOUTME: Tests follow TDD principles - all tests initially FAIL until implementation is complete
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, List
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

# Import will fail initially - this is expected in TDD RED phase
try:
    from services.device_state_manager import DeviceStateManager
except ImportError:
    DeviceStateManager = None


class TestDeviceStateManager:
    """
    TDD Tests for Generic Device State Management
    All tests should FAIL initially until DeviceStateManager is implemented
    """

    @pytest.fixture
    def device_manager(self):
        """Create DeviceStateManager instance for testing"""
        if DeviceStateManager is None:
            pytest.skip("DeviceStateManager not implemented yet")
        return DeviceStateManager()

    @pytest.fixture
    def sample_device_data(self):
        """Sample device data that any plugin might generate"""
        now = datetime.now(timezone.utc)
        return {
            "device_1": {
                "uid": "plugin-device-001",
                "timestamp": now,
                "lat": 40.7589,
                "lon": -73.9851,
                "plugin_source": "deepstate",
            },
            "device_2": {
                "uid": "plugin-device-002",
                "timestamp": now - timedelta(minutes=5),
                "lat": 34.0522,
                "lon": -118.2437,
                "plugin_source": "garmin",
            },
            "device_3": {
                "uid": "plugin-device-003",
                "timestamp": now - timedelta(minutes=10),
                "lat": 51.5074,
                "lon": -0.1278,
                "plugin_source": "spot",
            },
        }

    def test_device_state_manager_class_exists(self):
        """
        Basic test that DeviceStateManager class exists
        STATUS: WILL FAIL - class doesn't exist yet
        """
        assert DeviceStateManager is not None, "DeviceStateManager class should exist"

    def test_device_state_manager_initialization(self, device_manager):
        """
        Test that DeviceStateManager initializes with empty state
        STATUS: WILL FAIL - class doesn't exist
        """
        assert hasattr(
            device_manager, "device_states"
        ), "Should have device_states attribute"
        assert isinstance(
            device_manager.device_states, dict
        ), "device_states should be a dictionary"
        assert (
            len(device_manager.device_states) == 0
        ), "Should start with empty device states"

    def test_should_update_device_method_exists(self, device_manager):
        """
        Test that should_update_device method exists and is callable
        STATUS: WILL FAIL - method doesn't exist
        """
        assert hasattr(
            device_manager, "should_update_device"
        ), "Should have should_update_device method"
        assert callable(
            device_manager.should_update_device
        ), "should_update_device should be callable"

    def test_should_update_device_new_device(self, device_manager, sample_device_data):
        """
        Test that new device should always be updated
        STATUS: WILL FAIL - method doesn't exist
        """
        device_data = sample_device_data["device_1"]

        result = device_manager.should_update_device(
            device_data["uid"], device_data["timestamp"]
        )

        assert result is True, "New device should always be updated"

    def test_should_update_device_newer_timestamp(
        self, device_manager, sample_device_data
    ):
        """
        Test that device with newer timestamp should be updated
        STATUS: WILL FAIL - method doesn't exist
        """
        device_data = sample_device_data["device_1"]
        old_timestamp = device_data["timestamp"] - timedelta(minutes=5)
        new_timestamp = device_data["timestamp"]

        # First update with old timestamp
        device_manager.update_device_state(
            device_data["uid"],
            {
                "timestamp": old_timestamp,
                "lat": device_data["lat"],
                "lon": device_data["lon"],
            },
        )

        # Test with newer timestamp
        result = device_manager.should_update_device(device_data["uid"], new_timestamp)

        assert result is True, "Device with newer timestamp should be updated"

    def test_should_update_device_older_timestamp(
        self, device_manager, sample_device_data
    ):
        """
        Test that device with older timestamp should NOT be updated
        STATUS: WILL FAIL - method doesn't exist
        """
        device_data = sample_device_data["device_1"]
        new_timestamp = device_data["timestamp"]
        old_timestamp = device_data["timestamp"] - timedelta(minutes=5)

        # First update with new timestamp
        device_manager.update_device_state(
            device_data["uid"],
            {
                "timestamp": new_timestamp,
                "lat": device_data["lat"],
                "lon": device_data["lon"],
            },
        )

        # Test with older timestamp
        result = device_manager.should_update_device(device_data["uid"], old_timestamp)

        assert result is False, "Device with older timestamp should NOT be updated"

    def test_update_device_state_method_exists(self, device_manager):
        """
        Test that update_device_state method exists and is callable
        STATUS: WILL FAIL - method doesn't exist
        """
        assert hasattr(
            device_manager, "update_device_state"
        ), "Should have update_device_state method"
        assert callable(
            device_manager.update_device_state
        ), "update_device_state should be callable"

    def test_update_device_state_stores_data(self, device_manager, sample_device_data):
        """
        Test that update_device_state correctly stores device data
        STATUS: WILL FAIL - method doesn't exist
        """
        device_data = sample_device_data["device_1"]

        device_manager.update_device_state(
            device_data["uid"],
            {
                "timestamp": device_data["timestamp"],
                "lat": device_data["lat"],
                "lon": device_data["lon"],
                "plugin_source": device_data["plugin_source"],
            },
        )

        assert (
            device_data["uid"] in device_manager.device_states
        ), "Device UID should be stored"
        stored_data = device_manager.device_states[device_data["uid"]]
        assert (
            stored_data["timestamp"] == device_data["timestamp"]
        ), "Timestamp should match"
        assert stored_data["lat"] == device_data["lat"], "Latitude should match"
        assert stored_data["lon"] == device_data["lon"], "Longitude should match"

    def test_update_device_state_replaces_old_data(
        self, device_manager, sample_device_data
    ):
        """
        Test that update_device_state replaces old data for same device
        STATUS: WILL FAIL - method doesn't exist
        """
        device_data = sample_device_data["device_1"]
        uid = device_data["uid"]

        # First update
        old_lat, old_lon = 1.0, 1.0
        old_timestamp = device_data["timestamp"] - timedelta(minutes=5)
        device_manager.update_device_state(
            uid, {"timestamp": old_timestamp, "lat": old_lat, "lon": old_lon}
        )

        # Second update with new data
        device_manager.update_device_state(
            uid,
            {
                "timestamp": device_data["timestamp"],
                "lat": device_data["lat"],
                "lon": device_data["lon"],
            },
        )

        stored_data = device_manager.device_states[uid]
        assert stored_data["lat"] == device_data["lat"], "Should have new latitude"
        assert stored_data["lon"] == device_data["lon"], "Should have new longitude"
        assert (
            stored_data["timestamp"] == device_data["timestamp"]
        ), "Should have new timestamp"

    def test_get_stale_devices_method_exists(self, device_manager):
        """
        Test that get_stale_devices method exists and is callable
        STATUS: WILL FAIL - method doesn't exist
        """
        assert hasattr(
            device_manager, "get_stale_devices"
        ), "Should have get_stale_devices method"
        assert callable(
            device_manager.get_stale_devices
        ), "get_stale_devices should be callable"

    def test_get_stale_devices_finds_old_devices(
        self, device_manager, sample_device_data
    ):
        """
        Test that get_stale_devices correctly identifies old devices
        STATUS: WILL FAIL - method doesn't exist
        """
        # Add devices with different ages
        for device_id, device_data in sample_device_data.items():
            device_manager.update_device_state(
                device_data["uid"],
                {
                    "timestamp": device_data["timestamp"],
                    "lat": device_data["lat"],
                    "lon": device_data["lon"],
                },
            )

        # Find devices older than 8 minutes
        max_age = timedelta(minutes=8)
        stale_devices = device_manager.get_stale_devices(max_age)

        # Should find only device_3 (10 min old) - device_2 (5 min old) is still fresh
        assert (
            len(stale_devices) == 1
        ), f"Should find 1 stale device, found {len(stale_devices)}"
        assert (
            sample_device_data["device_3"]["uid"] in stale_devices
        ), "device_3 should be stale"
        assert (
            sample_device_data["device_2"]["uid"] not in stale_devices
        ), "device_2 should not be stale (only 5 min old)"
        assert (
            sample_device_data["device_1"]["uid"] not in stale_devices
        ), "device_1 should not be stale"

    def test_get_stale_devices_empty_when_all_fresh(
        self, device_manager, sample_device_data
    ):
        """
        Test that get_stale_devices returns empty list when all devices are fresh
        STATUS: WILL FAIL - method doesn't exist
        """
        # Add only fresh device
        device_data = sample_device_data["device_1"]
        device_manager.update_device_state(
            device_data["uid"],
            {
                "timestamp": device_data["timestamp"],
                "lat": device_data["lat"],
                "lon": device_data["lon"],
            },
        )

        # Find devices older than 1 hour
        max_age = timedelta(hours=1)
        stale_devices = device_manager.get_stale_devices(max_age)

        assert (
            len(stale_devices) == 0
        ), "Should find no stale devices when all are fresh"

    def test_multiple_plugins_device_tracking(self, device_manager, sample_device_data):
        """
        Test that DeviceStateManager works with devices from multiple plugins
        STATUS: WILL FAIL - method doesn't exist
        """
        # Add devices from different plugins
        for device_id, device_data in sample_device_data.items():
            device_manager.update_device_state(
                device_data["uid"],
                {
                    "timestamp": device_data["timestamp"],
                    "lat": device_data["lat"],
                    "lon": device_data["lon"],
                    "plugin_source": device_data["plugin_source"],
                },
            )

        assert (
            len(device_manager.device_states) == 3
        ), "Should track devices from multiple plugins"

        # Verify plugin sources are preserved
        deepstate_device = device_manager.device_states[
            sample_device_data["device_1"]["uid"]
        ]
        garmin_device = device_manager.device_states[
            sample_device_data["device_2"]["uid"]
        ]
        spot_device = device_manager.device_states[
            sample_device_data["device_3"]["uid"]
        ]

        assert deepstate_device["plugin_source"] == "deepstate"
        assert garmin_device["plugin_source"] == "garmin"
        assert spot_device["plugin_source"] == "spot"


if __name__ == "__main__":
    # Run tests to verify they all FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])
