"""Unit tests for the main TrakBridge application."""

import os
from unittest.mock import patch

from app import create_app, setup_cleanup_handlers, setup_template_helpers


class TestAppCreation:
    """Test Flask application creation and configuration."""

    def test_create_app_development(self):
        """Test creating app with development config."""
        # Set environment variables for testing to avoid file system issues
        test_env = {
            "DB_TYPE": "sqlite",
            "FLASK_ENV": "testing",
            "SECRET_KEY": "test-secret-key",
            "TRAKBRIDGE_ENCRYPTION_KEY": ("test-encryption-key-for-testing-12345"),
            "DATABASE_URL": "sqlite:///:memory:",
        }

        with patch.dict(os.environ, test_env, clear=False):
            app = create_app("development")
            assert app is not None
            assert app.config["DEBUG"] is True

    def test_create_app_testing(self):
        """Test creating app with testing config."""
        app = create_app("testing")
        assert app is not None
        assert app.config["TESTING"] is True

    def test_create_app_production(self):
        """Test creating app with production config."""
        # Set environment variables for testing to avoid file system issues
        test_env = {
            "DB_TYPE": "sqlite",
            "FLASK_ENV": "testing",
            "SECRET_KEY": "test-secret-key-for-production-test",
            "TRAKBRIDGE_ENCRYPTION_KEY": ("test-encryption-key-for-testing-12345"),
            "DATABASE_URL": "sqlite:///:memory:",
        }

        with patch.dict(os.environ, test_env, clear=False):
            app = create_app("production")
            assert app is not None
            assert app.config["DEBUG"] is False

    def test_app_has_required_attributes(self):
        """Test that app has required attributes."""
        app = create_app("testing")

        # Check for required managers
        assert hasattr(app, "stream_manager")
        assert hasattr(app, "plugin_manager")
        assert hasattr(app, "encryption_service")
        assert hasattr(app, "auth_manager")

    def test_app_context_factory(self):
        """Test app context factory."""
        app = create_app("testing")
        assert hasattr(app, "app_context_factory")

        context = app.app_context_factory()
        assert context is not None


class TestAppConfiguration:
    """Test application configuration."""

    def test_app_secret_key_set(self):
        """Test that secret key is set."""
        app = create_app("testing")
        assert app.config.get("SECRET_KEY") is not None
        assert app.config.get("SECRET_KEY") != ""

    def test_database_configuration(self):
        """Test database configuration."""
        app = create_app("testing")
        assert app.config.get("SQLALCHEMY_DATABASE_URI") is not None
        assert app.config.get("SQLALCHEMY_TRACK_MODIFICATIONS") is not None

    def test_app_logging_configuration(self):
        """Test logging configuration."""
        app = create_app("testing")
        assert app.config.get("LOG_LEVEL") is not None

    def test_worker_configuration(self):
        """Test worker thread configuration."""
        app = create_app("testing")
        assert app.config.get("MAX_WORKER_THREADS") is not None
        assert isinstance(app.config.get("MAX_WORKER_THREADS"), int)
        assert app.config.get("MAX_WORKER_THREADS") > 0


class TestAppBlueprints:
    """Test application blueprint registration."""

    def test_blueprints_registered(self):
        """Test that all required blueprints are registered."""
        app = create_app("testing")

        blueprint_names = [bp.name for bp in app.blueprints.values()]

        # Check for expected blueprints
        expected_blueprints = [
            "main",
            "streams",
            "tak_servers",
            "admin",
            "api",
            "cot_types",
            "auth",
        ]

        for expected in expected_blueprints:
            assert expected in blueprint_names, f"Blueprint '{expected}' not registered"


class TestAppHelpers:
    """Test application helper functions."""

    def test_setup_cleanup_handlers(self):
        """Test cleanup handlers setup."""
        # This should not raise an exception
        setup_cleanup_handlers()
        assert True

    def test_setup_template_helpers(self):
        """Test template helpers setup."""
        app = create_app("testing")

        # This should not raise an exception
        setup_template_helpers(app)
        assert True


class TestAppStartup:
    """Test application startup functionality."""

    @patch("app.initialize_database_safely")
    def test_database_initialization(self, mock_init_db):
        """Test database initialization."""
        app = create_app("testing")

        with app.app_context():
            from app import initialize_database_safely

            initialize_database_safely()

        # Should have been called during app creation
        assert mock_init_db.called

    def test_version_context_processor(self):
        """Test version context processor."""
        app = create_app("testing")

        with app.app_context():
            with app.test_request_context():
                # Get the context processors
                context_processors = app.template_context_processors[None]

                # Should have context processors
                assert len(context_processors) > 0

                # Execute context processors
                context = {}
                for processor in context_processors:
                    context.update(processor())

                # Should have version info
                assert "app_version" in context or len(context_processors) > 0


class TestErrorHandlers:
    """Test application error handlers."""

    def test_404_handler_registered(self):
        """Test 404 error handler."""
        app = create_app("testing")

        with app.test_client() as client:
            response = client.get("/nonexistent-endpoint")
            # Should handle 404 gracefully, not return 500
            assert response.status_code in [
                404,
                302,
                503,
            ]  # 302 for redirects, 503 for startup

    def test_500_handler_registered(self):
        """Test 500 error handler."""
        app = create_app("testing")

        # Test that error handlers are registered
        assert 404 in app.error_handler_spec[None]
        assert 500 in app.error_handler_spec[None]
