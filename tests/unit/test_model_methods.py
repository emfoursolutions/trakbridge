"""
ABOUTME: Comprehensive tests for standardized model methods and validation patterns
ABOUTME: Tests consistent to_dict behavior, validation patterns, and common model functionality

TDD Tests for Phase 4: Model Method Standardization
These tests define the expected behavior for standardized model methods,
consistent validation patterns, and common functionality across all models.

Author: Emfour Solutions
Created: 2025-09-04
"""

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

from database import db
from models.callsign_mapping import CallsignMapping
from models.stream import Stream
from models.tak_server import TakServer
from models.user import AccountStatus, AuthProvider, User, UserRole, UserSession


class TestStandardizedModelMethods:
    """Test standardized methods across all models."""

    def test_all_models_have_standardized_to_dict_signature(self, app, db_session):
        """Test that all models have consistent to_dict method signatures."""
        with app.app_context():
            # Create test instances
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=server.id
            )
            db_session.add(stream)
            db_session.flush()

            user = User.create_local_user(
                username="testuser", password="pass123", email="test@example.com"
            )
            db_session.add(user)
            db_session.flush()

            session = UserSession.create_session(user=user)
            db_session.add(session)
            db_session.flush()

            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="IMEI123",
                custom_callsign="Alpha1",
            )
            db_session.add(mapping)
            db_session.commit()

            # Test that all models support to_dict() with no arguments
            models_to_test = [server, stream, user, session, mapping]

            for model in models_to_test:
                # Should not raise an exception
                result = model.to_dict()
                assert isinstance(
                    result, dict
                ), f"{model.__class__.__name__}.to_dict() should return dict"

                # Should contain basic fields that all models should have
                assert (
                    "id" in result
                ), f"{model.__class__.__name__}.to_dict() missing 'id' field"
                assert (
                    "created_at" in result
                ), f"{model.__class__.__name__}.to_dict() missing 'created_at' field"
                assert (
                    "updated_at" in result
                ), f"{model.__class__.__name__}.to_dict() missing 'updated_at' field"

    def test_to_dict_include_sensitive_parameter_consistency(self, app, db_session):
        """Test that models consistently handle include_sensitive parameter."""
        with app.app_context():
            # Create user with sensitive data
            user = User.create_local_user(
                username="testuser", password="secret123", email="test@example.com"
            )
            db_session.add(user)

            # Create stream with potentially sensitive config
            stream = Stream(name="Test Stream", plugin_type="garmin")
            stream.set_plugin_config(
                {
                    "url": "https://share.garmin.com/Feed/Share/12345",
                    "username": "testuser",
                    "password": "secret_password",
                    "hide_inactive_devices": True,
                }
            )
            db_session.add(stream)
            db_session.commit()

            # Test User model - should support include_sensitive parameter
            user_dict_safe = user.to_dict(include_sensitive=False)
            user_dict_full = user.to_dict(include_sensitive=True)

            # Password hash should never be serialized for security reasons
            assert (
                "password_hash" not in user_dict_safe
            ), "Safe dict should not include password_hash"
            assert (
                "password_hash" not in user_dict_full
            ), "Password hash should never be serialized for security"

            # Test Stream model - should support include_sensitive parameter
            stream_dict_safe = stream.to_dict(include_sensitive=False)
            stream_dict_full = stream.to_dict(include_sensitive=True)

            # Plugin config should be masked in safe version, full in sensitive version
            safe_config_str = str(stream_dict_safe.get("plugin_config", {}))
            full_config_str = str(stream_dict_full.get("plugin_config", {}))

            assert (
                "••••••••" in safe_config_str
            ), "Safe dict should mask sensitive config values"

            # In sensitive mode, should either show decrypted value OR encrypted value (if decryption fails in CI)
            # The key test is that it's different from the masked version and contains some form of the password
            assert (
                safe_config_str != full_config_str
            ), "Full dict should differ from safe dict"
            assert (
                "secret_password" in full_config_str or "ENC:v1:" in full_config_str
            ), "Full dict should include either decrypted password or encrypted value"

    def test_standardized_model_repr_methods(self, app, db_session):
        """Test that all models have consistent and informative __repr__ methods."""
        with app.app_context():
            # Create test instances
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            stream = Stream(name="Test Stream", plugin_type="garmin")
            user = User.create_local_user(username="testuser", password="pass123")
            mapping = CallsignMapping(
                stream_id=1, identifier_value="IMEI123", custom_callsign="Alpha1"
            )

            models_to_test = [
                (server, "TakServer", "Test Server"),
                (stream, "Stream", "Test Stream"),
                (user, "User", "testuser"),
                (mapping, "CallsignMapping", "IMEI123"),
            ]

            for model, class_name, identifier in models_to_test:
                repr_str = repr(model)

                # Should include class name and key identifier
                # This will fail initially until all models have consistent __repr__
                assert (
                    class_name in repr_str
                ), f"__repr__ should include class name {class_name}"
                assert (
                    identifier in repr_str
                ), f"__repr__ should include identifier {identifier}"
                assert repr_str.startswith("<"), "__repr__ should start with '<'"
                assert repr_str.endswith(">"), "__repr__ should end with '>'"

    def test_standardized_validation_methods(self, app, db_session):
        """Test that models have consistent validation patterns."""
        with app.app_context():
            # Test User validation methods exist and work consistently
            user = User.create_local_user(username="testuser", password="pass123")

            # These methods should exist and work consistently across models
            validation_methods = [
                "is_active",
                "is_locked",
            ]  # Common validation patterns

            for method_name in validation_methods:
                if hasattr(user, method_name):
                    method = getattr(user, method_name)
                    result = method()
                    # Should return boolean
                    assert isinstance(
                        result, bool
                    ), f"{method_name}() should return boolean"

            # Test Stream validation - should have status property
            stream = Stream(name="Test Stream", plugin_type="garmin", is_active=True)

            # Stream should have consistent status reporting
            # This will fail initially until status property is standardized
            assert hasattr(stream, "status"), "Stream should have status property"
            assert stream.status in [
                "active",
                "inactive",
                "error",
            ], f"Stream status should be standard value, got: {stream.status}"

    def test_common_field_patterns_across_models(self, app, db_session):
        """Test that models follow common field patterns consistently."""
        with app.app_context():
            # Create instances of all models
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=server.id
            )
            db_session.add(stream)
            db_session.flush()

            user = User.create_local_user(username="testuser", password="pass123")
            db_session.add(user)
            db_session.flush()

            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="IMEI123",
                custom_callsign="Alpha1",
            )
            db_session.add(mapping)
            db_session.commit()

            models_to_test = [server, stream, user, mapping]

            # Test that all models have TimestampMixin fields
            for model in models_to_test:
                assert hasattr(
                    model, "created_at"
                ), f"{model.__class__.__name__} missing created_at"
                assert hasattr(
                    model, "updated_at"
                ), f"{model.__class__.__name__} missing updated_at"

                # Timestamps should be datetime objects
                assert isinstance(
                    model.created_at, datetime
                ), "created_at should be datetime"
                assert isinstance(
                    model.updated_at, datetime
                ), "updated_at should be datetime"

                # Timestamps should be timezone-aware (UTC)
                assert (
                    model.created_at.tzinfo is not None
                ), "created_at should be timezone-aware"
                assert (
                    model.updated_at.tzinfo is not None
                ), "updated_at should be timezone-aware"


