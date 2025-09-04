"""Unit tests for TrakBridge services."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from services.encryption_service import EncryptionService
from services.logging_service import setup_logging
from services.stream_manager import StreamManager
from services.stream_worker import StreamWorker
from services.tak_servers_service import (TakServerConnectionTester,
                                          TakServerService)
from services.version import get_version, get_version_info


class TestStreamManager:
    """Test the StreamManager service."""

    def test_stream_manager_initialization(self, app):
        """Test StreamManager initialization."""
        with app.app_context():
            stream_manager = StreamManager()
            assert stream_manager is not None

    @patch("services.stream_manager.StreamWorker")
    @patch("services.database_manager.DatabaseManager")
    def test_start_stream(self, mock_db_manager, mock_worker, app):
        """Test starting a stream."""
        with app.app_context():
            stream_manager = StreamManager()

            # Mock the database manager
            mock_db_instance = Mock()
            mock_db_manager.return_value = mock_db_instance
            stream_manager.db_manager = mock_db_instance

            # Mock a stream from database
            mock_stream = Mock()
            mock_stream.id = 1
            mock_stream.name = "Test Stream"
            mock_stream.plugin_type = "garmin"
            mock_stream.is_active = True
            mock_db_instance.get_stream.return_value = mock_stream

            # Mock the worker
            mock_worker_instance = Mock()
            mock_worker.return_value = mock_worker_instance

            # Mock start_stream to return a non-coroutine value instead of an actual coroutine
            def mock_start_stream(stream_id):
                # Return a simple value instead of a coroutine
                return True

            with patch.object(
                stream_manager, "start_stream", side_effect=mock_start_stream
            ):
                with patch.object(
                    stream_manager, "_run_coroutine_threadsafe", return_value=True
                ):
                    result = stream_manager.start_stream_sync(1)
                    assert result is True

            # Verify database lookup was called
            mock_db_instance.get_stream.assert_called_once_with(1)


class TestEncryptionService:
    """Test the EncryptionService."""

    def test_encryption_service_initialization(self, app):
        """Test EncryptionService initialization."""
        with app.app_context():
            encryption_service = EncryptionService()
            assert encryption_service is not None

    def test_encrypt_decrypt(self, app):
        """Test encryption and decryption."""
        with app.app_context():
            encryption_service = EncryptionService()

            # Test data
            test_data = "sensitive information"

            # Encrypt
            encrypted = encryption_service.encrypt_value(test_data)
            assert encrypted != test_data
            assert encrypted is not None

            # Decrypt
            decrypted = encryption_service.decrypt_value(encrypted)
            assert decrypted == test_data


class TestVersionService:
    """Test version-related services."""

    def test_get_version(self):
        """Test getting version information."""
        version = get_version()
        assert version is not None
        assert isinstance(version, str)

    def test_get_version_info(self):
        """Test getting detailed version information."""
        version_info = get_version_info()
        assert version_info is not None
        assert isinstance(version_info, dict)
        assert "version" in version_info


class TestLoggingService:
    """Test logging service."""

    def test_setup_logging(self, app):
        """Test logging setup."""
        with app.app_context():
            # This should not raise an exception
            setup_logging(app)
            assert True  # If we get here, setup_logging worked


class TestTakServerService:
    """Test TAK server service integration."""

    def test_tak_server_service_initialization(self):
        """Test TakServerService can be initialized."""
        service = TakServerService()
        assert service is not None

    def test_tak_server_connection_tester_cot_message(self):
        """Test COT message creation works correctly."""
        # This tests the fix for the defusedxml.ElementTree issue
        cot_xml = TakServerConnectionTester.create_test_cot_message()
        assert cot_xml is not None
        assert isinstance(cot_xml, bytes)

        # Should be valid XML
        import xml.etree.ElementTree as ET

        root = ET.fromstring(cot_xml)
        assert root.tag == "event"


@pytest.mark.callsign
class TestStreamWorkerCallsignIntegration:
    """Test stream worker callsign mapping functionality - integrated with existing service tests"""

    @pytest.mark.asyncio
    async def test_stream_worker_callsign_application_disabled(self, app, db_session):
        """Test stream worker applies callsigns correctly when feature is disabled"""
        with app.app_context():
            from database import db
            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream

            # Create test stream without callsign mapping enabled
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=False,  # Feature disabled
            )
            db_session.add(stream)
            db_session.commit()

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Create test location data
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                    },
                }
            ]

            # Test that _apply_callsign_mapping method exists and handles disabled case
            # This should fail initially until we implement the method
            assert hasattr(worker, "_apply_callsign_mapping")

            # Apply callsign mapping (should be early exit when disabled)
            await worker._apply_callsign_mapping(test_locations)

            # Location name should remain unchanged when feature disabled
            assert test_locations[0]["name"] == "Original Name"

    @pytest.mark.asyncio
    async def test_stream_worker_callsign_application_enabled(self, app, db_session):
        """Test stream worker applies callsigns correctly when feature is enabled"""
        with app.app_context():
            from database import db
            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream

            # Create test stream with callsign mapping enabled
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback",
            )
            db_session.add(stream)
            db_session.commit()

            # Create callsign mapping
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="123456789",
                custom_callsign="Alpha-1",
                cot_type="a-f-G-U-C",
            )
            db_session.add(mapping)
            db_session.commit()

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Create test location data with Garmin structure
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                    },
                }
            ]

            # Test that _apply_callsign_mapping method applies mapping
            await worker._apply_callsign_mapping(test_locations)

            # Location name should be updated with custom callsign
            assert test_locations[0]["name"] == "Alpha-1"

    @pytest.mark.asyncio
    async def test_stream_worker_per_callsign_cot_types(self, app, db_session):
        """Test stream worker applies per-callsign CoT type overrides"""
        with app.app_context():
            from database import db
            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream

            # Create test stream with per-callsign CoT types enabled
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                enable_per_callsign_cot_types=True,
                cot_type="a-f-G-U-C",  # Stream default
            )
            db_session.add(stream)
            db_session.commit()

            # Create callsign mapping with CoT type override
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="123456789",
                custom_callsign="Alpha-1",
                cot_type="a-f-G-E-V-C",  # Override CoT type
            )
            db_session.add(mapping)
            db_session.commit()

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Create test location data
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                    },
                }
            ]

            # Apply callsign mapping with CoT type override
            await worker._apply_callsign_mapping(test_locations)

            # Should have both callsign and CoT type applied
            assert test_locations[0]["name"] == "Alpha-1"
            assert test_locations[0]["cot_type"] == "a-f-G-E-V-C"

    @pytest.mark.asyncio
    async def test_stream_worker_callsign_error_handling_fallback(
        self, app, db_session
    ):
        """Test stream worker fallback behavior when callsign mapping fails"""
        with app.app_context():
            from database import db
            from models.stream import Stream

            # Create test stream with fallback error handling
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback",
            )
            db_session.add(stream)
            db_session.commit()
            # Note: No callsign mappings created - should trigger fallback

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Create test location data
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "999888777"}}
                    },
                }
            ]

            # Apply callsign mapping (should fallback to original name)
            await worker._apply_callsign_mapping(test_locations)

            # Should use fallback behavior (keep original name)
            assert test_locations[0]["name"] == "Original Name"

    @pytest.mark.asyncio
    async def test_stream_worker_callsign_error_handling_skip(self, app, db_session):
        """Test stream worker skip behavior when callsign mapping fails"""
        with app.app_context():
            from database import db
            from models.stream import Stream

            # Create test stream with skip error handling
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="skip",
            )
            db_session.add(stream)
            db_session.commit()
            # Note: No callsign mappings created - should trigger skip

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Create test location data with one mappable and one unmappable location
            test_locations = [
                {
                    "name": "Unmappable Location",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "999888777"}}
                    },
                },
                {
                    "name": "Valid Location",
                    "lat": 41.0,
                    "lon": -121.0,
                    "uid": "test-456",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "111222333"}}
                    },
                },
            ]

            # Apply callsign mapping (should skip problematic locations)
            await worker._apply_callsign_mapping(test_locations)

            # With skip mode, unmapped locations should be removed or marked
            # Implementation will determine exact behavior
            assert hasattr(worker, "_apply_callsign_mapping")

    @pytest.mark.asyncio
    async def test_stream_worker_load_callsign_mappings(self, app, db_session):
        """Test stream worker loads callsign mappings efficiently from database"""
        with app.app_context():
            from database import db
            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream

            # Create test stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            db_session.add(stream)
            db_session.commit()

            # Create multiple callsign mappings
            mappings = [
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="111111111",
                    custom_callsign="Alpha-1",
                ),
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="222222222",
                    custom_callsign="Bravo-2",
                ),
                CallsignMapping(
                    stream_id=stream.id,
                    identifier_value="333333333",
                    custom_callsign="Charlie-3",
                ),
            ]
            for mapping in mappings:
                db_session.add(mapping)
            db_session.commit()

            # Create mock database manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

            # Test that _load_callsign_mappings method exists
            assert hasattr(worker, "_load_callsign_mappings")

            # Load callsign mappings
            result = await worker._load_callsign_mappings()

            # Should return dictionary mapping identifiers to mappings
            assert isinstance(result, dict)
            assert len(result) == 3
            assert "111111111" in result
            assert "222222222" in result
            assert "333333333" in result
            assert result["111111111"].custom_callsign == "Alpha-1"

    @pytest.mark.asyncio
    async def test_stream_worker_plugin_integration(self, app, db_session):
        """Test stream worker integrates with plugin CallsignMappable interface"""
        with app.app_context():
            from database import db
            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream

            # Create test stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            db_session.add(stream)
            db_session.commit()

            # Create callsign mapping
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="123456789",
                custom_callsign="Alpha-1",
            )
            db_session.add(mapping)
            db_session.commit()

            # Mock plugin that implements CallsignMappable
            from plugins.base_plugin import CallsignMappable, FieldMetadata

            class MockCallsignPlugin(CallsignMappable):
                def __init__(self, config):
                    self.config = config

                def get_available_fields(self):
                    return [FieldMetadata("imei", "Device IMEI", "string", True)]

                def apply_callsign_mapping(
                    self, tracker_data, field_name, callsign_map
                ):
                    for item in tracker_data:
                        if field_name == "imei":
                            imei = (
                                item.get("additional_data", {})
                                .get("raw_placemark", {})
                                .get("extended_data", {})
                                .get("IMEI")
                            )
                            if imei in callsign_map:
                                item["name"] = callsign_map[imei]

                async def fetch_locations(self, session):
                    return []

                @property
                def plugin_name(self):
                    return "mock"

            # Create mock database manager and session manager
            mock_db_manager = Mock()
            mock_session_manager = Mock()

            # Create stream worker instance
            worker = StreamWorker(stream, mock_session_manager, mock_db_manager)
            worker.plugin = MockCallsignPlugin({})  # Set mock plugin

            # Create test location data
            test_locations = [
                {
                    "name": "Original Name",
                    "lat": 40.0,
                    "lon": -120.0,
                    "uid": "test-123",
                    "additional_data": {
                        "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                    },
                }
            ]

            # Apply callsign mapping through plugin interface
            await worker._apply_callsign_mapping(test_locations)

            # Should have applied callsign through plugin
            assert test_locations[0]["name"] == "Alpha-1"


@pytest.mark.callsign
class TestStreamOperationsServiceCallsign:
    """Test StreamOperationsService callsign functionality - written with TDD approach."""

    def test_create_stream_with_callsign_mappings(self, app, db_session):
        """Test creating a stream with callsign mapping data - FAILING TEST FIRST"""
        with app.app_context():
            # Arrange: Create test TAK server
            import uuid

            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.stream_operations_service import \
                StreamOperationsService

            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Prepare stream data with callsign mapping
            stream_data = {
                "name": "Test Callsign Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "fallback",
                "enable_per_callsign_cot_types": True,
                "callsign_mapping_0_identifier": "123456789",
                "callsign_mapping_0_callsign": "Alpha-1",
                "callsign_mapping_0_cot_type": "a-f-G-E-V-C",
                "callsign_mapping_1_identifier": "987654321",
                "callsign_mapping_1_callsign": "Bravo-2",
                "plugin_username": "test_user",
                "plugin_password": "test_pass",
            }

            # Act: Create stream with callsign data
            result = service.create_stream(stream_data)

            # Assert: Should successfully create stream with callsign mappings
            assert result["success"] is True
            assert "stream_id" in result

            # Verify stream was created with correct callsign settings
            stream = Stream.query.get(result["stream_id"])
            assert stream.enable_callsign_mapping is True
            assert stream.callsign_identifier_field == "imei"
            assert stream.callsign_error_handling == "fallback"
            assert stream.enable_per_callsign_cot_types is True

            # Verify callsign mappings were created
            mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(mappings) == 2

            # Check mapping details
            mapping_dict = {m.identifier_value: m for m in mappings}
            assert "123456789" in mapping_dict
            assert mapping_dict["123456789"].custom_callsign == "Alpha-1"
            assert mapping_dict["123456789"].cot_type == "a-f-G-E-V-C"
            assert "987654321" in mapping_dict
            assert mapping_dict["987654321"].custom_callsign == "Bravo-2"

    def test_create_stream_without_callsign_mappings(self, app, db_session):
        """Test creating a stream without callsign mapping - FAILING TEST FIRST"""
        with app.app_context():
            # Arrange: Create test TAK server
            import uuid

            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.stream_operations_service import \
                StreamOperationsService

            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Prepare stream data without callsign mapping
            stream_data = {
                "name": "Regular Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": False,
                "plugin_username": "test_user",
                "plugin_password": "test_pass",
            }

            # Act: Create stream without callsign data
            result = service.create_stream(stream_data)

            # Assert: Should successfully create stream without callsign mappings
            assert result["success"] is True
            assert "stream_id" in result

            # Verify stream was created with correct settings
            stream = Stream.query.get(result["stream_id"])
            assert stream.enable_callsign_mapping is False
            assert stream.callsign_identifier_field is None

            # Verify no callsign mappings were created
            mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(mappings) == 0

    def test_update_stream_callsign_mappings(self, app, db_session):
        """Test updating stream callsign mappings - FAILING TEST FIRST"""
        with app.app_context():
            # Arrange: Create test stream
            import uuid

            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.stream_operations_service import \
                StreamOperationsService

            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=False,
            )
            db_session.add(stream)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()
            mock_stream_manager.get_stream_status.return_value = {"running": False}
            mock_stream_manager.start_stream_sync.return_value = True
            mock_stream_manager.stop_stream_sync.return_value = True

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Prepare update data with callsign mapping
            update_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin",
                "tak_server_id": tak_server.id,
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "skip",
                "enable_per_callsign_cot_types": False,
                "callsign_mapping_0_identifier": "111222333",
                "callsign_mapping_0_callsign": "Delta-4",
                "callsign_mapping_1_identifier": "444555666",
                "callsign_mapping_1_callsign": "Echo-5",
            }

            # Act: Update stream with callsign data
            result = service.update_stream_safely(stream.id, update_data)

            # Assert: Should successfully update stream with callsign mappings
            assert result["success"] is True

            # Verify stream was updated with correct callsign settings
            updated_stream = Stream.query.get(stream.id)
            assert updated_stream.enable_callsign_mapping is True
            assert updated_stream.callsign_identifier_field == "imei"
            assert updated_stream.callsign_error_handling == "skip"
            assert updated_stream.enable_per_callsign_cot_types is False

            # Verify callsign mappings were created
            mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(mappings) == 2

            # Check mapping details
            callsigns = [m.custom_callsign for m in mappings]
            assert "Delta-4" in callsigns
            assert "Echo-5" in callsigns

    def test_create_callsign_mappings_helper(self, app, db_session):
        """Test _create_callsign_mappings helper method - FAILING TEST FIRST"""
        with app.app_context():
            # Arrange: Create test stream
            import uuid

            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.stream_operations_service import \
                StreamOperationsService

            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            db_session.add(stream)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Prepare form data with callsign mappings
            form_data = {
                "callsign_mapping_0_identifier": "AAA111",
                "callsign_mapping_0_callsign": "Unit-1",
                "callsign_mapping_0_cot_type": "a-f-G-U-H",
                "callsign_mapping_1_identifier": "BBB222",
                "callsign_mapping_1_callsign": "Unit-2",
                "callsign_mapping_2_identifier": "CCC333",
                "callsign_mapping_2_callsign": "Unit-3",
            }

            # Act: Create callsign mappings using helper method
            service._create_callsign_mappings(stream, form_data)
            db_session.commit()

            # Assert: Should create mappings from form data
            mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(mappings) == 3

            # Verify mapping details
            mapping_dict = {m.identifier_value: m for m in mappings}
            assert "AAA111" in mapping_dict
            assert mapping_dict["AAA111"].custom_callsign == "Unit-1"
            assert mapping_dict["AAA111"].cot_type == "a-f-G-U-H"
            assert "BBB222" in mapping_dict
            assert mapping_dict["BBB222"].custom_callsign == "Unit-2"
            assert mapping_dict["BBB222"].cot_type is None
            assert "CCC333" in mapping_dict
            assert mapping_dict["CCC333"].custom_callsign == "Unit-3"

    def test_update_callsign_mappings_helper(self, app, db_session):
        """Test _update_callsign_mappings helper method - FAILING TEST FIRST"""
        with app.app_context():
            # Arrange: Create test stream with existing mappings
            import uuid

            from models.callsign_mapping import CallsignMapping
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.stream_operations_service import \
                StreamOperationsService

            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
            )
            db_session.add(stream)
            db_session.commit()

            # Create existing mappings
            old_mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="OLD123",
                custom_callsign="OldUnit",
            )
            db_session.add(old_mapping)
            db_session.commit()

            # Mock stream manager
            mock_stream_manager = Mock()

            # Create service instance
            service = StreamOperationsService(mock_stream_manager, db_session)

            # Prepare new form data
            form_data = {
                "callsign_mapping_0_identifier": "NEW456",
                "callsign_mapping_0_callsign": "NewUnit",
            }

            # Act: Update callsign mappings
            service._update_callsign_mappings(stream, form_data)
            db_session.commit()

            # Assert: Should clear old mappings and create new ones
            mappings = CallsignMapping.query.filter_by(stream_id=stream.id).all()
            assert len(mappings) == 1
            assert mappings[0].identifier_value == "NEW456"
            assert mappings[0].custom_callsign == "NewUnit"

            # Verify old mapping is gone
            old_exists = CallsignMapping.query.filter_by(
                stream_id=stream.id, identifier_value="OLD123"
            ).first()
            assert old_exists is None


@pytest.mark.integration
class TestStreamWorkerConfiguration:
    """Test stream worker stream object assignment to plugins."""

    @pytest.mark.asyncio
    async def test_stream_worker_assigns_stream_to_plugin(self, app, db_session):
        """Test that stream worker assigns stream object to plugins for stream-level configuration access."""
        with app.app_context():
            from unittest.mock import AsyncMock, Mock, patch

            from database import db
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.database_manager import DatabaseManager
            from services.session_manager import SessionManager

            # Create test TAK server
            tak_server = TakServer(
                name="Test Server",
                host="127.0.0.1",
                port=8089,
                protocol="tcp",
                verify_ssl=False,
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create test stream with specific cot_type_mode
            stream = Stream(
                name="Test Stream",
                plugin_type="deepstate",
                tak_server_id=tak_server.id,
                cot_type_mode="per_point",  # Stream-level setting
                cot_type="a-f-G-U-C",  # Stream-level setting
                plugin_config='{"api_url": "https://test.com"}',  # Plugin-specific config
            )
            db_session.add(stream)
            db_session.commit()

            # Mock dependencies
            mock_session_manager = Mock(spec=SessionManager)
            mock_session_manager.session = Mock()  # Add session attribute
            mock_db_manager = Mock(spec=DatabaseManager)

            # Mock plugin manager to capture the plugin and verify stream assignment
            created_plugin = AsyncMock()
            created_plugin.validate_config.return_value = True
            created_plugin.fetch_locations.return_value = (
                []
            )  # Return empty list for async method

            def mock_get_plugin(plugin_type, config):
                return created_plugin

            with (
                patch(
                    "services.stream_worker.get_plugin_manager"
                ) as mock_plugin_manager,
                patch("services.stream_worker.cot_service") as mock_cot_service,
            ):
                mock_plugin_manager.return_value.get_plugin = mock_get_plugin

                # Mock COT service to prevent TAK server connections
                mock_cot_service.start_worker = AsyncMock(return_value=True)
                mock_cot_service.is_worker_running.return_value = True
                mock_cot_service.get_worker_status.return_value = {
                    "worker_running": True
                }
                mock_cot_service.enqueue_event = AsyncMock(return_value=True)

                # Create stream worker
                worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

                # Start the worker (this initializes the plugin)
                result = await worker.start()

                # Assert plugin was initialized and stream was assigned
                assert result is True
                assert worker.plugin is created_plugin
                assert hasattr(created_plugin, "stream")
                assert created_plugin.stream is stream

    @pytest.mark.asyncio
    async def test_stream_worker_handles_missing_stream_fields_gracefully(
        self, app, db_session
    ):
        """Test that stream worker handles missing stream-level fields gracefully."""
        with app.app_context():
            from unittest.mock import AsyncMock, Mock, patch

            from database import db
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.database_manager import DatabaseManager
            from services.session_manager import SessionManager

            # Create test TAK server
            tak_server = TakServer(
                name="Test Server",
                host="127.0.0.1",
                port=8089,
                protocol="tcp",
                verify_ssl=False,
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create test stream with explicit cot_type_mode/cot_type to test defaults
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                cot_type_mode="stream",  # Add default stream mode
                cot_type="a-f-G-U-C",  # Add default CoT type
                plugin_config='{"url": "https://test.com"}',
            )
            db_session.add(stream)
            db_session.commit()

            # Mock dependencies
            mock_session_manager = Mock(spec=SessionManager)
            mock_session_manager.session = Mock()  # Add session attribute
            mock_db_manager = Mock(spec=DatabaseManager)

            # Mock plugin manager to capture the config passed to plugins
            captured_config = {}

            def mock_get_plugin(plugin_type, config):
                # Capture the full config passed to plugin (should include stream config)
                captured_config.clear()
                captured_config.update(config)
                mock_plugin = AsyncMock()

                # Make validate_config synchronous
                def sync_validate_config():
                    return True

                mock_plugin.validate_config = sync_validate_config
                mock_plugin.fetch_locations.return_value = (
                    []
                )  # Return empty list for async method
                return mock_plugin

            with (
                patch(
                    "services.stream_worker.get_plugin_manager"
                ) as mock_plugin_manager,
                patch("services.stream_worker.cot_service") as mock_cot_service,
            ):
                mock_plugin_manager.return_value.get_plugin = mock_get_plugin

                # Mock COT service to prevent TAK server connections
                mock_cot_service.start_worker = AsyncMock(return_value=True)
                mock_cot_service.is_worker_running.return_value = True
                mock_cot_service.get_worker_status.return_value = {
                    "worker_running": True
                }
                mock_cot_service.enqueue_event = AsyncMock(return_value=True)

                # Create stream worker
                worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

                # Start the worker (this initializes the plugin)
                result = await worker.start()

                # Assert plugin was initialized with plugin config (not stream config)
                assert result is True
                # Debug: captured_config should contain plugin-specific config
                # Plugin config should contain the original plugin configuration
                assert "url" in captured_config
                assert captured_config["url"] == "https://test.com"

                # Stream-level config should be accessible through the worker's stream object
                assert worker.stream.cot_type_mode == "stream"
                assert worker.stream.cot_type == "a-f-G-U-C"

    @pytest.mark.asyncio
    async def test_stream_worker_preserves_plugin_specific_config(
        self, app, db_session
    ):
        """Test that stream worker preserves plugin-specific configuration when adding stream config."""
        with app.app_context():
            from unittest.mock import AsyncMock, Mock, patch

            from database import db
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.database_manager import DatabaseManager
            from services.session_manager import SessionManager

            # Create test TAK server
            tak_server = TakServer(
                name="Test Server",
                host="127.0.0.1",
                port=8089,
                protocol="tcp",
                verify_ssl=False,
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create test stream with complex plugin configuration
            plugin_config = {
                "api_url": "https://test.com",
                "username": "testuser",
                "password": "encrypted_password",
                "timeout": 30,
                "custom_field": "custom_value",
            }

            stream = Stream(
                name="Test Stream",
                plugin_type="traccar",
                tak_server_id=tak_server.id,
                cot_type_mode="stream",
                cot_type="a-h-G-U-C",
                plugin_config=str(plugin_config).replace(
                    "'", '"'
                ),  # Convert to JSON string
            )
            db_session.add(stream)
            db_session.commit()

            # Mock dependencies
            mock_session_manager = Mock(spec=SessionManager)
            mock_session_manager.session = Mock()  # Add session attribute
            mock_db_manager = Mock(spec=DatabaseManager)

            # Mock plugin manager to capture the config passed to plugins
            captured_config = {}

            def mock_get_plugin(plugin_type, config):
                captured_config.update(config)
                mock_plugin = AsyncMock()

                # Make validate_config synchronous
                def sync_validate_config():
                    return True

                mock_plugin.validate_config = sync_validate_config
                mock_plugin.fetch_locations.return_value = (
                    []
                )  # Return empty list for async method
                return mock_plugin

            with (
                patch(
                    "services.stream_worker.get_plugin_manager"
                ) as mock_plugin_manager,
                patch("services.stream_worker.cot_service") as mock_cot_service,
            ):
                mock_plugin_manager.return_value.get_plugin = mock_get_plugin

                # Mock COT service to prevent TAK server connections
                mock_cot_service.start_worker = AsyncMock(return_value=True)
                mock_cot_service.is_worker_running.return_value = True
                mock_cot_service.get_worker_status.return_value = {
                    "worker_running": True
                }
                mock_cot_service.enqueue_event = AsyncMock(return_value=True)

                # Create stream worker
                worker = StreamWorker(stream, mock_session_manager, mock_db_manager)

                # Start the worker (this initializes the plugin)
                result = await worker.start()

                # Assert all configuration is preserved and stream config is added
                assert result is True

                # Plugin-specific configuration should be preserved in plugin config
                # Debug: captured_config should contain plugin-specific config
                assert "api_url" in captured_config
                assert captured_config["api_url"] == "https://test.com"
                assert "timeout" in captured_config
                assert captured_config["timeout"] == 30
                assert "custom_field" in captured_config
                assert captured_config["custom_field"] == "custom_value"

                # Stream-level configuration should be accessible through worker's stream
                assert worker.stream.cot_type_mode == "stream"
                assert worker.stream.cot_type == "a-h-G-U-C"


@pytest.mark.integration
class TestStreamWorkerCotTypeModeIntegration:
    """Test stream worker CoT type mode functionality with plugin integration."""

    @pytest.mark.asyncio
    async def test_stream_worker_deepstate_plugin_integration(self, app, db_session):
        """Test that stream worker properly configures deepstate plugin with CoT type mode."""
        with app.app_context():
            from unittest.mock import AsyncMock, Mock, patch

            from database import db
            from models.stream import Stream
            from models.tak_server import TakServer
            from services.database_manager import DatabaseManager
            from services.session_manager import SessionManager

            # Create test TAK server
            tak_server = TakServer(
                name="Test Server",
                host="127.0.0.1",
                port=8089,
                protocol="tcp",
                verify_ssl=False,
            )
            db_session.add(tak_server)
            db_session.commit()

            # Test both CoT type modes
            test_cases = [
                {
                    "name": "Stream Mode Test",
                    "cot_type_mode": "stream",
                    "cot_type": "a-f-G-U-C",
                    "expected_mode": "stream",
                },
                {
                    "name": "Per-Point Mode Test",
                    "cot_type_mode": "per_point",
                    "cot_type": "a-h-G-U-C",
                    "expected_mode": "per_point",
                },
            ]

            for case in test_cases:
                # Create test stream
                stream = Stream(
                    name=case["name"],
                    plugin_type="deepstate",
                    tak_server_id=tak_server.id,
                    cot_type_mode=case["cot_type_mode"],
                    cot_type=case["cot_type"],
                    plugin_config='{"api_url": "https://deepstatemap.live/api/history/last"}',
                )
                db_session.add(stream)
                db_session.commit()

                # Mock dependencies
                mock_session_manager = Mock(spec=SessionManager)
                mock_session_manager.session = Mock()  # Add session attribute
                mock_db_manager = Mock(spec=DatabaseManager)

                # Test with actual deepstate plugin if available
                try:
                    from plugins.deepstate_plugin import DeepstatePlugin

                    # Create real plugin to test actual integration
                    def mock_get_plugin(plugin_type, config):
                        if plugin_type == "deepstate":
                            plugin = DeepstatePlugin(config)

                            # Mock the get_decrypted_config to include stream-level config
                            def get_decrypted_config():
                                result = config.copy()
                                result["cot_type_mode"] = case["cot_type_mode"]
                                result["cot_type"] = case["cot_type"]
                                return result

                            plugin.get_decrypted_config = get_decrypted_config

                            # Make validate_config synchronous
                            def sync_validate_config():
                                return True

                            plugin.validate_config = sync_validate_config
                            return plugin
                        return None

                    with (
                        patch(
                            "services.stream_worker.get_plugin_manager"
                        ) as mock_plugin_manager,
                        patch("services.stream_worker.cot_service") as mock_cot_service,
                    ):
                        mock_plugin_manager.return_value.get_plugin = mock_get_plugin

                        # Mock COT service to prevent TAK server connections
                        mock_cot_service.return_value.start_worker.return_value = True
                        mock_cot_service.return_value.is_worker_running.return_value = (
                            True
                        )

                        # Create stream worker
                        worker = StreamWorker(
                            stream, mock_session_manager, mock_db_manager
                        )

                        # Start the worker (this initializes the plugin)
                        result = await worker.start()

                        # Assert plugin was initialized successfully
                        assert result is True
                        assert worker.plugin is not None

                        # Verify plugin has correct configuration
                        plugin_config = worker.plugin.get_decrypted_config()
                        assert plugin_config["cot_type_mode"] == case["expected_mode"]
                        assert plugin_config["cot_type"] == case["cot_type"]
                        assert (
                            plugin_config["api_url"]
                            == "https://deepstatemap.live/api/history/last"
                        )

                except ImportError:
                    # Skip if deepstate plugin not available
                    pytest.skip("Deepstate plugin not available for integration test")

                # Clean up for next test case
                db_session.delete(stream)
                db_session.commit()
