"""
ABOUTME: Authentication services package for TrakBridge multi-provider authentication
ABOUTME: Exports authentication providers, managers, and base classes

File: services/auth/__init__.py

Description:
    Authentication services package initialization providing centralized imports
    for all authentication-related classes and functions. Exports the authentication
    manager, base provider interface, concrete providers, and utility functions
    for easy import throughout the application.

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Authentication manager
from .auth_manager import AuthenticationManager
# Base authentication components
from .base_provider import (AuthenticationException, AuthenticationResponse,
                            AuthenticationResult, BaseAuthenticationProvider,
                            ProviderConfigurationException,
                            ProviderConnectionException)
# Authentication decorators
from .decorators import (admin_required, api_key_or_auth_required,
                         create_auth_context_processor, get_current_user,
                         get_user_permissions, is_authenticated,
                         login_required_json, logout_user, operator_required,
                         optional_auth, require_auth, require_permission,
                         require_role)
from .ldap_provider import LDAPAuthProvider
# Authentication providers
from .local_provider import LocalAuthProvider, PasswordPolicyViolation
from .oidc_provider import OIDCAuthProvider

__all__ = [
    # Base provider and responses
    "BaseAuthenticationProvider",
    "AuthenticationResult",
    "AuthenticationResponse",
    # Authentication manager
    "AuthenticationManager",
    # Providers
    "LocalAuthProvider",
    "LDAPAuthProvider",
    "OIDCAuthProvider",
    # Decorators and utilities
    "require_auth",
    "require_role",
    "require_permission",
    "admin_required",
    "operator_required",
    "api_key_or_auth_required",
    "optional_auth",
    "login_required_json",
    "get_current_user",
    "is_authenticated",
    "logout_user",
    "get_user_permissions",
    "create_auth_context_processor",
    # Exceptions
    "AuthenticationException",
    "ProviderConfigurationException",
    "ProviderConnectionException",
    "PasswordPolicyViolation",
]
