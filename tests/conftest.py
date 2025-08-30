"""
ABOUTME: Pytest configuration and shared fixtures for TrakBridge authentication tests
ABOUTME: Provides database setup, test client configuration, and authentication utilities

File: tests/conftest.py

Description:
    Central pytest configuration file that provides shared fixtures and utilities
    for testing the TrakBridge authentication system. Includes database setup,
    Flask test client configuration, mock services, and authentication helpers.

Author: Emfour Solutions
Created: 2025-07-27
Last Modified: 2025-07-27
Version: 1.0.0
"""

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from flask import Flask

# Import application components
from database import db
from models.user import AuthProvider, User, UserRole, UserSession
from services.auth.auth_manager import AuthenticationManager


@pytest.fixture(scope="session")
def app():
    """Create test Flask application using the actual app factory"""
    # Import here to avoid circular imports
    from app import create_app

    # Set environment variables for clean testing
    original_env = {}
    test_env_vars = {
        "FLASK_ENV": "testing",
        "DB_TYPE": "sqlite",
        "TRAKBRIDGE_ENCRYPTION_KEY": "test-encryption-key-for-testing-12345",
        "SECRET_KEY": "test-secret-key-for-sessions",
    }

    # Save original values and set test values
    for key, value in test_env_vars.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        # Create app using the testing configuration
        app = create_app("testing")

        with app.app_context():
            yield app
    finally:
        # Restore original environment variables
        for key, original_value in original_env.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def db_session(app):
    """Create database session for tests"""
    with app.app_context():
        # Create tables
        db.create_all()

        # Provide the session
        yield db.session

        # Cleanup
        db.session.rollback()
        db.session.remove()


