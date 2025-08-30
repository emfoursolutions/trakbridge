"""Integration tests for callsign mapping functionality."""

import pytest
from unittest.mock import Mock

from models.stream import Stream
from models.callsign_mapping import CallsignMapping
from services.stream_worker import StreamWorker


@pytest.mark.integration
@pytest.mark.callsign
class TestCallsignMappingIntegration:
    """Integration tests for end-to-end callsign functionality"""

    def test_full_callsign_workflow(self, app, db_session):
        """Test complete callsign mapping workflow from database to plugin to stream worker"""
        with app.app_context():
            # 1. Create stream with callsign mapping enabled
            stream = Stream(
                name="Integration Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback",
                enable_per_callsign_cot_types=True,
                cot_type="a-f-G-U-C",
            )
            db_session.add(stream)
            db_session.commit()

            # 2. Create multiple callsign mappings
            mappings = [
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="123456789",
                    custom_callsign="Alpha-1",
                    cot_type="a-f-G-E-V-C",
                ),
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="987654321",
                    custom_callsign="Bravo-2",
                    cot_type="a-f-G-U-H",
                ),
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="555666777",
                    custom_callsign="Charlie-3",
                    # No custom CoT type - should use stream default
                ),
            ]
            for mapping in mappings:
                db_session.add(mapping)
            db_session.commit()

            # 3. Create stream worker with mock dependencies
            mock_db_manager = Mock()
            mock_session_manager = Mock()
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # 4. Create realistic location data with different scenarios
            test_locations = [
                {
                    "name": "Original Device 1",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                    },
                },
                {
                    "name": "Original Device 2",
                    "lat": 41.0,
                    "lon": -121.0,
                    "uid": "test-456",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "987654321"}}
                    },
                },
                {
                    "name": "Original Device 3",
                    "lat": 42.0,
                    "lon": -122.0,
                    "uid": "test-789",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "555666777"}}
                    },
                },
                {
                    "name": "Unmapped Device",
                    "lat": 43.0,
                    "lon": -123.0,
                    "uid": "test-999",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "999888777"}}
                    },
                },
            ]

            # 5. Apply callsign mapping through stream worker
            import asyncio

            async def test_integration():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_integration())

            # 6. Verify results
            # First device: custom callsign + custom CoT type
            assert test_locations[0]["name"] == "Alpha-1"
            assert test_locations[0]["cot_type"] == "a-f-G-E-V-C"

            # Second device: custom callsign + custom CoT type
            assert test_locations[1]["name"] == "Bravo-2"
            assert test_locations[1]["cot_type"] == "a-f-G-U-H"

            # Third device: custom callsign + stream default CoT type
            assert test_locations[2]["name"] == "Charlie-3"
            # Should not have custom CoT type set since enable_per_callsign_cot_types is true
            # but this mapping has no cot_type
            assert "cot_type" not in test_locations[2]

            # Fourth device: fallback behavior (keep original name)
            assert test_locations[3]["name"] == "Unmapped Device"
            assert "cot_type" not in test_locations[3]

    def test_plugin_interface_integration(self, app, db_session):
        """Test integration with actual plugin CallsignMappable interface"""
        with app.app_context():
            from plugins.garmin_plugin import GarminPlugin

            # Create stream and mapping
            stream = Stream(
                name="Plugin Integration Test",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            db_session.add(stream)
            db_session.commit()

            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="PLUGIN123",
                custom_callsign="PluginTest-1",
            )
            db_session.add(mapping)
            db_session.commit()

            # Create stream worker with real Garmin plugin
            mock_db_manager = Mock()
            mock_session_manager = Mock()
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Initialize plugin
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test",
            }
            worker.plugin = GarminPlugin(plugin_config)

            # Test location data
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "PLUGIN123"}}
                    },
                }
            ]

            # Apply callsign mapping through plugin interface
            import asyncio

            async def test_plugin():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_plugin())

            # Verify plugin applied the mapping
            assert test_locations[0]["name"] == "PluginTest-1"

    def test_error_handling_modes(self, app, db_session):
        """Test different error handling modes (fallback vs skip)"""
        with app.app_context():
            # Test fallback mode
            fallback_stream = Stream(
                name="Fallback Test",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback",
            )
            db_session.add(fallback_stream)
            db_session.commit()

            # Test skip mode
            skip_stream = Stream(
                name="Skip Test",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="skip",
            )
            db_session.add(skip_stream)
            db_session.commit()

            # No callsign mappings created - all will be unmapped

            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Test fallback mode
            fallback_worker = StreamWorker(
                fallback_stream, mock_session_manager, mock_db_manager
            )
            fallback_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "UNMAPPED123"}}
                    },
                }
            ]

            # Test skip mode
            skip_worker = StreamWorker(
                skip_stream, mock_session_manager, mock_db_manager
            )
            skip_locations = [
                {
                    "name": "Device 1",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "UNMAPPED456"}}
                    },
                },
                {
                    "name": "Device 2",
                    "lat": 41.0,
                    "lon": -121.0,
                    "uid": "test-456",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "UNMAPPED789"}}
                    },
                },
            ]

            import asyncio

            # Test fallback mode
            async def test_fallback():
                await fallback_worker._apply_callsign_mapping(fallback_locations)

            # Test skip mode
            async def test_skip():
                await skip_worker._apply_callsign_mapping(skip_locations)

            asyncio.run(test_fallback())
            asyncio.run(test_skip())

            # Fallback mode: should keep original names
            assert len(fallback_locations) == 1
            assert fallback_locations[0]["name"] == "Original Name"

            # Skip mode: should remove unmapped locations
            assert len(skip_locations) == 0  # All locations should be skipped

    def test_database_schema_constraints(self, app, db_session):
        """Test database schema constraints and relationships"""
        with app.app_context():
            # Create test stream
            stream = Stream(name="Constraint Test", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()

            # Test successful creation
            mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="UNIQUE123",
                custom_callsign="Test-1",
            )
            db_session.add(mapping1)
            db_session.commit()

            # Test unique constraint violation
            mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="UNIQUE123",  # Same identifier
                custom_callsign="Test-2",
            )
            db_session.add(mapping2)

            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                db_session.commit()

            db_session.rollback()

            # Test cascade deletion
            mapping_id = mapping1.id
            db_session.delete(stream)
            db_session.commit()

            # Verify mapping was deleted
            deleted_mapping = db_session.get(CallsignMapping, mapping_id)
            assert deleted_mapping is None
