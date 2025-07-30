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

import pytest
import tempfile
import os
import shutil
from unittest.mock import Mock, patch
from flask import Flask
from datetime import datetime, timedelta, timezone

# Import application components
from database import db
from services.auth.auth_manager import AuthenticationManager
from models.user import User, UserRole, UserSession


@pytest.fixture(scope="session")
def app():
    """Create test Flask application for session scope"""
    app = Flask(__name__)
    
    # Test configuration
    app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-for-sessions',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'WTF_CSRF_ENABLED': False,
        'LOGIN_DISABLED': False,
        'TRAKBRIDGE_ENCRYPTION_KEY': 'test-encryption-key-for-testing-12345'
    })
    
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
            'session': {
                'lifetime_hours': 8,
                'cleanup_interval_minutes': 60,
                'secure_cookies': False  # For testing
            },
            'provider_priority': ['local', 'ldap', 'oidc'],
            'providers': {
                'local': {
                    'enabled': True,
                    'password_policy': {
                        'min_length': 8,
                        'require_uppercase': True,
                        'require_lowercase': True,
                        'require_numbers': True,
                        'require_special': False
                    }
                },
                'ldap': {
                    'enabled': False,
                    'server': 'ldap://test-server.com',
                    'port': 389,
                    'use_ssl': False,
                    'use_tls': True,
                    'bind_dn': 'CN=test,DC=test,DC=com',
                    'bind_password': 'test_password',
                    'user_search_base': 'OU=Users,DC=test,DC=com',
                    'user_search_filter': '(sAMAccountName={username})',
                    'role_mapping': {
                        'CN=Admins,DC=test,DC=com': 'admin',
                        'CN=Operators,DC=test,DC=com': 'operator',
                        'CN=Users,DC=test,DC=com': 'user'
                    }
                },
                'oidc': {
                    'enabled': False,
                    'issuer': 'https://test-issuer.com',
                    'client_id': 'test-client',
                    'client_secret': 'test-secret',
                    'scopes': ['openid', 'email', 'profile'],
                    'role_claim': 'groups',
                    'role_mapping': {
                        'admins': 'admin',
                        'operators': 'operator',
                        'users': 'user'
                    }
                }
            }
        }
        
        with patch('services.auth.auth_manager.load_auth_config', return_value=test_config):
            manager = AuthenticationManager()
            yield manager


@pytest.fixture
def test_users(app, db_session):
    """Create test users for authentication tests"""
    users = {}
    
    # Admin user
    admin = User(
        username='admin',
        email='admin@test.com',
        first_name='Admin',
        last_name='User',
        role=UserRole.ADMIN,
        auth_provider='local',
        is_active=True
    )
    admin.set_password('AdminPass123')
    db_session.add(admin)
    users['admin'] = admin
    
    # Operator user
    operator = User(
        username='operator',
        email='operator@test.com',
        first_name='Operator',
        last_name='User',
        role=UserRole.OPERATOR,
        auth_provider='local',
        is_active=True
    )
    operator.set_password('OperatorPass123')
    db_session.add(operator)
    users['operator'] = operator
    
    # Regular user
    user = User(
        username='user',
        email='user@test.com',
        first_name='Regular',
        last_name='User',
        role=UserRole.USER,
        auth_provider='local',
        is_active=True
    )
    user.set_password('UserPass123')
    db_session.add(user)
    users['user'] = user
    
    # Inactive user
    inactive = User(
        username='inactive',
        email='inactive@test.com',
        first_name='Inactive',
        last_name='User',
        role=UserRole.USER,
        auth_provider='local',
        is_active=False
    )
    inactive.set_password('InactivePass123')
    db_session.add(inactive)
    users['inactive'] = inactive
    
    # LDAP user
    ldap_user = User(
        username='ldapuser',
        email='ldapuser@test.com',
        first_name='LDAP',
        last_name='User',
        role=UserRole.USER,
        auth_provider='ldap',
        is_active=True
    )
    db_session.add(ldap_user)
    users['ldap_user'] = ldap_user
    
    # OIDC user
    oidc_user = User(
        username='oidcuser',
        email='oidcuser@test.com',
        first_name='OIDC',
        last_name='User',
        role=UserRole.OPERATOR,
        auth_provider='oidc',
        is_active=True
    )
    db_session.add(oidc_user)
    users['oidc_user'] = oidc_user
    
    db_session.commit()
    return users


