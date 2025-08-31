"""Basic integration tests for TrakBridge."""

import pytest
from database import db
from models.stream import Stream
from app import create_app


@pytest.fixture
def app():
    """Create test application."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


def test_health_endpoint_integration(client):
    """Test health endpoint with database integration."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_database_connection(app):
    """Test database connection and basic operations."""
    with app.app_context():
        # Test basic database operations
        stream = Stream(name="Integration Test Stream", plugin_type="garmin")
        db.session.add(stream)
        db.session.commit()

        retrieved = Stream.query.filter_by(name="Integration Test Stream").first()
        assert retrieved is not None
        assert retrieved.name == "Integration Test Stream"
        assert retrieved.plugin_type == "garmin"
