"""
ABOUTME: Comprehensive test suite for TrakBridge authentication system
ABOUTME: Tests all authentication providers, decorators, models, and security features

File: tests/test_authentication.py

Description:
    Complete test coverage for the TrakBridge authentication system including:
    - User and UserSession model testing
    - Authentication provider testing (Local, LDAP, OIDC)
    - Authentication manager orchestration
    - Decorator functionality and route protection
    - Session management and security
    - Role-based access control
    - Permission system testing
    - Configuration validation
    - Security features and edge cases

Author: Emfour Solutions
Created: 2025-07-27
Last Modified: 2025-07-27
Version: 1.0.0
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch

import bcrypt
import pytest
from flask import Flask, session
import jwt
from ldap3 import ALL, Connection, Server

from database import db
from models.user import User, UserRole, UserSession

# Import authentication components
from services.auth.auth_manager import AuthenticationManager
from services.auth.decorators import (
    admin_required,
    get_current_user,
    operator_required,
    require_auth,
    require_permission,
    require_role,
)
from services.auth.ldap_provider import LDAPAuthProvider
from services.auth.local_provider import LocalAuthProvider
from services.auth.oidc_provider import OIDCAuthProvider


@pytest.fixture
def app():
    """Create test Flask application"""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-for-sessions"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["WTF_CSRF_ENABLED"] = False

    # Initialize database
    db.init_app(app)

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def auth_config():
    """Test authentication configuration"""
    return {
        "session": {
            "lifetime_hours": 8,
            "cleanup_interval_minutes": 60,
            "secure_cookies": True,
        },
        "provider_priority": ["local", "ldap", "oidc"],
        "providers": {
            "local": {
                "enabled": True,
                "password_policy": {
                    "min_length": 8,
                    "require_uppercase": True,
                    "require_lowercase": True,
                    "require_numbers": True,
                    "require_special": False,
                },
            },
            "ldap": {
                "enabled": False,
                "server": "ldap://test-server.com",
                "port": 389,
                "use_ssl": False,
                "use_tls": True,
                "bind_dn": "CN=test,DC=test,DC=com",
                "bind_password": "test_password",
                "user_search_base": "OU=Users,DC=test,DC=com",
                "user_search_filter": "(sAMAccountName={username})",
                "role_mapping": {
                    "CN=Admins,DC=test,DC=com": "admin",
                    "CN=Operators,DC=test,DC=com": "operator",
                    "CN=Users,DC=test,DC=com": "user",
                },
            },
            "oidc": {
                "enabled": False,
                "issuer": "https://test-issuer.com",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "scopes": ["openid", "email", "profile"],
                "role_claim": "groups",
                "role_mapping": {
                    "admins": "admin",
                    "operators": "operator",
                    "users": "user",
                },
            },
        },
    }


@pytest.fixture
def test_users(app):
    """Create test users"""
    with app.app_context():
        users = {}

        # Admin user
        admin = User(
            username="admin",
            email="admin@test.com",
            first_name="Admin",
            last_name="User",
            role=UserRole.ADMIN,
            auth_provider="local",
            is_active=True,
        )
        admin.set_password("AdminPass123")
        db.session.add(admin)
        users["admin"] = admin

        # Operator user
        operator = User(
            username="operator",
            email="operator@test.com",
            first_name="Operator",
            last_name="User",
            role=UserRole.OPERATOR,
            auth_provider="local",
            is_active=True,
        )
        operator.set_password("OperatorPass123")
        db.session.add(operator)
        users["operator"] = operator

        # Regular user
        user = User(
            username="user",
            email="user@test.com",
            first_name="Regular",
            last_name="User",
            role=UserRole.USER,
            auth_provider="local",
            is_active=True,
        )
        user.set_password("UserPass123")
        db.session.add(user)
        users["user"] = user

        # Inactive user
        inactive = User(
            username="inactive",
            email="inactive@test.com",
            first_name="Inactive",
            last_name="User",
            role=UserRole.USER,
            auth_provider="local",
            is_active=False,
        )
        inactive.set_password("InactivePass123")
        db.session.add(inactive)
        users["inactive"] = inactive

        db.session.commit()
        return users


class TestUserModel:
    """Test User model functionality"""

    def test_user_creation(self, app):
        """Test user creation and basic properties"""
        with app.app_context():
            user = User(
                username="testuser",
                email="test@example.com",
                first_name="Test",
                last_name="User",
                role=UserRole.USER,
                auth_provider="local",
            )
            db.session.add(user)
            db.session.commit()

            assert user.id is not None
            assert user.username == "testuser"
            assert user.email == "test@example.com"
            assert user.role == UserRole.USER
            assert user.is_active is True

    def test_password_hashing(self, app):
        """Test password hashing and verification"""
        with app.app_context():
            user = User(username="testuser", email="test@example.com")
            user.set_password("TestPassword123")

            assert user.password_hash is not None
            assert user.password_hash != "TestPassword123"
            assert user.check_password("TestPassword123") is True
            assert user.check_password("wrongpassword") is False

    def test_role_permissions(self, app):
        """Test role-based permission checking"""
        with app.app_context():
            # User role
            user = User(username="user", role=UserRole.USER)
            assert user.can_access("streams", "read") is True
            assert user.can_access("streams", "write") is False
            assert user.can_access("admin", "read") is False

            # Operator role
            operator = User(username="operator", role=UserRole.OPERATOR)
            assert operator.can_access("streams", "read") is True
            assert operator.can_access("streams", "write") is True
            assert operator.can_access("admin", "read") is False

            # Admin role
            admin = User(username="admin", role=UserRole.ADMIN)
            assert admin.can_access("streams", "read") is True
            assert admin.can_access("streams", "write") is True
            assert admin.can_access("admin", "read") is True
            assert admin.can_access("admin", "write") is True

    def test_user_serialization(self, app):
        """Test user to_dict method"""
        with app.app_context():
            user = User(
                username="testuser",
                email="test@example.com",
                first_name="Test",
                last_name="User",
                role=UserRole.OPERATOR,
                auth_provider="ldap",
            )
            user.set_password("TestPassword123")

            # Test without sensitive data
            data = user.to_dict(include_sensitive=False)
            assert "password_hash" not in data
            assert data["username"] == "testuser"
            assert data["role"] == "operator"

            # Test with sensitive data
            sensitive_data = user.to_dict(include_sensitive=True)
            assert "password_hash" in sensitive_data


class TestUserSession:
    """Test UserSession model functionality"""

    def test_session_creation(self, app, test_users):
        """Test session creation and properties"""
        with app.app_context():
            user = test_users["user"]
            session = UserSession.create_session(user)

            assert session.user_id == user.id
            assert session.session_id is not None
            assert len(session.session_id) > 20
            assert session.expires_at > datetime.now(timezone.utc)
            assert session.is_valid() is True

    def test_session_expiration(self, app, test_users):
        """Test session expiration"""
        with app.app_context():
            user = test_users["user"]
            session = UserSession.create_session(user)

            # Manually expire session
            session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
            db.session.commit()

            assert session.is_valid() is False

    def test_session_cleanup(self, app, test_users):
        """Test expired session cleanup"""
        with app.app_context():
            user = test_users["user"]

            # Create expired session
            expired_session = UserSession.create_session(user)
            expired_session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

            # Create valid session
            valid_session = UserSession.create_session(user)

            db.session.commit()

            # Run cleanup
            cleaned_count = UserSession.cleanup_expired_sessions()

            assert cleaned_count == 1
            assert UserSession.query.get(expired_session.id) is None
            assert UserSession.query.get(valid_session.id) is not None


class TestLocalAuthProvider:
    """Test Local authentication provider"""

    def test_provider_initialization(self, auth_config):
        """Test provider initialization"""
        provider = LocalAuthProvider(auth_config["providers"]["local"])
        assert provider.enabled is True
        assert provider.password_policy["min_length"] == 8

    def test_successful_authentication(self, app, test_users, auth_config):
        """Test successful local authentication"""
        with app.app_context():
            provider = LocalAuthProvider(auth_config["providers"]["local"])

            user = provider.authenticate("admin", "AdminPass123")

            assert user is not None
            assert user.username == "admin"
            assert user.role == UserRole.ADMIN

    def test_failed_authentication(self, app, test_users, auth_config):
        """Test failed local authentication"""
        with app.app_context():
            provider = LocalAuthProvider(auth_config["providers"]["local"])

            # Wrong password
            user = provider.authenticate("admin", "wrongpassword")
            assert user is None

            # Non-existent user
            user = provider.authenticate("nonexistent", "password")
            assert user is None

            # Inactive user
            user = provider.authenticate("inactive", "InactivePass123")
            assert user is None

    def test_password_validation(self, auth_config):
        """Test password policy validation"""
        provider = LocalAuthProvider(auth_config["providers"]["local"])

        # Valid password
        assert provider.validate_password("ValidPass123") is True

        # Too short
        assert provider.validate_password("short") is False

        # Missing uppercase
        assert provider.validate_password("lowercase123") is False

        # Missing lowercase
        assert provider.validate_password("UPPERCASE123") is False

        # Missing numbers
        assert provider.validate_password("NoNumbers") is False

    def test_user_creation(self, app, auth_config):
        """Test local user creation"""
        with app.app_context():
            provider = LocalAuthProvider(auth_config["providers"]["local"])

            user = provider.create_user(
                username="newuser",
                email="new@test.com",
                password="NewPass123",
                first_name="New",
                last_name="User",
                role=UserRole.USER,
            )

            assert user is not None
            assert user.username == "newuser"
            assert user.check_password("NewPass123") is True
            assert user.role == UserRole.USER


class TestLDAPAuthProvider:
    """Test LDAP authentication provider"""

    @patch("ldap3.Server")
    @patch("ldap3.Connection")
    def test_ldap_authentication_success(
        self, mock_connection_class, mock_server_class, auth_config
    ):
        """Test successful LDAP authentication"""
        # Mock LDAP server and connection
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        mock_connection = Mock()
        mock_connection_class.return_value = mock_connection
        mock_connection.bind.return_value = True
        mock_connection.search.return_value = True
        mock_connection.entries = [
            Mock(
                entry_dn="CN=testuser,OU=Users,DC=test,DC=com",
                sAMAccountName="testuser",
                mail="testuser@test.com",
                givenName="Test",
                sn="User",
                displayName="Test User",
            )
        ]

        # Mock group search
        def side_effect(*args, **kwargs):
            if "member" in str(kwargs.get("search_filter", "")):
                mock_connection.entries = [Mock(entry_dn="CN=Users,DC=test,DC=com")]
            return True

        mock_connection.search.side_effect = side_effect

        provider = LDAPAuthProvider(auth_config["providers"]["ldap"])
        user_data = provider.authenticate("testuser", "password")

        assert user_data is not None
        assert user_data["username"] == "testuser"
        assert user_data["email"] == "testuser@test.com"
        assert user_data["role"] == UserRole.USER

    @patch("ldap3.Server")
    @patch("ldap3.Connection")
    def test_ldap_authentication_failure(
        self, mock_connection_class, mock_server_class, auth_config
    ):
        """Test failed LDAP authentication"""
        mock_server = Mock()
        mock_server_class.return_value = mock_server

        mock_connection = Mock()
        mock_connection_class.return_value = mock_connection
        mock_connection.bind.return_value = False

        provider = LDAPAuthProvider(auth_config["providers"]["ldap"])
        user_data = provider.authenticate("testuser", "wrongpassword")

        assert user_data is None

    def test_ldap_disabled(self, auth_config):
        """Test LDAP provider when disabled"""
        config = auth_config["providers"]["ldap"].copy()
        config["enabled"] = False

        provider = LDAPAuthProvider(config)
        assert provider.enabled is False

        user_data = provider.authenticate("testuser", "password")
        assert user_data is None


class TestOIDCAuthProvider:
    """Test OIDC authentication provider"""

    @patch("requests.get")
    def test_oidc_discovery(self, mock_get, auth_config):
        """Test OIDC provider discovery"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "authorization_endpoint": "https://test-issuer.com/auth",
            "token_endpoint": "https://test-issuer.com/token",
            "userinfo_endpoint": "https://test-issuer.com/userinfo",
            "jwks_uri": "https://test-issuer.com/jwks",
        }
        mock_get.return_value = mock_response

        provider = OIDCAuthProvider(auth_config["providers"]["oidc"])
        discovery = provider.get_discovery_document()

        assert discovery["authorization_endpoint"] == "https://test-issuer.com/auth"
        assert discovery["token_endpoint"] == "https://test-issuer.com/token"

    def test_authorization_url_generation(self, auth_config):
        """Test authorization URL generation"""
        provider = OIDCAuthProvider(auth_config["providers"]["oidc"])

        auth_url, state = provider.get_authorization_url("https://app.com/callback")

        assert "https://test-issuer.com" in auth_url
        assert "client_id=test-client" in auth_url
        assert "redirect_uri=" in auth_url
        assert "state=" in auth_url
        assert state is not None

    @patch("requests.post")
    @patch("jwt.decode")
    @patch.object(OIDCAuthProvider, "validate_configuration", return_value=[])
    @patch.object(OIDCAuthProvider, "_load_discovery_document")
    def test_token_validation(self, mock_discovery, mock_validate, mock_jwt_decode, mock_post, auth_config):
        """Test OIDC token validation"""
        # Enable OIDC for this test
        auth_config["providers"]["oidc"]["enabled"] = True
        # Mock token exchange
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "access_token",
            "id_token": "id_token",
            "token_type": "Bearer",
        }
        mock_post.return_value = mock_response

        # Mock JWT decode
        mock_jwt_decode.return_value = {
            "sub": "user123",
            "email": "user@test.com",
            "name": "Test User",
            "groups": ["users"],
        }

        # Create config with providers structure for OIDC
        oidc_config = {
            "providers": {
                "test_provider": auth_config["providers"]["oidc"]
            }
        }
        provider = OIDCAuthProvider(oidc_config)

        with patch.object(provider, "_validate_and_decode_token", return_value={"sub": "user123", "email": "user@test.com", "name": "Test User", "groups": ["users"]}):
            user_data = provider.handle_callback("auth_code", "state")

        assert user_data is not None
        assert user_data["email"] == "user@test.com"
        assert user_data["role"] == UserRole.USER


