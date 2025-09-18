"""
ABOUTME: Unit tests for Stream model configuration version tracking functionality
ABOUTME: Tests the config_version field and update_config_version method
"""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest import TestCase

import pytest

from models.stream import Stream


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


class TestStreamVersionTracking:
    """Test Stream model version tracking functionality"""

    def test_stream_version_tracking_in_database(self, app):
        """Test config_version field creation and automatic timestamping"""
        with clean_database_env():
            from database import db
            
            # Create a stream instance
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            
            # Should have config_version set to current time by default
            assert stream.config_version is not None
            assert isinstance(stream.config_version, datetime)
            
            # Save to database
            db.session.add(stream)
            db.session.commit()
            
            # Refresh from database
            db.session.refresh(stream)
            
            # Should still have config_version
            assert stream.config_version is not None
            assert isinstance(stream.config_version, datetime)

    def test_update_config_version_method(self, app):
        """Test the update_config_version method updates timestamp"""
        with clean_database_env():
            from database import db
            
            # Create and save stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            db.session.add(stream)
            db.session.commit()
            
            # Store original version
            original_version = stream.config_version
            
            # Wait a moment to ensure timestamp difference
            time.sleep(0.01)
            
            # Update config version
            stream.update_config_version()
            
            # Should have updated timestamp
            assert stream.config_version > original_version
            assert isinstance(stream.config_version, datetime)

    def test_config_version_persists_in_database(self, app):
        """Test that config_version changes are saved to database"""
        with clean_database_env():
            from database import db
            
            # Create and save stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            db.session.add(stream)
            db.session.commit()
            stream_id = stream.id
            
            # Update version and save
            time.sleep(0.01)
            stream.update_config_version()
            updated_version = stream.config_version
            db.session.commit()
            
            # Fetch fresh instance from database
            fresh_stream = Stream.query.get(stream_id)
            
            # Should have the updated version
            assert fresh_stream.config_version == updated_version

    def test_version_comparison_for_coordination(self, app):
        """Test version comparison logic for worker coordination"""
        with clean_database_env():
            from database import db
            
            # Create stream
            stream = Stream(
                name="Test Stream", 
                plugin_type="garmin",
                poll_interval=120,
            )
            db.session.add(stream)
            db.session.commit()
            
            version1 = stream.config_version
            
            # Update version
            time.sleep(0.01)
            stream.update_config_version()
            version2 = stream.config_version
            
            # Newer version should be greater than older version
            assert version2 > version1
            
            # Same versions should be equal
            assert version1 == version1
            assert version2 == version2

    def test_multiple_streams_independent_versions(self, app):
        """Test that different streams maintain independent version tracking"""
        with clean_database_env():
            from database import db
            
            # Create two streams
            stream1 = Stream(
                name="Stream 1",
                plugin_type="garmin", 
                poll_interval=120,
            )
            stream2 = Stream(
                name="Stream 2",
                plugin_type="spot",
                poll_interval=180,
            )
            
            db.session.add_all([stream1, stream2])
            db.session.commit()
            
            original_version1 = stream1.config_version
            original_version2 = stream2.config_version
            
            # Update only stream1
            time.sleep(0.01)
            stream1.update_config_version()
            db.session.commit()
            
            # Refresh both from database
            db.session.refresh(stream1)
            db.session.refresh(stream2)
            
            # Stream1 should have new version, stream2 unchanged
            assert stream1.config_version > original_version1
            assert stream2.config_version == original_version2

    def test_version_tracking_with_plugin_config_updates(self, app):
        """Test version tracking when plugin configuration is updated"""
        with clean_database_env():
            from database import db
            
            # Create stream with plugin config
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            stream.set_plugin_config({"username": "test", "password": "secret"})
            
            db.session.add(stream)
            db.session.commit()
            
            original_version = stream.config_version
            
            # Update plugin config and version
            time.sleep(0.01)
            stream.set_plugin_config({"username": "updated", "password": "newsecret"})
            stream.update_config_version()
            db.session.commit()
            
            # Should have newer version
            assert stream.config_version > original_version

    def test_version_tracking_survives_stream_updates(self, app):
        """Test that version tracking works with other stream field updates"""
        with clean_database_env():
            from database import db
            
            # Create stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            db.session.add(stream)
            db.session.commit()
            
            original_version = stream.config_version
            
            # Update other fields and version
            time.sleep(0.01)
            stream.name = "Updated Stream"
            stream.poll_interval = 300
            stream.update_config_version()
            db.session.commit()
            
            # Should maintain version tracking
            assert stream.config_version > original_version
            assert stream.name == "Updated Stream"
            assert stream.poll_interval == 300

    def test_default_version_on_stream_creation(self, app):
        """Test that new streams get default config_version timestamp"""
        with clean_database_env():
            from database import db
            
            before_creation = datetime.utcnow()
            
            # Create stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
            )
            
            after_creation = datetime.utcnow()
            
            # Default version should be between before and after timestamps
            assert before_creation <= stream.config_version <= after_creation

    def test_version_precision_for_worker_coordination(self, app):
        """Test version timestamp precision is sufficient for coordination"""
        with clean_database_env():
            from database import db
            
            # Create stream
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin", 
                poll_interval=120,
            )
            db.session.add(stream)
            db.session.commit()
            
            # Perform rapid updates
            versions = []
            for i in range(5):
                time.sleep(0.001)  # 1ms delay
                stream.update_config_version()
                versions.append(stream.config_version)
            
            # All versions should be distinct and ordered
            assert len(set(versions)) == len(versions)  # All unique
            assert versions == sorted(versions)  # Chronologically ordered