@pytest.fixture
def auth_manager(app):
    """Create authentication manager with test configuration"""
    with app.app_context():
        # Mock configuration loading
        test_config = {
            "session": {
                "lifetime_hours": 8,
                "cleanup_interval_minutes": 60,
                "secure_cookies": False,  # For testing
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

        with patch(
            "services.auth.auth_manager.load_auth_config", return_value=test_config
        ):
            manager = AuthenticationManager()
            yield manager


@pytest.fixture
def test_users(app, db_session):
    """Create test users for authentication tests"""
    users = {}

    # Admin user
    admin = User(
        username="admin",
        email="admin@test.com",
        full_name="Admin User",
        role=UserRole.ADMIN,
        auth_provider=AuthProvider.LOCAL,
    )
    admin.set_password("AdminPass123")
    db_session.add(admin)
    users["admin"] = admin

    # Operator user
    operator = User(
        username="operator",
        email="operator@test.com",
        full_name="Operator User",
        role=UserRole.OPERATOR,
        auth_provider=AuthProvider.LOCAL,
    )
    operator.set_password("OperatorPass123")
    db_session.add(operator)
    users["operator"] = operator

    # Regular user
    user = User(
        username="user",
        email="user@test.com",
        full_name="Regular User",
        role=UserRole.USER,
        auth_provider=AuthProvider.LOCAL,
    )
    user.set_password("UserPass123")
    db_session.add(user)
    users["user"] = user

    # Inactive user
    inactive = User(
        username="inactive",
        email="inactive@test.com",
        full_name="Inactive User",
        role=UserRole.USER,
        auth_provider=AuthProvider.LOCAL,
    )
    # Set status to inactive instead of using is_active
    from models.user import AccountStatus

    inactive.status = AccountStatus.DISABLED
    inactive.set_password("InactivePass123")
    db_session.add(inactive)
    users["inactive"] = inactive

    # LDAP user
    ldap_user = User(
        username="ldapuser",
        email="ldapuser@test.com",
        full_name="LDAP User",
        role=UserRole.USER,
        auth_provider=AuthProvider.LDAP,
    )
    db_session.add(ldap_user)
    users["ldap_user"] = ldap_user

    # OIDC user
    oidc_user = User(
        username="oidcuser",
        email="oidcuser@test.com",
        full_name="OIDC User",
        role=UserRole.OPERATOR,
        auth_provider=AuthProvider.OIDC,
    )
    db_session.add(oidc_user)
    users["oidc_user"] = oidc_user

    db_session.commit()
    return users


@pytest.fixture
def test_sessions(app, db_session, test_users):
    """Create test sessions"""
    sessions = {}

    # Active session for admin
    admin_session = UserSession.create_session(test_users["admin"])
    sessions["admin"] = admin_session

    # Active session for regular user
    user_session = UserSession.create_session(test_users["user"])
    sessions["user"] = user_session

    # Expired session
    expired_session = UserSession.create_session(test_users["operator"])
    expired_session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    sessions["expired"] = expired_session

    db_session.commit()
    return sessions


@pytest.fixture
def mock_ldap_connection():
    """Mock LDAP connection for testing"""
    with (
        patch("ldap3.Server") as mock_server,
        patch("ldap3.Connection") as mock_connection,
    ):

        # Configure mocks
        mock_server_instance = Mock()
        mock_server.return_value = mock_server_instance

        mock_conn_instance = Mock()
        mock_connection.return_value = mock_conn_instance

        # Default successful responses
        mock_conn_instance.bind.return_value = True
        mock_conn_instance.search.return_value = True
        mock_conn_instance.entries = [
            Mock(
                entry_dn="CN=testuser,OU=Users,DC=test,DC=com",
                sAMAccountName="testuser",
                mail="testuser@test.com",
                givenName="Test",
                sn="User",
                displayName="Test User",
            )
        ]

        yield {
            "server": mock_server,
            "connection": mock_connection,
            "server_instance": mock_server_instance,
            "connection_instance": mock_conn_instance,
        }


@pytest.fixture
def mock_oidc_provider():
    """Mock OIDC provider for testing"""
    with (
        patch("requests.get") as mock_get,
        patch("requests.post") as mock_post,
        patch("jose.jwt.decode") as mock_jwt_decode,
    ):

        # Mock discovery document
        discovery_response = Mock()
        discovery_response.json.return_value = {
            "authorization_endpoint": "https://test-issuer.com/auth",
            "token_endpoint": "https://test-issuer.com/token",
            "userinfo_endpoint": "https://test-issuer.com/userinfo",
            "jwks_uri": "https://test-issuer.com/jwks",
        }
        mock_get.return_value = discovery_response

        # Mock token exchange
        token_response = Mock()
        token_response.json.return_value = {
            "access_token": "test_access_token",
            "id_token": "test_id_token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_post.return_value = token_response

        # Mock JWT decode
        mock_jwt_decode.return_value = {
            "sub": "user123",
            "email": "user@test.com",
            "name": "Test User",
            "groups": ["users"],
        }

        yield {
            "get": mock_get,
            "post": mock_post,
            "jwt_decode": mock_jwt_decode,
            "discovery_response": discovery_response,
            "token_response": token_response,
        }


@pytest.fixture
def authenticated_client(client, app, test_users, auth_manager):
    """Create authenticated test client"""

    def _authenticate_as(username):
        user = test_users[username]
        session_id = auth_manager.create_session(user)

        with client.session_transaction() as sess:
            sess["session_id"] = session_id
            sess["user_id"] = user.id

        return client

    return _authenticate_as


@pytest.fixture
def temp_config_dir():
    """Create temporary configuration directory"""
    temp_dir = tempfile.mkdtemp()
    config_dir = os.path.join(temp_dir, "config", "settings")
    os.makedirs(config_dir, exist_ok=True)

    yield config_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def sample_auth_config(temp_config_dir):
    """Create sample authentication configuration file"""
    config_content = """
authentication:
  session:
    lifetime_hours: 8
    cleanup_interval_minutes: 60
    secure_cookies: true
    
  provider_priority:
    - local
    - ldap
    - oidc
    
  providers:
    local:
      enabled: true
      password_policy:
        min_length: 8
        require_uppercase: true
        require_lowercase: true
        require_numbers: true
        require_special: false
        
    ldap:
      enabled: false
      server: "ldap://your-ad-server.company.com"
      port: 389
      use_ssl: false
      use_tls: true
      bind_dn: "CN=trakbridge,OU=Service Accounts,DC=company,DC=com"
      bind_password: "service_account_password"
      user_search_base: "OU=Users,DC=company,DC=com"
      user_search_filter: "(sAMAccountName={username})"
      role_mapping:
        "CN=TrakBridge-Admins,OU=Groups,DC=company,DC=com": "admin"
        "CN=TrakBridge-Operators,OU=Groups,DC=company,DC=com": "operator"
        "CN=TrakBridge-Users,OU=Groups,DC=company,DC=com": "user"
        
    oidc:
      enabled: false
      issuer: "https://your-identity-provider.com"
      client_id: "trakbridge-client"
      client_secret: "your-client-secret"
      scopes: ["openid", "email", "profile"]
      role_claim: "groups"
      role_mapping:
        "trakbridge-admins": "admin"
        "trakbridge-operators": "operator"
        "trakbridge-users": "user"
"""

    config_file = os.path.join(temp_config_dir, "auth.yaml")
    with open(config_file, "w") as f:
        f.write(config_content)

    return config_file


@pytest.fixture
def test_callsign_mappings(app, db_session, test_users):
    """Create test callsign mappings - follows existing fixture patterns"""
    mappings = {}

    with app.app_context():
        from models.callsign_mapping import CallsignMapping
        from models.stream import Stream

        # Create test streams for tracker plugins
        test_streams = {}
        for plugin_type in ["garmin", "spot", "traccar"]:
            stream = Stream(
                name=f"Test {plugin_type.title()} Stream",
                plugin_type=plugin_type,
                enable_callsign_mapping=True,
                callsign_identifier_field=(
                    "imei" if plugin_type == "garmin" else "device_name"
                ),
            )
            db_session.add(stream)
            test_streams[plugin_type] = stream

        db_session.commit()

        # Create test callsign mappings
        for plugin_type, stream in test_streams.items():
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value=f"TEST_{plugin_type.upper()}_123",
                custom_callsign=f"CALL_{plugin_type.upper()}_1",
                cot_type="a-f-G-U-C",
            )
            db_session.add(mapping)
            mappings[plugin_type] = mapping

        db_session.commit()

    return mappings


@pytest.fixture
def test_streams(app, db_session):
    """Create test streams - add to existing fixtures for callsign testing"""
    streams = {}

    with app.app_context():
        from models.stream import Stream

        # Create basic streams
        basic_stream = Stream(name="Basic Stream", plugin_type="garmin")
        db_session.add(basic_stream)
        streams["basic"] = basic_stream

        # Create callsign-enabled streams
        callsign_stream = Stream(
            name="Callsign Stream",
            plugin_type="spot",
            enable_callsign_mapping=True,
            callsign_identifier_field="device_name",
            callsign_error_handling="fallback",
            enable_per_callsign_cot_types=True,
        )
        db_session.add(callsign_stream)
        streams["callsign"] = callsign_stream

        db_session.commit()

    return streams


# Test utilities
def create_test_user(
    username,
    email,
    role=UserRole.USER,
    auth_provider=AuthProvider.LOCAL,
    password="TestPass123",
):
    """Utility function to create test users"""
    user = User(
        username=username,
        email=email,
        full_name=f"{username.title()} User",
        role=role,
        auth_provider=auth_provider,
    )
    if password:
        user.set_password(password)
    return user


def create_test_session(user, expires_in_hours=8):
    """Utility function to create test sessions"""
    session = UserSession(
        user_id=user.id,
        session_id=f"test_session_{user.username}",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
    )
    return session


# Pytest hooks
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line("markers", "integration: mark test as integration test")
    config.addinivalue_line("markers", "ldap: mark test as requiring LDAP server")
    config.addinivalue_line("markers", "oidc: mark test as requiring OIDC provider")
    config.addinivalue_line("markers", "performance: mark test as performance test")
    config.addinivalue_line("markers", "security: mark test as security test")
    config.addinivalue_line("markers", "callsign: mark test as callsign mapping test")
    config.addinivalue_line(
        "markers", "database: mark test as requiring specific database"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test names"""
    for item in items:
        # Add integration marker for integration tests
        if "integration" in item.nodeid.lower():
            item.add_marker(pytest.mark.integration)

        # Add LDAP marker for LDAP tests
        if "ldap" in item.nodeid.lower():
            item.add_marker(pytest.mark.ldap)

        # Add OIDC marker for OIDC tests
        if "oidc" in item.nodeid.lower():
            item.add_marker(pytest.mark.oidc)

        # Add performance marker for performance tests
        if "performance" in item.nodeid.lower():
            item.add_marker(pytest.mark.performance)

        # Add security marker for security tests
        if "security" in item.nodeid.lower():
            item.add_marker(pytest.mark.security)