class TestModelValidationPatterns:
    """Test consistent validation patterns across models."""

    def test_password_handling_standardization(self, app, db_session):
        """Test that password handling is standardized across models that need it."""
        with app.app_context():
            # User model password handling
            user = User.create_local_user(username="testuser", password="secret123")

            # Should have standardized password methods
            assert hasattr(user, "set_password"), "User should have set_password method"
            assert hasattr(
                user, "check_password"
            ), "User should have check_password method"

            # Test password validation
            assert user.check_password("secret123"), "Should validate correct password"
            assert not user.check_password("wrong"), "Should reject wrong password"

            # TakServer certificate password handling
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )

            # Should have standardized password methods for certificate
            assert hasattr(
                server, "set_cert_password"
            ), "TakServer should have set_cert_password method"
            assert hasattr(
                server, "get_cert_password"
            ), "TakServer should have get_cert_password method"
            assert hasattr(
                server, "has_cert_password"
            ), "TakServer should have has_cert_password method"

            # Test certificate password handling
            server.set_cert_password("cert_pass")
            assert server.has_cert_password(), "Should detect password is set"
            assert (
                server.get_cert_password() == "cert_pass"
            ), "Should return decrypted password"

    def test_configuration_handling_standardization(self, app, db_session):
        """Test that configuration handling is standardized."""
        with app.app_context():
            # Stream plugin configuration
            stream = Stream(name="Test Stream", plugin_type="garmin")

            # Should have standardized config methods
            config_methods = [
                "get_plugin_config",
                "set_plugin_config",
                "get_raw_plugin_config",
            ]
            for method_name in config_methods:
                assert hasattr(
                    stream, method_name
                ), f"Stream should have {method_name} method"

            # Test configuration handling
            test_config = {"api_key": "secret", "feed_id": "123", "interval": 60}
            stream.set_plugin_config(test_config)

            retrieved_config = stream.get_plugin_config()
            assert retrieved_config == test_config, "Config should round-trip correctly"

            # Raw config should handle encryption status
            assert hasattr(
                stream, "is_field_encrypted"
            ), "Stream should have is_field_encrypted method"

    def test_relationship_access_patterns(self, app, db_session):
        """Test that relationship access follows consistent patterns."""
        with app.app_context():
            # Create related objects
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            stream = Stream(
                name="Test Stream", plugin_type="garmin", tak_server_id=server.id
            )
            db_session.add(stream)
            db_session.flush()

            user = User.create_local_user(username="testuser", password="pass123")
            db_session.add(user)
            db_session.flush()

            session = UserSession.create_session(user=user)
            db_session.add(session)
            db_session.commit()

            # Test forward relationships
            assert (
                stream.tak_server is not None
            ), "Stream should have tak_server relationship"
            assert (
                stream.tak_server.id == server.id
            ), "Relationship should be correctly linked"

            assert session.user is not None, "UserSession should have user relationship"
            assert session.user.id == user.id, "Relationship should be correctly linked"

            # Test reverse relationships - these will fail initially if not properly configured
            assert (
                len(server.streams) > 0
            ), "TakServer should have reverse streams relationship"
            assert (
                stream in server.streams
            ), "Stream should be in server's streams collection"

            assert (
                len(user.sessions) > 0
            ), "User should have reverse sessions relationship"
            assert (
                session in user.sessions
            ), "Session should be in user's sessions collection"

    def test_model_factory_methods_standardization(self, app, db_session):
        """Test that models have consistent factory/creation methods."""
        with app.app_context():
            # User model should have standardized creation methods
            user_methods = ["create_local_user", "create_external_user"]
            for method_name in user_methods:
                assert hasattr(
                    User, method_name
                ), f"User should have {method_name} class method"

            # Test factory methods work
            local_user = User.create_local_user(
                username="local_user", password="pass123", email="local@example.com"
            )
            assert local_user.auth_provider == AuthProvider.LOCAL
            assert local_user.username == "local_user"

            # Save user to database before creating session
            db_session.add(local_user)
            db_session.flush()  # Get ID but don't commit yet

            external_user = User.create_external_user(
                username="external_user",
                provider=AuthProvider.OIDC,
                provider_user_id="oidc_123",
            )
            assert external_user.auth_provider == AuthProvider.OIDC
            assert external_user.provider_user_id == "oidc_123"

            # UserSession should have standardized creation
            assert hasattr(
                UserSession, "create_session"
            ), "UserSession should have create_session method"

            session = UserSession.create_session(
                user=local_user, ip_address="192.168.1.1", user_agent="TestAgent"
            )
            # Add session to database session so relationships can be resolved
            db_session.add(session)
            db_session.flush()

            assert session.user == local_user
            assert session.ip_address == "192.168.1.1"