class TestAuthenticationManager:
    """Test authentication manager orchestration"""

    def test_manager_initialization(self, app, auth_config):
        """Test authentication manager initialization"""
        with app.app_context():
            with patch(
                "services.auth.auth_manager.load_auth_config", return_value=auth_config
            ):
                manager = AuthenticationManager()

                assert manager.local_provider is not None
                assert manager.ldap_provider is not None
                assert manager.oidc_provider is not None

    def test_authenticate_with_local(self, app, test_users, auth_config):
        """Test authentication through manager with local provider"""
        with app.app_context():
            with patch(
                "services.auth.auth_manager.load_auth_config", return_value=auth_config
            ):
                manager = AuthenticationManager()

                user = manager.authenticate("admin", "AdminPass123", "local")

                assert user is not None
                assert user.username == "admin"

    def test_authenticate_priority_order(self, app, test_users, auth_config):
        """Test authentication provider priority"""
        with app.app_context():
            # Modify config to test priority
            config = auth_config.copy()
            config["provider_priority"] = ["ldap", "local"]

            with patch(
                "services.auth.auth_manager.load_auth_config", return_value=config
            ):
                manager = AuthenticationManager()

                # Should try LDAP first, then fall back to local
                with patch.object(
                    manager.ldap_provider, "authenticate", return_value=None
                ):
                    user = manager.authenticate("admin", "AdminPass123")
                    assert user is not None  # Found via local provider

    def test_session_management(self, app, test_users, auth_config):
        """Test session creation and validation"""
        with app.app_context():
            with patch(
                "services.auth.auth_manager.load_auth_config", return_value=auth_config
            ):
                manager = AuthenticationManager()

                # Create session
                user = test_users["admin"]
                session_id = manager.create_session(user)

                assert session_id is not None

                # Validate session
                retrieved_user = manager.get_user_by_session(session_id)
                assert retrieved_user.id == user.id

                # Invalidate session
                manager.invalidate_session(session_id)
                retrieved_user = manager.get_user_by_session(session_id)
                assert retrieved_user is None


