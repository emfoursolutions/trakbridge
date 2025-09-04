"""Unit tests for TrakBridge models."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import db
from models.stream import Stream
from models.tak_server import TakServer
from models.user import AuthProvider, User, UserRole, UserSession


class TestUserModel:
    """Test the User model."""

    def test_user_creation(self, app, db_session):
        """Test creating a user."""
        with app.app_context():
            user = User(
                username="testuser",
                email="test@example.com",
                full_name="Test User",
                role=UserRole.USER,
            )
            db_session.add(user)
            db_session.commit()

            assert user.id is not None
            assert user.username == "testuser"
            assert user.email == "test@example.com"
            assert user.full_name == "Test User"
            assert user.role == UserRole.USER

    def test_user_password_hashing(self, app, db_session):
        """Test password hashing and verification."""
        with app.app_context():
            user = User(
                username="testuser",
                email="test@example.com",
                auth_provider=AuthProvider.LOCAL,
            )
            user.set_password("testpassword")

            assert user.password_hash is not None
            assert user.check_password("testpassword") is True
            assert user.check_password("wrongpassword") is False

    def test_user_roles(self, app):
        """Test user role enumeration."""
        with app.app_context():
            assert UserRole.ADMIN.value == "admin"
            assert UserRole.OPERATOR.value == "operator"
            assert UserRole.USER.value == "user"


class TestStreamModel:
    """Test the Stream model."""

    def test_stream_creation(self, app, db_session):
        """Test creating a stream."""
        with app.app_context():
            stream = Stream(name="Test Stream", plugin_type="garmin", is_active=True)
            stream.set_plugin_config({"test": "config"})
            db_session.add(stream)
            db_session.commit()

            assert stream.id is not None
            assert stream.name == "Test Stream"
            assert stream.plugin_type == "garmin"
            assert stream.is_active is True

    def test_stream_callsign_fields(self, app, db_session):
        """Test new callsign-related fields in Stream model"""
        with app.app_context():
            stream = Stream(name="Test Stream", plugin_type="garmin")

            # Test default values
            assert stream.enable_callsign_mapping is False
            assert stream.callsign_identifier_field is None
            assert stream.callsign_error_handling == "fallback"
            assert stream.enable_per_callsign_cot_types is False

            # Test setting values
            stream.enable_callsign_mapping = True
            stream.callsign_identifier_field = "imei"
            stream.callsign_error_handling = "skip"
            stream.enable_per_callsign_cot_types = True

            db_session.add(stream)
            db_session.commit()

            # Verify saved values
            saved_stream = db_session.get(Stream, stream.id)
            assert saved_stream.enable_callsign_mapping is True
            assert saved_stream.callsign_identifier_field == "imei"
            assert saved_stream.callsign_error_handling == "skip"
            assert saved_stream.enable_per_callsign_cot_types is True


class TestTakServerModel:
    """Test the TakServer model."""

    def test_tak_server_creation(self, app, db_session):
        """Test creating a TAK server."""
        with app.app_context():
            # Use unique name to avoid constraint violations between tests
            unique_name = f"Test Server {uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name, host="localhost", port=8089, protocol="tcp"
            )
            db_session.add(server)
            db_session.commit()

            assert server.id is not None
            assert server.name == unique_name
            assert server.host == "localhost"
            assert server.port == 8089


class TestCallsignMappingModel:
    """Test the CallsignMapping model - integrated with existing model tests"""

    def test_callsign_mapping_creation(self, app, db_session):
        """Test CallsignMapping model creation and validation"""
        with app.app_context():
            # Import here to test if the model exists
            from models.callsign_mapping import CallsignMapping

            # Create test stream first (using existing stream test patterns)
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()

            # Test CallsignMapping creation
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="ABC123",
                custom_callsign="Alpha-1",
                cot_type="a-f-G-U-C",
            )
            db_session.add(mapping)
            db_session.commit()

            assert mapping.id is not None
            assert mapping.stream_id == stream.id
            assert mapping.identifier_value == "ABC123"
            assert mapping.custom_callsign == "Alpha-1"
            assert mapping.cot_type == "a-f-G-U-C"

    def test_stream_callsign_relationship(self, app, db_session):
        """Test Stream <-> CallsignMapping relationship - follows existing test patterns"""
        with app.app_context():
            from models.callsign_mapping import CallsignMapping

            # Create test stream
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()

            # Create callsign mapping
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="DEF456",
                custom_callsign="Bravo-2",
            )
            db_session.add(mapping)
            db_session.commit()

            # Test relationship from stream side
            assert len(stream.callsign_mappings) == 1
            assert stream.callsign_mappings[0].custom_callsign == "Bravo-2"

            # Test relationship from mapping side
            assert mapping.stream == stream
            assert mapping.stream.name == "Test Stream"

    def test_callsign_mapping_uniqueness(self, app, db_session):
        """Test unique constraint on stream_id + identifier_value"""
        with app.app_context():
            from sqlalchemy.exc import IntegrityError

            from models.callsign_mapping import CallsignMapping

            # Create test stream
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()

            # Create first mapping
            mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="UNIQUE123",
                custom_callsign="Charlie-1",
            )
            db_session.add(mapping1)
            db_session.commit()

            # Try to create duplicate mapping - should fail
            mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="UNIQUE123",  # Same identifier
                custom_callsign="Charlie-2",  # Different callsign
            )
            db_session.add(mapping2)

            # This should raise an IntegrityError due to unique constraint
            with pytest.raises(IntegrityError):
                db_session.commit()

    def test_callsign_mapping_cascade_deletion(self, app, db_session):
        """Test that callsign mappings are deleted when stream is deleted"""
        with app.app_context():
            from models.callsign_mapping import CallsignMapping

            # Create test stream
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.commit()
            stream_id = stream.id

            # Create callsign mapping
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="CASCADE123",
                custom_callsign="Delta-1",
            )
            db_session.add(mapping)
            db_session.commit()
            mapping_id = mapping.id

            # Verify mapping exists
            assert db_session.get(CallsignMapping, mapping_id) is not None

            # Delete stream
            db_session.delete(stream)
            db_session.commit()

            # Verify mapping was cascaded deleted
            assert db_session.get(CallsignMapping, mapping_id) is None


class TestCallsignMigrationIntegration:
    """Test callsign mapping database migration integration"""

    def test_database_schema_exists(self, app, db_session):
        """Test that the callsign_mappings table and stream fields exist in database schema"""
        with app.app_context():
            from sqlalchemy import inspect

            from database import db

            inspector = inspect(db.engine)

            # Check that callsign_mappings table exists
            tables = inspector.get_table_names()
            assert "callsign_mappings" in tables

            # Check callsign_mappings table columns
            callsign_columns = [
                col["name"] for col in inspector.get_columns("callsign_mappings")
            ]
            expected_callsign_columns = [
                "id",
                "stream_id",
                "identifier_value",
                "custom_callsign",
                "cot_type",
                "created_at",
                "updated_at",
            ]
            for col in expected_callsign_columns:
                assert (
                    col in callsign_columns
                ), f"Column '{col}' missing from callsign_mappings table"

            # Check streams table has new callsign columns
            stream_columns = [col["name"] for col in inspector.get_columns("streams")]
            expected_stream_callsign_columns = [
                "enable_callsign_mapping",
                "callsign_identifier_field",
                "callsign_error_handling",
                "enable_per_callsign_cot_types",
            ]
            for col in expected_stream_callsign_columns:
                assert (
                    col in stream_columns
                ), f"Column '{col}' missing from streams table"

    def test_database_constraints_exist(self, app, db_session):
        """Test that database constraints are properly created"""
        with app.app_context():
            from sqlalchemy import inspect

            from database import db

            inspector = inspect(db.engine)

            # Check unique constraint on callsign_mappings
            indexes = inspector.get_unique_constraints("callsign_mappings")
            unique_constraint_found = False
            for idx in indexes:
                if set(idx["column_names"]) == {"stream_id", "identifier_value"}:
                    unique_constraint_found = True
                    break
            assert (
                unique_constraint_found
            ), "Unique constraint on stream_id+identifier_value not found"

            # Check foreign key constraint
            foreign_keys = inspector.get_foreign_keys("callsign_mappings")
            fk_found = False
            for fk in foreign_keys:
                if (
                    fk["constrained_columns"] == ["stream_id"]
                    and fk["referred_table"] == "streams"
                ):
                    fk_found = True
                    break
            assert fk_found, "Foreign key constraint to streams table not found"
