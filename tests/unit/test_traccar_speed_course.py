"""
ABOUTME: Unit tests for Traccar speed and course extraction
ABOUTME: Tests that speed and course are added as top-level fields
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from plugins.traccar_plugin import TraccarPlugin


class TestTraccarSpeedCourseExtraction:
    """Test Traccar plugin adds speed and course as top-level fields"""

    @pytest.mark.asyncio
    async def test_speed_course_added_as_top_level_fields(self):
        """Test that speed and course are added as top-level fields"""
        plugin = TraccarPlugin(
            config={
                "server_url": "http://localhost:8082",
                "username": "test",
                "password": "test",
                "timeout": 30,
            }
        )

        # Mock position data from Traccar API
        mock_positions = [
            {
                "id": 1,
                "deviceId": 123,
                "latitude": 46.886493,
                "longitude": 29.207861,
                "speed": 15.5,  # Speed in knots (Traccar default)
                "course": 315.0,
                "altitude": 100.0,
                "accuracy": 5.0,
                "deviceTime": "2025-11-08T10:00:00Z",
                "fixTime": "2025-11-08T10:00:00Z",
                "attributes": {},
            }
        ]

        # Mock device data
        mock_devices = [{"id": 123, "name": "Test Device", "uniqueId": "test-001"}]

        # Mock the API fetch methods
        with patch.object(
            plugin, "_fetch_positions_from_api", new=AsyncMock(return_value=mock_positions)
        ), patch.object(
            plugin, "_fetch_devices_from_api", new=AsyncMock(return_value=mock_devices)
        ):
            mock_session = MagicMock()
            locations = await plugin._fetch_locations_with_session(
                mock_session, plugin.get_decrypted_config()
            )

            assert len(locations) == 1
            location = locations[0]

            # Verify speed and course are TOP-LEVEL fields
            assert "speed" in location
            assert "course" in location
            assert location["speed"] == 15.5
            assert location["course"] == 315.0

            # Verify they are NOT in additional_data
            assert "speed" not in location["additional_data"]
            assert "course" not in location["additional_data"]

    @pytest.mark.asyncio
    async def test_speed_course_not_added_when_none(self):
        """Test that speed/course are not added when None"""
        plugin = TraccarPlugin(
            config={
                "server_url": "http://localhost:8082",
                "username": "test",
                "password": "test",
                "timeout": 30,
            }
        )

        # Mock position data without speed/course
        mock_positions = [
            {
                "id": 1,
                "deviceId": 123,
                "latitude": 46.886493,
                "longitude": 29.207861,
                "speed": None,
                "course": None,
                "altitude": 100.0,
                "deviceTime": "2025-11-08T10:00:00Z",
                "fixTime": "2025-11-08T10:00:00Z",
                "attributes": {},
            }
        ]

        mock_devices = [{"id": 123, "name": "Test Device"}]

        with patch.object(
            plugin, "_fetch_positions_from_api", new=AsyncMock(return_value=mock_positions)
        ), patch.object(
            plugin, "_fetch_devices_from_api", new=AsyncMock(return_value=mock_devices)
        ):
            mock_session = MagicMock()
            locations = await plugin._fetch_locations_with_session(
                mock_session, plugin.get_decrypted_config()
            )

            assert len(locations) == 1
            location = locations[0]

            # Verify speed and course are NOT added when None
            assert "speed" not in location
            assert "course" not in location

    @pytest.mark.asyncio
    async def test_speed_course_zero_values_added(self):
        """Test that zero speed/course values are properly added"""
        plugin = TraccarPlugin(
            config={
                "server_url": "http://localhost:8082",
                "username": "test",
                "password": "test",
                "timeout": 30,
            }
        )

        # Mock position data with zero values
        mock_positions = [
            {
                "id": 1,
                "deviceId": 123,
                "latitude": 46.886493,
                "longitude": 29.207861,
                "speed": 0.0,
                "course": 0.0,
                "altitude": 100.0,
                "deviceTime": "2025-11-08T10:00:00Z",
                "fixTime": "2025-11-08T10:00:00Z",
                "attributes": {},
            }
        ]

        mock_devices = [{"id": 123, "name": "Test Device"}]

        with patch.object(
            plugin, "_fetch_positions_from_api", new=AsyncMock(return_value=mock_positions)
        ), patch.object(
            plugin, "_fetch_devices_from_api", new=AsyncMock(return_value=mock_devices)
        ):
            mock_session = MagicMock()
            locations = await plugin._fetch_locations_with_session(
                mock_session, plugin.get_decrypted_config()
            )

            assert len(locations) == 1
            location = locations[0]

            # Verify zero values are properly added
            assert "speed" in location
            assert "course" in location
            assert location["speed"] == 0.0
            assert location["course"] == 0.0

    @pytest.mark.asyncio
    async def test_multiple_devices_with_different_speed_course(self):
        """Test multiple devices with varying speed/course values"""
        plugin = TraccarPlugin(
            config={
                "server_url": "http://localhost:8082",
                "username": "test",
                "password": "test",
                "timeout": 30,
            }
        )

        # Mock position data for multiple devices
        mock_positions = [
            {
                "id": 1,
                "deviceId": 123,
                "latitude": 46.886493,
                "longitude": 29.207861,
                "speed": 25.5,
                "course": 180.0,
                "altitude": 100.0,
                "deviceTime": "2025-11-08T10:00:00Z",
                "fixTime": "2025-11-08T10:00:00Z",
                "attributes": {},
            },
            {
                "id": 2,
                "deviceId": 456,
                "latitude": 47.0,
                "longitude": 30.0,
                "speed": None,  # No speed data
                "course": 90.0,  # Has course
                "altitude": 50.0,
                "deviceTime": "2025-11-08T10:00:00Z",
                "fixTime": "2025-11-08T10:00:00Z",
                "attributes": {},
            },
        ]

        mock_devices = [
            {"id": 123, "name": "Device 1"},
            {"id": 456, "name": "Device 2"},
        ]

        with patch.object(
            plugin, "_fetch_positions_from_api", new=AsyncMock(return_value=mock_positions)
        ), patch.object(
            plugin, "_fetch_devices_from_api", new=AsyncMock(return_value=mock_devices)
        ):
            mock_session = MagicMock()
            locations = await plugin._fetch_locations_with_session(
                mock_session, plugin.get_decrypted_config()
            )

            assert len(locations) == 2

            # First device has both speed and course
            assert locations[0]["speed"] == 25.5
            assert locations[0]["course"] == 180.0

            # Second device has course but no speed
            assert "speed" not in locations[1]
            assert locations[1]["course"] == 90.0