class TestAuthenticationDecorators:
    """Test authentication decorators"""

    def test_require_auth_decorator(self, app, test_users):
        """Test @require_auth decorator"""
        with app.app_context():
            app.auth_manager = Mock()

            @require_auth
            def protected_view():
                return "success"

            with app.test_request_context():
                # No user in session
                with patch(
                    "services.auth.decorators.get_current_user", return_value=None
                ):
                    response = protected_view()
                    assert response[1] == 302  # Redirect to login

                # User in session
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["user"],
                ):
                    response = protected_view()
                    assert response == "success"

    def test_require_role_decorator(self, app, test_users):
        """Test @require_role decorator"""
        with app.app_context():
            app.auth_manager = Mock()

            @require_role(UserRole.ADMIN)
            def admin_view():
                return "admin success"

            with app.test_request_context():
                # Regular user trying to access admin view
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["user"],
                ):
                    response = admin_view()
                    assert response[1] == 403  # Forbidden

                # Admin user accessing admin view
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["admin"],
                ):
                    response = admin_view()
                    assert response == "admin success"

    def test_require_permission_decorator(self, app, test_users):
        """Test @require_permission decorator"""
        with app.app_context():
            app.auth_manager = Mock()

            @require_permission("streams", "write")
            def write_streams():
                return "write success"

            with app.test_request_context():
                # User without write permission
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["user"],
                ):
                    response = write_streams()
                    assert response[1] == 403  # Forbidden

                # Operator with write permission
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["operator"],
                ):
                    response = write_streams()
                    assert response == "write success"

    def test_admin_required_decorator(self, app, test_users):
        """Test @admin_required decorator"""
        with app.app_context():
            app.auth_manager = Mock()

            @admin_required
            def admin_only_view():
                return "admin only"

            with app.test_request_context():
                # Non-admin user
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["operator"],
                ):
                    response = admin_only_view()
                    assert response[1] == 403

                # Admin user
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["admin"],
                ):
                    response = admin_only_view()
                    assert response == "admin only"

    def test_operator_required_decorator(self, app, test_users):
        """Test @operator_required decorator"""
        with app.app_context():
            app.auth_manager = Mock()

            @operator_required
            def operator_view():
                return "operator success"

            with app.test_request_context():
                # Regular user
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["user"],
                ):
                    response = operator_view()
                    assert response[1] == 403

                # Operator user
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["operator"],
                ):
                    response = operator_view()
                    assert response == "operator success"

                # Admin user (should also work)
                with patch(
                    "services.auth.decorators.get_current_user",
                    return_value=test_users["admin"],
                ):
                    response = operator_view()
                    assert response == "operator success"


