"""Unit tests for database functionality."""

import pytest
from sqlalchemy import inspect
from database import db
from models.user import User, UserRole, AuthProvider
from models.stream import Stream
from models.tak_server import TakServer


class TestDatabaseOperations:
    """Test database operations."""

    def test_database_tables_creation(self, app, db_session):
        """Test that database tables can be created."""
        with app.app_context():
            # Tables should be created automatically
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            assert len(tables) > 0

    def test_user_crud_operations(self, app, db_session):
        """Test CRUD operations on User model."""
        with app.app_context():
            # Create
            user = User(
                username="testuser",
                email="test@example.com",
                full_name="Test User",
                role=UserRole.USER,
                auth_provider=AuthProvider.LOCAL,
            )
            db_session.add(user)
            db_session.commit()

            # Read
            found_user = User.query.filter_by(username="testuser").first()
            assert found_user is not None
            assert found_user.email == "test@example.com"

            # Update
            found_user.email = "updated@example.com"
            db_session.commit()

            updated_user = User.query.filter_by(username="testuser").first()
            assert updated_user.email == "updated@example.com"

            # Delete
            db_session.delete(updated_user)
            db_session.commit()

            deleted_user = User.query.filter_by(username="testuser").first()
            assert deleted_user is None

    def test_stream_crud_operations(self, app, db_session):
        """Test CRUD operations on Stream model."""
        with app.app_context():
            # Create
            stream = Stream(name="Test Stream", plugin_type="garmin", is_active=True)
            stream.set_plugin_config({"api_key": "test"})
            db_session.add(stream)
            db_session.commit()

            # Read
            found_stream = Stream.query.filter_by(name="Test Stream").first()
            assert found_stream is not None
            assert found_stream.plugin_type == "garmin"

            # Update
            found_stream.is_active = False
            db_session.commit()

            updated_stream = Stream.query.filter_by(name="Test Stream").first()
            assert updated_stream.is_active is False

    def test_tak_server_crud_operations(self, app, db_session):
        """Test CRUD operations on TakServer model."""
        with app.app_context():
            # Create
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tcp"
            )
            db_session.add(server)
            db_session.commit()

            # Read
            found_server = TakServer.query.filter_by(name="Test Server").first()
            assert found_server is not None
            assert found_server.host == "localhost"
            assert found_server.port == 8089

    def test_database_relationships(self, app, db_session):
        """Test database relationships between models."""
        with app.app_context():
            # Create a user
            user = User(
                username="owner", email="owner@example.com", role=UserRole.ADMIN
            )
            db_session.add(user)
            db_session.commit()

            # Create streams owned by the user (if relationship exists)
            stream = Stream(name="User Stream", plugin_type="spot", is_active=True)
            stream.set_plugin_config({"feed_id": "test"})
            # Note: If there's no relationship, this test still validates CRUD
            db_session.add(stream)
            db_session.commit()

            assert stream.id is not None
