"""Basic unit tests for TrakBridge."""

import pytest
from sqlalchemy import text

from app import create_app
from database import db


class TestBasicFunctionality:
    """Test basic application functionality."""

    def test_app_creation(self):
        """Test that the Flask app can be created."""
        app = create_app("testing")
        assert app is not None
        assert app.config["TESTING"] is True

    def test_health_endpoint(self, client):
        """Test the health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_basic_functionality(self):
        """Test basic application functionality."""
        app = create_app("testing")
        assert app.name == "app"

    def test_database_connection(self, app, db_session):
        """Test database connection."""
        with app.app_context():
            # Test that we can interact with the database
            result = db_session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_app_configuration_loaded(self, app):
        """Test that app configuration is properly loaded."""
        with app.app_context():
            assert app.config.get("SECRET_KEY") is not None
            assert app.config.get("SQLALCHEMY_DATABASE_URI") is not None

    def test_blueprints_loaded(self, app):
        """Test that blueprints are loaded."""
        with app.app_context():
            assert len(app.blueprints) > 0

    def test_error_handlers_registered(self, app):
        """Test that error handlers are registered."""
        with app.app_context():
            assert 404 in app.error_handler_spec[None]
            assert 500 in app.error_handler_spec[None]

    def test_template_context_processors(self, app):
        """Test template context processors."""
        with app.app_context():
            processors = app.template_context_processors[None]
            assert len(processors) > 0

    def test_app_services_initialized(self, app):
        """Test that core services are initialized."""
        with app.app_context():
            assert hasattr(app, "stream_manager")
            assert hasattr(app, "plugin_manager")
            assert hasattr(app, "encryption_service")
            assert hasattr(app, "auth_manager")

    def test_version_info_available(self, app):
        """Test that version information is available."""
        with app.app_context():
            from services.version import get_version

            version = get_version()
            assert version is not None
            assert isinstance(version, str)