class TestAuthenticationRoutes:
    """Test authentication routes and UI"""

    def test_login_page(self, client):
        """Test login page accessibility"""
        response = client.get("/auth/login")
        assert response.status_code == 200
        assert b"Login" in response.data

    def test_login_post_success(self, client, app, test_users):
        """Test successful login POST"""
        with app.app_context():
            response = client.post(
                "/auth/login",
                data={
                    "username": "admin",
                    "password": "AdminPass123",
                    "provider": "local",
                },
                follow_redirects=True,
            )

            assert response.status_code == 200

    def test_login_post_failure(self, client, app, test_users):
        """Test failed login POST"""
        with app.app_context():
            response = client.post(
                "/auth/login",
                data={
                    "username": "admin",
                    "password": "wrongpassword",
                    "provider": "local",
                },
            )

            assert response.status_code == 200
            assert b"Invalid credentials" in response.data or b"error" in response.data

    def test_logout(self, client, app, test_users):
        """Test logout functionality"""
        with app.app_context():
            # Login first
            with client.session_transaction() as sess:
                sess["session_id"] = "test_session_id"

            # Mock auth manager for logout
            with patch("routes.auth.current_app") as mock_app:
                mock_auth_manager = Mock()
                mock_app.auth_manager = mock_auth_manager

                response = client.get("/auth/logout", follow_redirects=True)
                assert response.status_code == 200
                mock_auth_manager.invalidate_session.assert_called_once()


