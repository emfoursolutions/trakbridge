"""
ABOUTME: Tests for database access patterns and service layer consistency
ABOUTME: Validates that services use proper SQLAlchemy ORM patterns instead of raw queries

Tests for Database Access Patterns
These tests validate that services use proper SQLAlchemy ORM patterns
and maintain consistent database access without unnecessary abstraction layers.

Author: Emfour Solutions
Created: 2025-09-04
"""

from unittest.mock import MagicMock

import pytest

from database import db
from models.stream import Stream
from models.tak_server import TakServer


class TestServiceDatabasePatterns:
    """Test that services use proper database access patterns."""

    def test_services_use_sqlalchemy_orm(self, app, db_session):
        """Test that services use SQLAlchemy ORM properly."""
        with app.app_context():
            from services.stream_operations_service import StreamOperationsService

            # Mock StreamManager for testing
            mock_stream_manager = MagicMock()
            service = StreamOperationsService(mock_stream_manager, db)

            # Check that service has proper database session access
            assert hasattr(service, "db"), "Service should have database access"
            assert hasattr(service, "_get_session"), "Service should have session accessor method"

            # Verify the service can get database session
            session = service._get_session()
            assert session is not None, "Service should be able to get database session"

    def test_models_have_proper_crud_methods(self, app, db_session):
        """Test that models provide proper CRUD functionality."""
        with app.app_context():
            # Test Stream model basic operations
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                poll_interval=120,
                cot_type="a-f-G-U-C",
                cot_stale_time=300,
            )

            # Test model can be created and saved
            db.session.add(stream)
            db.session.commit()

            # Test model can be retrieved
            retrieved = Stream.query.filter_by(name="Test Stream").first()
            assert retrieved is not None
            assert retrieved.name == "Test Stream"
            assert retrieved.plugin_type == "garmin"

            # Test model can be updated
            retrieved.poll_interval = 180
            db.session.commit()

            # Verify update
            updated = Stream.query.filter_by(name="Test Stream").first()
            assert updated.poll_interval == 180

            # Clean up
            db.session.delete(updated)
            db.session.commit()


class TestDatabaseIntegrity:
    """Test database integrity and constraint handling."""

    def test_database_session_handling(self, app, db_session):
        """Test proper database session management."""
        with app.app_context():
            # Test that we can create and rollback transactions
            stream = Stream(name="Rollback Test", plugin_type="garmin", poll_interval=120)

            db.session.add(stream)
            # Don't commit - test rollback
            db.session.rollback()

            # Should not exist after rollback
            found = Stream.query.filter_by(name="Rollback Test").first()
            assert found is None, "Stream should not exist after rollback"

    def test_model_validation(self, app, db_session):
        """Test that models properly validate data."""
        with app.app_context():
            # Test that models handle basic validation
            stream = Stream(
                name="Validation Test",
                plugin_type="garmin",
                poll_interval=60,  # Valid value
                cot_stale_time=300,
            )

            # Should be able to create valid model
            db.session.add(stream)
            db.session.commit()

            # Clean up
            db.session.delete(stream)
            db.session.commit()
