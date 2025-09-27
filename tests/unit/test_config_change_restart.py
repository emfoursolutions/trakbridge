"""Unit tests for automatic stream restart after configuration changes."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from services.stream_operations_service import StreamOperationsService


class TestConfigChangeRestart:
    """Test automatic stream restart with queue flushing after configuration changes."""

    @pytest.fixture
    def mock_stream_manager(self):
        """Create a mock stream manager."""
        stream_manager = Mock()
        stream_manager.restart_stream_sync = Mock(return_value=True)
        stream_manager.stop_stream_sync = Mock(return_value=True)
        stream_manager.refresh_stream_tak_workers = Mock(return_value=True)
        return stream_manager

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = Mock()
        session.commit = Mock()
        session.rollback = Mock()
        session.refresh = Mock()
        return session

    @pytest.fixture
    def stream_operations_service(self, mock_stream_manager, mock_session):
        """Create a StreamOperationsService with mocked dependencies."""
        mock_db = Mock()
        service = StreamOperationsService(mock_stream_manager, mock_db)
        service._get_session = Mock(return_value=mock_session)
        service._get_database_type = Mock(return_value="sqlite")
        service._safe_get_stream_status = Mock()
        service._is_concurrency_error = Mock(return_value=False)
        service._update_callsign_mappings = Mock()
        service._publish_config_change = Mock()
        return service

    @pytest.fixture
    def mock_stream(self):
        """Create a mock stream object."""
        stream = Mock()
        stream.id = 1
        stream.name = "Test Stream"
        stream.enable_callsign_mapping = False
        stream.tak_servers = []
        stream.tak_server_id = None
        stream.plugin_type = "garmin"
        stream.poll_interval = 120
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.callsign_identifier_field = None
        stream.callsign_error_handling = "fallback"
        stream.enable_per_callsign_cot_types = False
        stream.set_plugin_config = Mock()
        return stream

    @patch("plugins.plugin_manager.get_plugin_manager")
    @patch("services.stream_config_service.StreamConfigService")
    def test_update_stream_safely_calls_restart_for_running_stream(
        self,
        mock_config_service_class,
        mock_plugin_manager,
        stream_operations_service,
        mock_stream_manager,
        mock_stream,
        app,
        db_session,
    ):
        """Test that configuration changes trigger restart_stream_sync for running streams."""
        with app.app_context():
            # Create real database records instead of mocking
            from models.stream import Stream
            from models.tak_server import TakServer

            # Create a test TAK server
            tak_server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create a test stream
            test_stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=tak_server.id
            )
            db_session.add(test_stream)
            db_session.commit()

            # Mock plugin manager and config service
            mock_plugin_manager.return_value.get_plugin_metadata.return_value = {
                "config_fields": []
            }
            mock_config_service = Mock()
            mock_config_service.extract_plugin_config_from_request.return_value = {}
            mock_config_service.merge_plugin_config_with_existing.return_value = {}
            mock_config_service_class.return_value = mock_config_service

            # Set stream as running
            stream_operations_service._safe_get_stream_status.return_value = {
                "running": True
            }

            # Test data
            update_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin",
                "poll_interval": 300,
                "cot_type": "a-f-G-U-C",
                "cot_stale_time": 600,
                "tak_servers": [str(tak_server.id)],
            }

            # Execute
            result = stream_operations_service.update_stream_safely(
                test_stream.id, update_data
            )

            # Verify
            assert result["success"] is True
            # The actual implementation calls restart_stream_sync directly (which handles stop internally)
            # and refresh_stream_tak_workers for configuration changes
            mock_stream_manager.restart_stream_sync.assert_called_once_with(
                test_stream.id
            )
            mock_stream_manager.refresh_stream_tak_workers.assert_called_once_with(
                test_stream.id
            )

    @patch("plugins.plugin_manager.get_plugin_manager")
    @patch("services.stream_config_service.StreamConfigService")
    def test_update_stream_safely_no_restart_for_stopped_stream(
        self,
        mock_config_service_class,
        mock_plugin_manager,
        stream_operations_service,
        mock_stream_manager,
        mock_stream,
        app,
        db_session,
    ):
        """Test that configuration changes don't trigger restart for already stopped streams."""
        with app.app_context():
            # Create real database records instead of mocking
            from models.stream import Stream
            from models.tak_server import TakServer

            # Create a test TAK server
            tak_server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create a test stream
            test_stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=tak_server.id
            )
            db_session.add(test_stream)
            db_session.commit()

            # Mock plugin manager and config service
            mock_plugin_manager.return_value.get_plugin_metadata.return_value = {
                "config_fields": []
            }
            mock_config_service = Mock()
            mock_config_service.extract_plugin_config_from_request.return_value = {}
            mock_config_service.merge_plugin_config_with_existing.return_value = {}
            mock_config_service_class.return_value = mock_config_service

            # Set stream as NOT running
            stream_operations_service._safe_get_stream_status.return_value = {
                "running": False
            }

            # Test data
            update_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin",
                "poll_interval": 300,
                "cot_type": "a-f-G-U-C",
                "cot_stale_time": 600,
                "tak_servers": [str(tak_server.id)],
            }

            # Execute
            result = stream_operations_service.update_stream_safely(
                test_stream.id, update_data
            )

            # Verify
            assert result["success"] is True
            # For stopped streams, no restart should occur, but refresh should still happen
            mock_stream_manager.restart_stream_sync.assert_not_called()
            # TAK worker refresh should still happen for configuration changes
            mock_stream_manager.refresh_stream_tak_workers.assert_called_once_with(
                test_stream.id
            )

    @patch("plugins.plugin_manager.get_plugin_manager")
    @patch("services.stream_config_service.StreamConfigService")
    def test_update_stream_safely_continues_on_restart_failure(
        self,
        mock_config_service_class,
        mock_plugin_manager,
        stream_operations_service,
        mock_stream_manager,
        mock_stream,
        app,
        db_session,
    ):
        """Test that configuration updates succeed even if restart fails."""
        with app.app_context():
            # Create real database records instead of mocking
            from models.stream import Stream
            from models.tak_server import TakServer

            # Create a test TAK server
            tak_server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(tak_server)
            db_session.commit()

            # Create a test stream
            test_stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=tak_server.id
            )
            db_session.add(test_stream)
            db_session.commit()

            # Mock plugin manager and config service
            mock_plugin_manager.return_value.get_plugin_metadata.return_value = {
                "config_fields": []
            }
            mock_config_service = Mock()
            mock_config_service.extract_plugin_config_from_request.return_value = {}
            mock_config_service.merge_plugin_config_with_existing.return_value = {}
            mock_config_service_class.return_value = mock_config_service

            # Set stream as running
            stream_operations_service._safe_get_stream_status.return_value = {
                "running": True
            }

            # Make restart fail
            mock_stream_manager.restart_stream_sync.return_value = False

            # Test data
            update_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin",
                "poll_interval": 300,
                "cot_type": "a-f-G-U-C",
                "cot_stale_time": 600,
                "tak_servers": [str(tak_server.id)],
            }

            # Execute
            result = stream_operations_service.update_stream_safely(
                test_stream.id, update_data
            )

            # Verify
            assert result["success"] is True  # Update should still succeed
            # The implementation calls restart_stream_sync directly (which handles restart failure gracefully)
            mock_stream_manager.restart_stream_sync.assert_called_once_with(
                test_stream.id
            )
            mock_stream_manager.refresh_stream_tak_workers.assert_called_once_with(
                test_stream.id
            )
