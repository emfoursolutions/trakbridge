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


@pytest.mark.callsign
@pytest.mark.integration
class TestPhase5ApiServiceIntegration:
    """Integration tests for Phase 5 API and service workflows - TDD approach"""

    def test_api_to_service_to_database_workflow(self, app, db_session):
        """Test complete API → Service → Database workflow - FAILING TEST FIRST"""
        with app.app_context():
            from services.stream_operations_service import StreamOperationsService
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            from unittest.mock import Mock
            import uuid

            # Arrange: Create test TAK server
            tak_server = TakServer(
                name=f"API Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()
            mock_stream_manager.get_stream_status.return_value = {"running": False}

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Act & Assert: Test full workflow through service

            # 1. Create stream with callsign mappings via service
            create_data = {
                "name": "API Integration Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "fallback",
                "enable_per_callsign_cot_types": True,
                "callsign_mapping_0_identifier": "API001",
                "callsign_mapping_0_callsign": "API-Alpha",
                "callsign_mapping_0_cot_type": "a-f-G-E-V-C",
                "callsign_mapping_1_identifier": "API002",
                "callsign_mapping_1_callsign": "API-Bravo",
                "plugin_username": "api_user",
                "plugin_password": "api_pass",
            }

            result = service.create_stream(create_data)
            assert result["success"] is True
            stream_id = result["stream_id"]

            # Verify stream was created correctly
            stream = Stream.query.get(stream_id)
            assert stream.enable_callsign_mapping is True
            assert stream.callsign_identifier_field == "imei"
            assert stream.enable_per_callsign_cot_types is True

            # Verify callsign mappings were created
            mappings = CallsignMapping.query.filter_by(stream_id=stream_id).all()
            assert len(mappings) == 2

            mapping_dict = {m.identifier_value: m for m in mappings}
            assert "API001" in mapping_dict
            assert mapping_dict["API001"].custom_callsign == "API-Alpha"
            assert mapping_dict["API001"].cot_type == "a-f-G-E-V-C"
            assert "API002" in mapping_dict
            assert mapping_dict["API002"].custom_callsign == "API-Bravo"

            # 2. Update stream via service
            update_data = {
                "name": "Updated API Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "skip",
                "enable_per_callsign_cot_types": False,
                "callsign_mapping_0_identifier": "API003",
                "callsign_mapping_0_callsign": "API-Charlie",
                "callsign_mapping_1_identifier": "API004",
                "callsign_mapping_1_callsign": "API-Delta",
            }

            update_result = service.update_stream_safely(stream_id, update_data)
            assert update_result["success"] is True

            # Verify updates were applied
            updated_stream = Stream.query.get(stream_id)
            assert updated_stream.name == "Updated API Stream"
            assert updated_stream.callsign_error_handling == "skip"
            assert updated_stream.enable_per_callsign_cot_types is False

            # Verify mappings were updated (old ones cleared, new ones added)
            updated_mappings = CallsignMapping.query.filter_by(
                stream_id=stream_id
            ).all()
            assert len(updated_mappings) == 2

            updated_mapping_dict = {m.identifier_value: m for m in updated_mappings}
            assert "API003" in updated_mapping_dict
            assert updated_mapping_dict["API003"].custom_callsign == "API-Charlie"
            assert "API004" in updated_mapping_dict
            assert updated_mapping_dict["API004"].custom_callsign == "API-Delta"

            # Old mappings should be gone
            assert "API001" not in updated_mapping_dict
            assert "API002" not in updated_mapping_dict

    def test_service_error_handling_integration(self, app, db_session):
        """Test service error handling and rollback behavior - FAILING TEST FIRST"""
        with app.app_context():
            from services.stream_operations_service import StreamOperationsService
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            from unittest.mock import Mock
            import uuid

            # Arrange: Create test setup
            tak_server = TakServer(
                name=f"Error Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            mock_stream_manager = Mock()
            mock_stream_manager.get_stream_status.return_value = {"running": False}
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Act & Assert: Test error handling

            # 1. Test create with invalid data
            invalid_create_data = {
                "name": "Error Test Stream",
                "plugin_type": "garmin",
                "tak_server_id": 99999,  # Invalid TAK server ID
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_mapping_0_identifier": "ERROR001",
                "callsign_mapping_0_callsign": "Error-Alpha",
            }

            result = service.create_stream(invalid_create_data)
            assert result["success"] is False
            assert "error" in result

            # Verify no partial data was created
            # Need to rollback and start new transaction after error
            db_session.rollback()
            error_stream = Stream.query.filter_by(name="Error Test Stream").first()
            assert error_stream is None

            # 2. Test update with invalid stream ID
            update_result = service.update_stream_safely(
                99999, {"name": "Invalid Update"}
            )
            assert update_result["success"] is False
            assert "error" in update_result

    def test_callsign_mapping_crud_integration(self, app, db_session):
        """Test CRUD operations integration for callsign mappings - FAILING TEST FIRST"""
        with app.app_context():
            from services.stream_operations_service import StreamOperationsService
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            from unittest.mock import Mock
            import uuid

            # Arrange: Create test stream
            tak_server = TakServer(
                name=f"CRUD Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="CRUD Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            stream.set_plugin_config({"username": "crud", "password": "test"})
            db_session.add(stream)
            db_session.commit()

            mock_stream_manager = Mock()
            mock_stream_manager.get_stream_status.return_value = {"running": False}
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Act & Assert: Test CRUD operations

            # 1. CREATE: Add initial mappings
            create_form_data = {
                "name": "CRUD Test Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_mapping_0_identifier": "CRUD001",
                "callsign_mapping_0_callsign": "CRUD-Alpha",
                "callsign_mapping_1_identifier": "CRUD002",
                "callsign_mapping_1_callsign": "CRUD-Bravo",
            }

            service._create_callsign_mappings(stream, create_form_data)
            db_session.commit()

            # Verify CREATE
            initial_mappings = CallsignMapping.query.filter_by(
                stream_id=stream.id
            ).all()
            assert len(initial_mappings) == 2

            # 2. UPDATE: Modify mappings
            update_form_data = {
                "callsign_mapping_0_identifier": "CRUD003",
                "callsign_mapping_0_callsign": "CRUD-Charlie",
                "callsign_mapping_1_identifier": "CRUD004",
                "callsign_mapping_1_callsign": "CRUD-Delta",
                "callsign_mapping_2_identifier": "CRUD005",
                "callsign_mapping_2_callsign": "CRUD-Echo",
            }

            service._update_callsign_mappings(stream, update_form_data)
            db_session.commit()

            # Verify UPDATE (should replace all mappings)
            updated_mappings = CallsignMapping.query.filter_by(
                stream_id=stream.id
            ).all()
            assert len(updated_mappings) == 3

            updated_identifiers = [m.identifier_value for m in updated_mappings]
            assert "CRUD003" in updated_identifiers
            assert "CRUD004" in updated_identifiers
            assert "CRUD005" in updated_identifiers

            # Old identifiers should be gone
            assert "CRUD001" not in updated_identifiers
            assert "CRUD002" not in updated_identifiers

            # 3. DELETE: Remove all mappings by updating with empty data
            empty_form_data = {}
            service._update_callsign_mappings(stream, empty_form_data)
            db_session.commit()

            # Verify DELETE
            final_mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(final_mappings) == 0

    def test_cross_stream_isolation_integration(self, app, db_session):
        """Test that callsign mappings are properly isolated between streams - FAILING TEST FIRST"""
        with app.app_context():
            from services.stream_operations_service import StreamOperationsService
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            from unittest.mock import Mock
            import uuid

            # Arrange: Create two separate streams
            tak_server = TakServer(
                name=f"Isolation Test Server {uuid.uuid4()}",
                host="localhost",
                port=8087,
            )
            db_session.add(tak_server)
            db_session.commit()

            stream1 = Stream(
                name="Isolation Stream 1",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            stream1.set_plugin_config({"username": "stream1", "password": "test"})

            stream2 = Stream(
                name="Isolation Stream 2",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            stream2.set_plugin_config({"username": "stream2", "password": "test"})

            db_session.add_all([stream1, stream2])
            db_session.commit()

            mock_stream_manager = Mock()
            mock_stream_manager.get_stream_status.return_value = {"running": False}
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Act: Add mappings to both streams with same identifiers

            # Stream 1 mappings
            stream1_data = {
                "callsign_mapping_0_identifier": "SHARED001",
                "callsign_mapping_0_callsign": "Stream1-Alpha",
                "callsign_mapping_1_identifier": "SHARED002",
                "callsign_mapping_1_callsign": "Stream1-Bravo",
            }
            service._create_callsign_mappings(stream1, stream1_data)

            # Stream 2 mappings (same identifiers, different callsigns)
            stream2_data = {
                "callsign_mapping_0_identifier": "SHARED001",
                "callsign_mapping_0_callsign": "Stream2-Charlie",
                "callsign_mapping_1_identifier": "SHARED002",
                "callsign_mapping_1_callsign": "Stream2-Delta",
            }
            service._create_callsign_mappings(stream2, stream2_data)

            db_session.commit()

            # Assert: Verify isolation
            stream1_mappings = CallsignMapping.query.filter_by(
                stream_id=stream1.id
            ).all()
            stream2_mappings = CallsignMapping.query.filter_by(
                stream_id=stream2.id
            ).all()

            # Both streams should have their own mappings
            assert len(stream1_mappings) == 2
            assert len(stream2_mappings) == 2

            # Same identifiers should map to different callsigns per stream
            stream1_dict = {
                m.identifier_value: m.custom_callsign for m in stream1_mappings
            }
            stream2_dict = {
                m.identifier_value: m.custom_callsign for m in stream2_mappings
            }

            assert stream1_dict["SHARED001"] == "Stream1-Alpha"
            assert stream2_dict["SHARED001"] == "Stream2-Charlie"
            assert stream1_dict["SHARED002"] == "Stream1-Bravo"
            assert stream2_dict["SHARED002"] == "Stream2-Delta"

            # Deleting one stream's mappings should not affect the other
            service._update_callsign_mappings(stream1, {})  # Clear stream1 mappings
            db_session.commit()

            # Stream1 should have no mappings, Stream2 should be unchanged
            stream1_final = CallsignMapping.query.filter_by(stream_id=stream1.id).all()
            stream2_final = CallsignMapping.query.filter_by(stream_id=stream2.id).all()

            assert len(stream1_final) == 0
            assert len(stream2_final) == 2  # Unchanged
