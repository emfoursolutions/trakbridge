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
