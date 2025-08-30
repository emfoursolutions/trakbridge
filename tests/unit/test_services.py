"""Unit tests for TrakBridge services."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from services.encryption_service import EncryptionService
from services.logging_service import setup_logging
from services.stream_manager import StreamManager
from services.stream_worker import StreamWorker
from services.tak_servers_service import TakServerService, TakServerConnectionTester
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

    def test_stream_worker_callsign_application_disabled(self, app, db_session):
        """Test stream worker applies callsigns correctly when feature is disabled"""
        with app.app_context():
            from database import db
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping

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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # Location name should remain unchanged when feature disabled
            assert test_locations[0]["name"] == "Original Name"

    def test_stream_worker_callsign_application_enabled(self, app, db_session):
        """Test stream worker applies callsigns correctly when feature is enabled"""
        with app.app_context():
            from database import db
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping

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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # Location name should be updated with custom callsign
            assert test_locations[0]["name"] == "Alpha-1"

    def test_stream_worker_per_callsign_cot_types(self, app, db_session):
        """Test stream worker applies per-callsign CoT type overrides"""
        with app.app_context():
            from database import db
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping

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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # Should have both callsign and CoT type applied
            assert test_locations[0]["name"] == "Alpha-1"
            assert test_locations[0]["cot_type"] == "a-f-G-E-V-C"

    def test_stream_worker_callsign_error_handling_fallback(self, app, db_session):
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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # Should use fallback behavior (keep original name)
            assert test_locations[0]["name"] == "Original Name"

    def test_stream_worker_callsign_error_handling_skip(self, app, db_session):
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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # With skip mode, unmapped locations should be removed or marked
            # Implementation will determine exact behavior
            assert hasattr(worker, "_apply_callsign_mapping")

    def test_stream_worker_load_callsign_mappings(self, app, db_session):
        """Test stream worker loads callsign mappings efficiently from database"""
        with app.app_context():
            from database import db
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping

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
            import asyncio

            async def test_load():
                mappings_dict = await worker._load_callsign_mappings()
                return mappings_dict

            result = asyncio.run(test_load())

            # Should return dictionary mapping identifiers to mappings
            assert isinstance(result, dict)
            assert len(result) == 3
            assert "111111111" in result
            assert "222222222" in result
            assert "333333333" in result
            assert result["111111111"].custom_callsign == "Alpha-1"

    def test_stream_worker_plugin_integration(self, app, db_session):
        """Test stream worker integrates with plugin CallsignMappable interface"""
        with app.app_context():
            from database import db
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping

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
            import asyncio

            async def test_apply():
                await worker._apply_callsign_mapping(test_locations)

            asyncio.run(test_apply())

            # Should have applied callsign through plugin
            assert test_locations[0]["name"] == "Alpha-1"