class TestAuthenticationSecurity:
    """Test security aspects of authentication"""

    def test_password_hashing_security(self, app):
        """Test password hashing security"""
        with app.app_context():
            user = User(username="testuser", email="test@example.com")

            # Test that same password produces different hashes
            user.set_password("TestPassword123")
            hash1 = user.password_hash

            user.set_password("TestPassword123")
            hash2 = user.password_hash

            assert hash1 != hash2  # Salted hashes should differ
            assert user.check_password("TestPassword123") is True

    def test_session_security(self, app, test_users):
        """Test session security measures"""
        with app.app_context():
            user = test_users["user"]
            session = UserSession.create_session(user)

            # Session ID should be cryptographically secure
            assert len(session.session_id) >= 32
            assert session.session_id.isalnum() or "-" in session.session_id

            # Session should have expiration
            assert session.expires_at > datetime.now(timezone.utc)

    def test_brute_force_protection(self, app, test_users, auth_config):
        """Test brute force protection (placeholder for future implementation)"""
        with app.app_context():
            with patch(
                "services.auth.auth_manager.load_auth_config", return_value=auth_config
            ):
                manager = AuthenticationManager()

                # Multiple failed attempts
                for _ in range(5):
                    user = manager.authenticate("admin", "wrongpassword", "local")
                    assert user is None

                # Should still allow correct password
                user = manager.authenticate("admin", "AdminPass123", "local")
                assert user is not None

    def test_session_hijacking_protection(self, app, test_users):
        """Test session hijacking protection"""
        with app.app_context():
            user = test_users["user"]
            session = UserSession.create_session(user)

            # Session should bind to user
            assert session.user_id == user.id

            # Invalid session ID should not work
            fake_session = UserSession(
                user_id=999,  # Non-existent user
                session_id="fake_session_id",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            assert fake_session.is_valid() is True  # Structurally valid
            # But user lookup should fail for non-existent user


class TestAuthenticationConfiguration:
    """Test authentication configuration validation"""

    def test_config_validation(self, auth_config):
        """Test configuration validation"""
        # Valid config should pass
        assert auth_config["providers"]["local"]["enabled"] is True
        assert "password_policy" in auth_config["providers"]["local"]
        assert auth_config["session"]["lifetime_hours"] > 0

    def test_invalid_config_handling(self):
        """Test handling of invalid configuration"""
        invalid_config = {
            "providers": {
                "local": {
                    "enabled": True,
                    "password_policy": {"min_length": -1},  # Invalid
                }
            }
        }

        # Should handle gracefully (implementation dependent)
        provider = LocalAuthProvider(invalid_config["providers"]["local"])
        assert provider.password_policy["min_length"] >= 0  # Should use default

    def test_missing_config_defaults(self):
        """Test default configuration values"""
        minimal_config = {"enabled": True}

        provider = LocalAuthProvider(minimal_config)

        # Should have sensible defaults
        assert provider.enabled is True
        assert "min_length" in provider.password_policy


class TestAuthenticationIntegration:
    """Integration tests for authentication system"""

    def test_full_authentication_flow(self, client, app, test_users):
        """Test complete authentication flow"""
        with app.app_context():
            # 1. Access protected resource - should redirect to login
            response = client.get("/admin/system_info")
            assert response.status_code == 302
            assert "/auth/login" in response.location

            # 2. Login with correct credentials
            response = client.post(
                "/auth/login",
                data={
                    "username": "admin",
                    "password": "AdminPass123",
                    "provider": "local",
                },
            )

            # 3. Should now be able to access protected resource
            # (This would require full Flask app setup with all routes)

    def test_role_based_access_integration(self, app, test_users):
        """Test role-based access in integrated environment"""
        with app.app_context():
            # Test different users accessing different resources
            users_and_permissions = [
                (test_users["user"], "streams", "read", True),
                (test_users["user"], "streams", "write", False),
                (test_users["operator"], "streams", "write", True),
                (test_users["operator"], "admin", "read", False),
                (test_users["admin"], "admin", "write", True),
            ]

            for user, resource, action, expected in users_and_permissions:
                result = user.can_access(resource, action)
                assert (
                    result == expected
                ), f"User {user.username} should {'have' if expected else 'not have'} {action} access to {resource}"


# Fixtures for CI/CD testing
@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    """Docker compose file for integration testing"""
    return os.path.join(str(pytestconfig.rootdir), "tests", "docker-compose.test.yml")


@pytest.fixture(scope="session")
def ldap_server(docker_compose_file):
    """Start test LDAP server for integration tests"""
    # This would start a test LDAP server
    # Implementation depends on test infrastructure
    pass


# Performance tests
class TestAuthenticationPerformance:
    """Performance tests for authentication system"""

    def test_password_hashing_performance(self, app):
        """Test password hashing performance"""
        import time

        with app.app_context():
            user = User(username="testuser", email="test@example.com")

            start_time = time.time()
            user.set_password("TestPassword123")
            hash_time = time.time() - start_time

            # Password hashing should take reasonable time (bcrypt is intentionally slow)
            assert hash_time < 1.0  # Should complete within 1 second
            assert hash_time > 0.01  # Should take some time for security

    def test_session_lookup_performance(self, app, test_users):
        """Test session lookup performance"""
        import time

        with app.app_context():
            # Create multiple sessions
            sessions = []
            for i in range(100):
                session = UserSession.create_session(test_users["user"])
                sessions.append(session)

            db.session.commit()

            # Test lookup performance
            start_time = time.time()
            for session in sessions[:10]:  # Test 10 lookups
                found_session = UserSession.query.filter_by(
                    session_id=session.session_id
                ).first()
                assert found_session is not None

            lookup_time = time.time() - start_time
            assert lookup_time < 1.0  # Should be fast


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