class TestModelErrorHandling:
    """Test consistent error handling patterns across models."""

    def test_standardized_exception_handling(self, app, db_session):
        """Test that models handle exceptions consistently."""
        with app.app_context():
            # Test Stream configuration errors
            stream = Stream(name="Test Stream", plugin_type="garmin")

            # Should handle invalid configuration gracefully
            try:
                stream.set_plugin_config("invalid_config")  # String instead of dict
                assert False, "Should raise ValueError for invalid config"
            except ValueError as e:
                # Should have descriptive error message
                assert (
                    "dictionary" in str(e).lower()
                ), "Error should mention expected type"

            # Test empty/None configuration handling
            stream.set_plugin_config(None)
            config = stream.get_plugin_config()
            assert config == {}, "None config should return empty dict"

            # Test User password validation errors
            user = User.create_local_user(username="testuser", password="pass123")

            # Should handle invalid password operations
            user.auth_provider = AuthProvider.OIDC  # Change to external provider

            try:
                user.set_password("newpass")
                assert (
                    False
                ), "Should raise ValueError for external provider password set"
            except ValueError as e:
                assert (
                    "local authentication" in str(e).lower()
                ), "Error should mention provider restriction"

    def test_graceful_degradation_patterns(self, app, db_session):
        """Test that models degrade gracefully when data is missing or corrupt."""
        with app.app_context():
            # Test Stream with missing plugin config
            stream = Stream(name="Test Stream", plugin_type="garmin")
            stream.plugin_config = None

            config = stream.get_plugin_config()
            assert config == {}, "Missing config should return empty dict, not None"

            # Test with corrupted JSON config
            stream.plugin_config = "{'invalid': json}"
            config = stream.get_plugin_config()
            assert (
                config == {}
            ), "Corrupted config should return empty dict, not raise exception"

            # Test TakServer with missing certificate password
            server = TakServer(
                name="Test Server", host="localhost", port=8089, protocol="tls"
            )

            password = server.get_cert_password()
            assert (
                password == ""
            ), "Missing password should return empty string, not None"
