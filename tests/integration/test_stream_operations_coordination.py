"""
ABOUTME: Integration tests for StreamOperationsService with worker coordination
ABOUTME: Tests Redis publish integration and configuration change notifications
"""

import os
import time
import unittest.mock as mock
from contextlib import contextmanager
from datetime import datetime
from unittest import TestCase

import pytest

from models.stream import Stream
from models.tak_server import TakServer
from services.stream_operations_service import StreamOperationsService
from services.worker_coordination_service import WorkerCoordinationService


@contextmanager
def clean_database_env():
    """Context manager to clear all database-related environment variables for testing."""
    database_env_vars = [
        "DATABASE_URL",
        "DB_TYPE", 
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
    ]
    
    # Save original values
    original_values = {}
    for var in database_env_vars:
        original_values[var] = os.environ.get(var)
        # Clear the variable if it exists
        if var in os.environ:
            del os.environ[var]
    
    try:
        yield
    finally:
        # Restore original values
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value
            elif var in os.environ:
                del os.environ[var]


class TestStreamOperationsCoordination:
    """Integration tests for stream operations with worker coordination"""

    @pytest.fixture
    def mock_stream_manager(self):
        """Mock stream manager for testing"""
        mock_manager = mock.Mock()
        mock_manager.start_stream_sync.return_value = True
        mock_manager.stop_stream_sync.return_value = True
        mock_manager.restart_stream_sync.return_value = True
        mock_manager.refresh_stream_tak_workers.return_value = True
        mock_manager.get_stream_status.return_value = {"running": False}
        mock_manager.get_all_stream_status.return_value = {}
        return mock_manager

    @pytest.fixture
    def mock_coordination_service(self):
        """Mock worker coordination service"""
        return mock.Mock(spec=WorkerCoordinationService)

    @pytest.fixture
    def stream_operations_service(self, app, mock_stream_manager):
        """Create StreamOperationsService instance for testing"""
        with clean_database_env():
            from database import db
            return StreamOperationsService(mock_stream_manager, db)

    def test_publish_config_change_on_stream_creation(self, app, stream_operations_service, mock_coordination_service):
        """Test that configuration changes are published when creating streams"""
        with clean_database_env():
            from database import db
            
            # Mock the coordination service
            with mock.patch.object(stream_operations_service, 'coordination_service', mock_coordination_service):
                # Create TAK server for testing
                tak_server = TakServer(
                    name="Test Server",
                    host="localhost",
                    port=8089,
                    protocol="tcp"
                )
                db.session.add(tak_server)
                db.session.commit()
                
                # Create stream data
                stream_data = {
                    "name": "Test Stream",
                    "plugin_type": "garmin",
                    "poll_interval": 120,
                    "cot_type": "a-f-G-U-C",
                    "tak_servers": [tak_server.id],
                }
                
                # Create stream
                result = stream_operations_service.create_stream(stream_data)
                
                # Should succeed
                assert result["success"] is True
                
                # Should have published config change
                mock_coordination_service.publish_config_change.assert_called_once()
                call_args = mock_coordination_service.publish_config_change.call_args[0]
                stream_id = call_args[0]
                version = call_args[1]
                
                assert stream_id == result["stream_id"]
                assert isinstance(version, datetime)

    def test_publish_config_change_on_stream_update(self, app, stream_operations_service, mock_coordination_service):
        """Test that configuration changes are published when updating streams"""
        with clean_database_env():
            from database import db
            
            # Create TAK server and stream
            tak_server = TakServer(
                name="Test Server",
                host="localhost", 
                port=8089,
                protocol="tcp"
            )
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
                tak_server_id=tak_server.id
            )
            db.session.add_all([tak_server, stream])
            db.session.commit()
            
            original_version = stream.config_version
            
            # Mock the coordination service
            with mock.patch.object(stream_operations_service, 'coordination_service', mock_coordination_service):
                # Update stream
                update_data = {
                    "name": "Updated Stream",
                    "plugin_type": "garmin",
                    "poll_interval": 300,
                    "cot_type": "a-f-G-U-C",
                    "tak_servers": [tak_server.id],
                }
                
                result = stream_operations_service.update_stream_safely(stream.id, update_data)
                
                # Should succeed
                assert result["success"] is True
                
                # Should have published config change
                mock_coordination_service.publish_config_change.assert_called_once()
                call_args = mock_coordination_service.publish_config_change.call_args[0]
                stream_id = call_args[0]
                version = call_args[1]
                
                assert stream_id == stream.id
                assert isinstance(version, datetime)
                assert version > original_version

    def test_config_version_updated_during_operations(self, app, stream_operations_service):
        """Test that config_version is updated during stream operations"""
        with clean_database_env():
            from database import db
            
            # Create TAK server
            tak_server = TakServer(
                name="Test Server",
                host="localhost",
                port=8089, 
                protocol="tcp"
            )
            db.session.add(tak_server)
            db.session.commit()
            
            # Create stream
            stream_data = {
                "name": "Test Stream", 
                "plugin_type": "garmin",
                "poll_interval": 120,
                "tak_servers": [tak_server.id],
            }
            
            result = stream_operations_service.create_stream(stream_data)
            assert result["success"] is True
            
            # Get the created stream
            stream = Stream.query.get(result["stream_id"])
            creation_version = stream.config_version
            
            # Wait and update
            time.sleep(0.01)
            update_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin", 
                "poll_interval": 300,
                "tak_servers": [tak_server.id],
            }
            
            result = stream_operations_service.update_stream_safely(stream.id, update_data)
            assert result["success"] is True
            
            # Refresh stream from database
            db.session.refresh(stream)
            
            # Version should be updated
            assert stream.config_version > creation_version

    def test_coordination_service_graceful_fallback(self, app, stream_operations_service):
        """Test graceful fallback when coordination service is unavailable"""
        with clean_database_env():
            from database import db
            
            # Create TAK server
            tak_server = TakServer(
                name="Test Server",
                host="localhost",
                port=8089,
                protocol="tcp"
            )
            db.session.add(tak_server)
            db.session.commit()
            
            # Mock coordination service to fail
            with mock.patch.object(stream_operations_service, 'coordination_service') as mock_coord:
                mock_coord.publish_config_change.side_effect = Exception("Redis unavailable")
                
                # Should still create stream successfully despite coordination failure
                stream_data = {
                    "name": "Test Stream",
                    "plugin_type": "garmin", 
                    "poll_interval": 120,
                    "tak_servers": [tak_server.id],
                }
                
                result = stream_operations_service.create_stream(stream_data)
                
                # Operation should succeed despite coordination failure
                assert result["success"] is True
                
                # Coordination was attempted
                mock_coord.publish_config_change.assert_called_once()

    def test_version_tracking_with_plugin_config_changes(self, app, stream_operations_service):
        """Test version tracking when plugin configurations are updated"""
        with clean_database_env():
            from database import db
            
            # Create TAK server
            tak_server = TakServer(
                name="Test Server",
                host="localhost",
                port=8089,
                protocol="tcp"
            )
            db.session.add(tak_server)
            db.session.commit()
            
            # Create stream with plugin config
            stream_data = {
                "name": "Test Stream",
                "plugin_type": "garmin",
                "poll_interval": 120,
                "tak_servers": [tak_server.id],
                "username": "test_user",
                "password": "test_pass"
            }
            
            result = stream_operations_service.create_stream(stream_data)
            assert result["success"] is True
            
            stream = Stream.query.get(result["stream_id"])
            original_version = stream.config_version
            
            # Update plugin configuration
            time.sleep(0.01)
            update_data = {
                "name": "Test Stream",
                "plugin_type": "garmin",
                "poll_interval": 120,
                "tak_servers": [tak_server.id],
                "username": "updated_user",
                "password": "updated_pass"
            }
            
            result = stream_operations_service.update_stream_safely(stream.id, update_data)
            assert result["success"] is True
            
            # Refresh and check version
            db.session.refresh(stream)
            assert stream.config_version > original_version

    def test_multiple_streams_independent_version_tracking(self, app, stream_operations_service):
        """Test that different streams maintain independent version tracking"""
        with clean_database_env():
            from database import db
            
            # Create TAK server
            tak_server = TakServer(
                name="Test Server",
                host="localhost", 
                port=8089,
                protocol="tcp"
            )
            db.session.add(tak_server)
            db.session.commit()
            
            # Create two streams
            stream1_data = {
                "name": "Stream 1",
                "plugin_type": "garmin",
                "tak_servers": [tak_server.id],
            }
            stream2_data = {
                "name": "Stream 2", 
                "plugin_type": "spot",
                "tak_servers": [tak_server.id],
            }
            
            result1 = stream_operations_service.create_stream(stream1_data)
            result2 = stream_operations_service.create_stream(stream2_data)
            
            assert result1["success"] is True
            assert result2["success"] is True
            
            stream1 = Stream.query.get(result1["stream_id"])
            stream2 = Stream.query.get(result2["stream_id"])
            
            version1_original = stream1.config_version
            version2_original = stream2.config_version
            
            # Update only stream1
            time.sleep(0.01)
            update_data = {
                "name": "Updated Stream 1",
                "plugin_type": "garmin",
                "tak_servers": [tak_server.id],
            }
            
            result = stream_operations_service.update_stream_safely(stream1.id, update_data)
            assert result["success"] is True
            
            # Refresh both streams
            db.session.refresh(stream1)
            db.session.refresh(stream2)
            
            # Only stream1 should have updated version
            assert stream1.config_version > version1_original
            assert stream2.config_version == version2_original

    def test_coordination_integration_with_real_service(self, app, stream_operations_service):
        """Test integration with real WorkerCoordinationService (disabled)"""
        with clean_database_env():
            from database import db
            
            # Create TAK server
            tak_server = TakServer(
                name="Test Server",
                host="localhost",
                port=8089, 
                protocol="tcp"
            )
            db.session.add(tak_server)
            db.session.commit()
            
            # Use real coordination service (should be disabled in test environment)
            stream_data = {
                "name": "Test Stream",
                "plugin_type": "garmin",
                "poll_interval": 120,
                "tak_servers": [tak_server.id],
            }
            
            result = stream_operations_service.create_stream(stream_data)
            
            # Should succeed even with real coordination service
            assert result["success"] is True
            
            # Stream should have version tracking
            stream = Stream.query.get(result["stream_id"])
            assert stream.config_version is not None
            assert isinstance(stream.config_version, datetime)