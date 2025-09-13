"""
ABOUTME: Test Phase 5 disabled tracker filtering functionality in stream processing
ABOUTME: Verifies that disabled trackers are filtered out from CoT generation pipeline

This test module verifies Phase 5 implementation where disabled trackers
are filtered out during stream processing to prevent them from being sent
to TAK servers while preserving their database configuration.

Author: TrakBridge Implementation Team
Created: 2025-01-12 (Phase 5 Implementation)
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock

from models.callsign_mapping import CallsignMapping
from models.stream import Stream
from services.stream_worker import StreamWorker


class TestDisabledTrackerFiltering:
    """Test that disabled trackers are filtered from CoT processing pipeline"""

    @pytest.fixture
    def mock_db_manager(self):
        """Create mock database manager"""
        return Mock()

    @pytest.fixture
    def mock_session_manager(self):
        """Create mock session manager"""
        return Mock()

    @pytest.fixture
    def test_stream(self):
        """Create test stream with callsign mapping enabled"""
        stream = Mock(spec=Stream)
        stream.id = 1
        stream.name = "Test Stream"
        stream.enable_callsign_mapping = True
        stream.callsign_identifier_field = "imei"
        stream.callsign_error_handling = "fallback"
        return stream

    @pytest.fixture
    def stream_worker(self, test_stream, mock_session_manager, mock_db_manager):
        """Create StreamWorker instance for testing"""
        return StreamWorker(test_stream, mock_session_manager, mock_db_manager)

    def test_filter_disabled_trackers_removes_disabled_locations(
        self, app, db_session, stream_worker
    ):
        """Test that _filter_disabled_trackers removes disabled tracker locations"""
        with app.app_context():
            # Create test stream in database
            stream = Stream(
                name="Filter Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei"
            )
            db_session.add(stream)
            db_session.commit()

            # Create disabled mappings
            disabled_mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED001",
                custom_callsign="Disabled-Alpha",
                enabled=False
            )
            disabled_mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED002", 
                custom_callsign="Disabled-Bravo",
                enabled=False
            )
            enabled_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ENABLED001",
                custom_callsign="Enabled-Charlie",
                enabled=True
            )
            
            db_session.add_all([disabled_mapping1, disabled_mapping2, enabled_mapping])
            db_session.commit()

            # Update worker's stream reference
            stream_worker.stream = stream

            # Test locations with mix of enabled/disabled trackers
            test_locations = [
                {
                    "name": "Device 1",
                    "lat": 40.0,
                    "lon": -120.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "DISABLED001"}}
                    },
                },
                {
                    "name": "Device 2", 
                    "lat": 41.0,
                    "lon": -121.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "ENABLED001"}}
                    },
                },
                {
                    "name": "Device 3",
                    "lat": 42.0,
                    "lon": -122.0, 
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "DISABLED002"}}
                    },
                },
                {
                    "name": "Device 4",
                    "lat": 43.0,
                    "lon": -123.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "UNMAPPED001"}}
                    },
                },
            ]

            # Create disabled mappings dict for filtering
            disabled_mappings = {
                "DISABLED001": disabled_mapping1,
                "DISABLED002": disabled_mapping2
            }
            
            fresh_stream_config = {
                "callsign_identifier_field": "imei"
            }

            # Run the filtering
            async def test_filtering():
                await stream_worker._filter_disabled_trackers(
                    test_locations, disabled_mappings, fresh_stream_config
                )

            asyncio.run(test_filtering())

            # Verify disabled trackers were removed
            assert len(test_locations) == 2  # Only enabled and unmapped should remain
            
            remaining_names = [loc["name"] for loc in test_locations]
            assert "Device 2" in remaining_names  # Enabled tracker
            assert "Device 4" in remaining_names  # Unmapped tracker (not filtered)
            assert "Device 1" not in remaining_names  # Disabled tracker removed
            assert "Device 3" not in remaining_names  # Disabled tracker removed

    def test_filter_disabled_trackers_handles_empty_disabled_mappings(
        self, stream_worker
    ):
        """Test that filtering works when no disabled mappings exist"""
        test_locations = [
            {
                "name": "Device 1",
                "lat": 40.0,
                "lon": -120.0,
                "additional_data": {
                    "raw_placemark": {"extended_data": {"IMEI": "TEST001"}}
                },
            }
        ]

        disabled_mappings = {}  # No disabled mappings
        fresh_stream_config = {"callsign_identifier_field": "imei"}

        async def test_filtering():
            await stream_worker._filter_disabled_trackers(
                test_locations, disabled_mappings, fresh_stream_config
            )

        asyncio.run(test_filtering())

        # No locations should be removed
        assert len(test_locations) == 1
        assert test_locations[0]["name"] == "Device 1"

    def test_filter_disabled_trackers_handles_no_identifier_field(
        self, stream_worker
    ):
        """Test that filtering is skipped when no identifier field is configured"""
        test_locations = [
            {
                "name": "Device 1",
                "lat": 40.0,
                "lon": -120.0,
                "additional_data": {
                    "raw_placemark": {"extended_data": {"IMEI": "DISABLED001"}}
                },
            }
        ]

        disabled_mappings = {"DISABLED001": Mock()}
        fresh_stream_config = {}  # No identifier field

        async def test_filtering():
            await stream_worker._filter_disabled_trackers(
                test_locations, disabled_mappings, fresh_stream_config
            )

        asyncio.run(test_filtering())

        # No locations should be removed without identifier field
        assert len(test_locations) == 1
        assert test_locations[0]["name"] == "Device 1"

    def test_load_disabled_callsign_mappings_returns_only_disabled(
        self, app, db_session, stream_worker
    ):
        """Test that _load_disabled_callsign_mappings only returns disabled mappings"""
        with app.app_context():
            # Create test stream in database
            stream = Stream(
                name="Disabled Load Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True
            )
            db_session.add(stream)
            db_session.commit()

            # Create mix of enabled and disabled mappings
            enabled_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ENABLED001",
                custom_callsign="Enabled-Test",
                enabled=True
            )
            disabled_mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED001", 
                custom_callsign="Disabled-Test-1",
                enabled=False
            )
            disabled_mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED002",
                custom_callsign="Disabled-Test-2", 
                enabled=False
            )
            
            db_session.add_all([enabled_mapping, disabled_mapping1, disabled_mapping2])
            db_session.commit()

            # Update worker's stream reference
            stream_worker.stream = stream

            # Load disabled mappings
            async def test_loading():
                return await stream_worker._load_disabled_callsign_mappings()

            disabled_mappings = asyncio.run(test_loading())

            # Verify only disabled mappings are returned
            assert len(disabled_mappings) == 2
            assert "DISABLED001" in disabled_mappings
            assert "DISABLED002" in disabled_mappings
            assert "ENABLED001" not in disabled_mappings

            # Verify the disabled mappings have correct data
            assert disabled_mappings["DISABLED001"].custom_callsign == "Disabled-Test-1"
            assert disabled_mappings["DISABLED002"].custom_callsign == "Disabled-Test-2"
            assert disabled_mappings["DISABLED001"].enabled is False
            assert disabled_mappings["DISABLED002"].enabled is False

    def test_load_callsign_mappings_returns_only_enabled(
        self, app, db_session, stream_worker
    ):
        """Test that _load_callsign_mappings only returns enabled mappings"""
        with app.app_context():
            # Create test stream in database
            stream = Stream(
                name="Enabled Load Test Stream", 
                plugin_type="garmin",
                enable_callsign_mapping=True
            )
            db_session.add(stream)
            db_session.commit()

            # Create mix of enabled and disabled mappings
            enabled_mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ENABLED001",
                custom_callsign="Enabled-Test-1",
                enabled=True
            )
            enabled_mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ENABLED002",
                custom_callsign="Enabled-Test-2", 
                enabled=True
            )
            disabled_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED001",
                custom_callsign="Disabled-Test",
                enabled=False
            )
            
            db_session.add_all([enabled_mapping1, enabled_mapping2, disabled_mapping])
            db_session.commit()

            # Update worker's stream reference
            stream_worker.stream = stream

            # Load enabled mappings
            async def test_loading():
                return await stream_worker._load_callsign_mappings()

            enabled_mappings = asyncio.run(test_loading())

            # Verify only enabled mappings are returned
            assert len(enabled_mappings) == 2
            assert "ENABLED001" in enabled_mappings
            assert "ENABLED002" in enabled_mappings
            assert "DISABLED001" not in enabled_mappings

            # Verify the enabled mappings have correct data
            assert enabled_mappings["ENABLED001"].custom_callsign == "Enabled-Test-1"
            assert enabled_mappings["ENABLED002"].custom_callsign == "Enabled-Test-2"
            assert enabled_mappings["ENABLED001"].enabled is True
            assert enabled_mappings["ENABLED002"].enabled is True

    def test_apply_callsign_mapping_filters_disabled_trackers(
        self, app, db_session, stream_worker
    ):
        """Test that _apply_callsign_mapping calls filtering for disabled trackers"""
        with app.app_context():
            # Create test stream in database
            stream = Stream(
                name="Apply Mapping Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback"
            )
            db_session.add(stream)
            db_session.commit()

            # Create enabled and disabled mappings
            enabled_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ENABLED001",
                custom_callsign="Enabled-Alpha",
                enabled=True
            )
            disabled_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DISABLED001", 
                custom_callsign="Disabled-Bravo",
                enabled=False
            )
            
            db_session.add_all([enabled_mapping, disabled_mapping])
            db_session.commit()

            # Update worker's stream reference
            stream_worker.stream = stream

            # Test locations with enabled and disabled trackers
            test_locations = [
                {
                    "name": "Enabled Device",
                    "lat": 40.0,
                    "lon": -120.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "ENABLED001"}}
                    },
                },
                {
                    "name": "Disabled Device",
                    "lat": 41.0,
                    "lon": -121.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "DISABLED001"}}
                    },
                },
                {
                    "name": "Unmapped Device",
                    "lat": 42.0,
                    "lon": -122.0,
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "UNMAPPED001"}}
                    },
                },
            ]

            # Apply callsign mapping (which includes filtering)
            async def test_mapping():
                await stream_worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_mapping())

            # Verify results
            assert len(test_locations) == 2  # Only enabled and unmapped should remain
            
            location_names = [loc["name"] for loc in test_locations]
            assert "Enabled-Alpha" in location_names  # Enabled tracker with mapping applied
            assert "Unmapped Device" in location_names  # Unmapped tracker (fallback)
            assert "Disabled Device" not in location_names  # Disabled tracker removed

    def test_extract_identifier_handles_various_field_types(self, stream_worker):
        """Test that _extract_identifier works with different identifier field types"""
        # Test different location data structures for various plugins
        test_cases = [
            # Garmin IMEI extraction
            (
                {
                    "name": "Garmin Device",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "GARMIN123"}}
                    },
                },
                "imei",
                "GARMIN123"
            ),
            # SPOT messenger name extraction
            (
                {
                    "name": "SPOT Device",
                    "additional_data": {
                        "raw_message": {"messengerName": "SPOT456"}
                    },
                },
                "messenger_name",
                "SPOT456"
            ),
            # Traccar device ID extraction
            (
                {
                    "name": "Traccar Device",
                    "additional_data": {"device_id": "TRACCAR789"}
                },
                "device_id", 
                "TRACCAR789"
            ),
            # Direct name field extraction
            (
                {
                    "name": "Direct Name",
                    "lat": 40.0,
                    "lon": -120.0
                },
                "name",
                "Direct Name"
            ),
            # UID field extraction
            (
                {
                    "name": "UID Device",
                    "uid": "UID123",
                    "lat": 40.0,
                    "lon": -120.0
                },
                "uid",
                "UID123"
            ),
            # Generic field extraction
            (
                {
                    "name": "Generic Device",
                    "custom_field": "GENERIC456"
                },
                "custom_field",
                "GENERIC456"
            ),
            # Missing field returns None
            (
                {
                    "name": "Missing Field Device"
                },
                "nonexistent_field",
                None
            ),
        ]

        for location, field_name, expected_result in test_cases:
            result = stream_worker._extract_identifier(location, field_name)
            assert result == expected_result, f"Failed for field '{field_name}': expected '{expected_result}', got '{result}'"


class TestFilteringPerformance:
    """Test performance aspects of disabled tracker filtering"""

    @pytest.fixture
    def stream_worker(self):
        """Create StreamWorker instance for performance testing"""
        test_stream = Mock()
        test_stream.id = 1
        test_stream.name = "Performance Test Stream"
        mock_session_manager = Mock()
        mock_db_manager = Mock()
        return StreamWorker(test_stream, mock_session_manager, mock_db_manager)

    def test_filtering_performance_with_large_datasets(self, stream_worker):
        """Test that filtering performs well with large numbers of locations and mappings"""
        # Create large dataset
        num_locations = 1000
        num_disabled = 200

        test_locations = []
        for i in range(num_locations):
            test_locations.append({
                "name": f"Device {i}",
                "lat": 40.0 + (i * 0.001),
                "lon": -120.0 + (i * 0.001),
                "additional_data": {
                    "raw_placemark": {"extended_data": {"IMEI": f"IMEI{i:04d}"}}
                },
            })

        # Create disabled mappings for first 200 locations
        disabled_mappings = {}
        for i in range(num_disabled):
            disabled_mapping = Mock()
            disabled_mapping.identifier_value = f"IMEI{i:04d}"
            disabled_mapping.enabled = False
            disabled_mappings[f"IMEI{i:04d}"] = disabled_mapping

        fresh_stream_config = {"callsign_identifier_field": "imei"}

        # Measure performance
        import time

        async def test_performance():
            start_time = time.time()
            await stream_worker._filter_disabled_trackers(
                test_locations, disabled_mappings, fresh_stream_config
            )
            end_time = time.time()
            return end_time - start_time

        import asyncio
        duration = asyncio.run(test_performance())

        # Verify results
        assert len(test_locations) == (num_locations - num_disabled)
        
        # Performance should be reasonable (less than 1 second for 1000 locations)
        assert duration < 1.0, f"Filtering took too long: {duration:.3f} seconds"

        # Verify correct locations were removed
        remaining_imeis = []
        for location in test_locations:
            imei = location["additional_data"]["raw_placemark"]["extended_data"]["IMEI"]
            remaining_imeis.append(imei)

        # First 200 (disabled) should be gone, rest should remain
        for i in range(num_disabled):
            assert f"IMEI{i:04d}" not in remaining_imeis
        
        for i in range(num_disabled, num_locations):
            assert f"IMEI{i:04d}" in remaining_imeis