@pytest.fixture
def test_sessions(app, db_session, test_users):
    """Create test sessions"""
    sessions = {}
    
    # Active session for admin
    admin_session = UserSession.create_session(test_users['admin'])
    sessions['admin'] = admin_session
    
    # Active session for regular user
    user_session = UserSession.create_session(test_users['user'])
    sessions['user'] = user_session
    
    # Expired session
    expired_session = UserSession.create_session(test_users['operator'])
    expired_session.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    sessions['expired'] = expired_session
    
    db_session.commit()
    return sessions


@pytest.fixture
def mock_ldap_connection():
    """Mock LDAP connection for testing"""
    with patch('ldap3.Server') as mock_server, \
         patch('ldap3.Connection') as mock_connection:
        
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
                entry_dn='CN=testuser,OU=Users,DC=test,DC=com',
                sAMAccountName='testuser',
                mail='testuser@test.com',
                givenName='Test',
                sn='User',
                displayName='Test User'
            )
        ]
        
        yield {
            'server': mock_server,
            'connection': mock_connection,
            'server_instance': mock_server_instance,
            'connection_instance': mock_conn_instance
        }


@pytest.fixture
def mock_oidc_provider():
    """Mock OIDC provider for testing"""
    with patch('requests.get') as mock_get, \
         patch('requests.post') as mock_post, \
         patch('jose.jwt.decode') as mock_jwt_decode:
        
        # Mock discovery document
        discovery_response = Mock()
        discovery_response.json.return_value = {
            'authorization_endpoint': 'https://test-issuer.com/auth',
            'token_endpoint': 'https://test-issuer.com/token',
            'userinfo_endpoint': 'https://test-issuer.com/userinfo',
            'jwks_uri': 'https://test-issuer.com/jwks'
        }
        mock_get.return_value = discovery_response
        
        # Mock token exchange
        token_response = Mock()
        token_response.json.return_value = {
            'access_token': 'test_access_token',
            'id_token': 'test_id_token',
            'token_type': 'Bearer',
            'expires_in': 3600
        }
        mock_post.return_value = token_response
        
        # Mock JWT decode
        mock_jwt_decode.return_value = {
            'sub': 'user123',
            'email': 'user@test.com',
            'name': 'Test User',
            'groups': ['users']
        }
        
        yield {
            'get': mock_get,
            'post': mock_post,
            'jwt_decode': mock_jwt_decode,
            'discovery_response': discovery_response,
            'token_response': token_response
        }


@pytest.fixture
def authenticated_client(client, app, test_users, auth_manager):
    """Create authenticated test client"""
    def _authenticate_as(username):
        user = test_users[username]
        session_id = auth_manager.create_session(user)
        
        with client.session_transaction() as sess:
            sess['session_id'] = session_id
            sess['user_id'] = user.id
        
        return client
    
    return _authenticate_as


@pytest.fixture
def temp_config_dir():
    """Create temporary configuration directory"""
    temp_dir = tempfile.mkdtemp()
    config_dir = os.path.join(temp_dir, 'config', 'settings')
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
    
    config_file = os.path.join(temp_config_dir, 'auth.yaml')
    with open(config_file, 'w') as f:
        f.write(config_content)
    
    return config_file


# Test utilities
def create_test_user(username, email, role=UserRole.USER, auth_provider='local', password='TestPass123'):
    """Utility function to create test users"""
    user = User(
        username=username,
        email=email,
        first_name=username.title(),
        last_name='User',
        role=role,
        auth_provider=auth_provider,
        is_active=True
    )
    if password:
        user.set_password(password)
    return user


def create_test_session(user, expires_in_hours=8):
    """Utility function to create test sessions"""
    session = UserSession(
        user_id=user.id,
        session_id=f'test_session_{user.username}',
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
    )
    return session


# Pytest hooks
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "ldap: mark test as requiring LDAP server"
    )
    config.addinivalue_line(
        "markers", "oidc: mark test as requiring OIDC provider"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "security: mark test as security test"
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