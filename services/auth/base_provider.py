"""
ABOUTME: Base authentication provider interface for TrakBridge authentication system
ABOUTME: Defines common interface for Local, LDAP, and OIDC authentication providers

File: services/auth/base_provider.py

Description:
    Base authentication provider interface that defines the common contract for all
    authentication methods in TrakBridge. Provides abstract methods for authentication,
    user management, and session handling that must be implemented by concrete providers
    (Local, LDAP, OIDC). Includes comprehensive error handling and logging integration.

Key features:
    - Abstract base class defining authentication provider contract
    - Standardized authentication result structure with detailed metadata
    - User creation and update methods for provider-specific data handling
    - Session management interface for provider-specific session data
    - Health check capabilities for monitoring provider status
    - Comprehensive error handling with typed exceptions
    - Built-in logging and debugging support
    - Configuration validation framework
    - Provider priority and fallback support

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Standard library imports
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# Local application imports
from models.user import AuthProvider, User, UserRole, UserSession

# Third-party imports
# (none for this file)



# Module-level logger
logger = logging.getLogger(__name__)


class AuthenticationResult(Enum):
    """Authentication result status codes"""

    SUCCESS = "success"
    INVALID_CREDENTIALS = "invalid_credentials"
    USER_NOT_FOUND = "user_not_found"
    USER_DISABLED = "user_disabled"
    USER_LOCKED = "user_locked"
    ACCOUNT_EXPIRED = "account_expired"
    PASSWORD_EXPIRED = "password_expired"
    PROVIDER_ERROR = "provider_error"
    CONFIGURATION_ERROR = "configuration_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    UNKNOWN_ERROR = "unknown_error"


class AuthenticationException(Exception):
    """Base exception for authentication errors"""

    def __init__(
        self,
        message: str,
        result: AuthenticationResult = AuthenticationResult.UNKNOWN_ERROR,
        details: Dict[str, Any] = None,
    ):
        super().__init__(message)
        self.result = result
        self.details = details or {}
        self.timestamp = datetime.utcnow()


class ProviderConfigurationException(AuthenticationException):
    """Exception for provider configuration errors"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, AuthenticationResult.CONFIGURATION_ERROR, details)


class ProviderConnectionException(AuthenticationException):
    """Exception for provider connection errors"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, AuthenticationResult.NETWORK_ERROR, details)


class AuthenticationResponse:
    """
    Standardized response object for authentication operations
    """

    def __init__(
        self,
        result: AuthenticationResult,
        user: Optional[User] = None,
        message: str = None,
        details: Dict[str, Any] = None,
        session_data: Dict[str, Any] = None,
    ):
        self.result = result
        self.user = user
        self.message = message or result.value.replace("_", " ").title()
        self.details = details or {}
        self.session_data = session_data or {}
        self.timestamp = datetime.utcnow()
        self.success = result == AuthenticationResult.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary representation"""
        data = {
            "success": self.success,
            "result": self.result.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }

        if self.user:
            data["user"] = self.user.to_dict()

        if self.session_data:
            data["session_data"] = self.session_data

        return data


class BaseAuthenticationProvider(ABC):
    """
    Abstract base class for all authentication providers
    """

    def __init__(self, provider_type: AuthProvider, config: Dict[str, Any] = None):
        self.provider_type = provider_type
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.priority = self.config.get("priority", 99)
        self.name = self.config.get("name", provider_type.value)
        self.logger = logging.getLogger(f"{__name__}.{provider_type.value}")

        # Validate configuration on initialization
        self._validate_configuration()

    @abstractmethod
    def authenticate(
        self, username: str, password: str = None, **kwargs
    ) -> AuthenticationResponse:
        """
        Authenticate a user with credentials

        Args:
            username: Username to authenticate
            password: Password (may be None for external providers)
            **kwargs: Provider-specific authentication parameters

        Returns:
            AuthenticationResponse with result and user information

        Raises:
            AuthenticationException: For authentication errors
        """
        pass

    @abstractmethod
    def get_user_info(self, username: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Retrieve user information from the provider

        Args:
            username: Username to look up
            **kwargs: Provider-specific parameters

        Returns:
            Dictionary with user information or None if not found

        Raises:
            AuthenticationException: For provider errors
        """
        pass

    @abstractmethod
    def validate_configuration(self) -> List[str]:
        """
        Validate provider configuration

        Returns:
            List of configuration issues (empty if valid)
        """
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Check provider health and connectivity

        Returns:
            Dictionary with health status information
        """
        pass

    def _validate_configuration(self) -> None:
        """Internal configuration validation"""
        issues = self.validate_configuration()
        if issues:
            raise ProviderConfigurationException(
                f"Configuration validation failed for {self.provider_type.value}",
                details={"issues": issues},
            )

    def create_or_update_user(self, username: str, user_data: Dict[str, Any]) -> User:
        """
        Create or update a user from provider data

        Args:
            username: Username
            user_data: User data from provider

        Returns:
            User instance
        """
        from database import db

        # Check if user already exists
        user = User.query.filter_by(
            username=username, auth_provider=self.provider_type
        ).first()

        if user:
            # Update existing user
            user.update_from_provider(user_data)
            self.logger.info(f"Updated existing user: {username}")
        else:
            # Create new user
            user = User.create_external_user(
                username=username,
                provider=self.provider_type,
                provider_user_id=user_data.get("id", username),
                provider_data=user_data,
                role=self._determine_user_role(user_data),
            )
            db.session.add(user)
            self.logger.info(f"Created new user: {username}")

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise AuthenticationException(
                f"Failed to save user {username}",
                AuthenticationResult.PROVIDER_ERROR,
                {"error": str(e)},
            )

        return user

    def _determine_user_role(self, user_data: Dict[str, Any]) -> UserRole:
        """
        Determine user role based on provider data and configuration

        Args:
            user_data: User data from provider

        Returns:
            UserRole for the user
        """
        # Default role mapping logic
        default_role = UserRole(self.config.get("default_role", "user"))

        # Check for role mapping configuration
        role_mappings = self.config.get("role_mappings", {})

        # Check groups/roles from provider data
        user_groups = user_data.get("groups", [])
        user_roles = user_data.get("roles", [])

        # Apply role mappings
        for provider_value in user_groups + user_roles:
            if provider_value in role_mappings:
                mapped_role = role_mappings[provider_value]
                try:
                    return UserRole(mapped_role)
                except ValueError:
                    self.logger.warning(f"Invalid role mapping: {mapped_role}")

        return default_role

    def create_session(
        self, user: User, request_info: Dict[str, Any] = None
    ) -> UserSession:
        """
        Create a new user session

        Args:
            user: User to create session for
            request_info: Request information (IP, user agent, etc.)

        Returns:
            UserSession instance
        """
        from database import db

        request_info = request_info or {}

        session = UserSession.create_session(
            user=user,
            provider=self.provider_type,
            expires_in_hours=self.config.get("session_timeout_hours", 24),
            ip_address=request_info.get("ip_address"),
            user_agent=request_info.get("user_agent"),
            provider_session_data=request_info.get("provider_session_data"),
        )

        db.session.add(session)

        try:
            db.session.commit()
            self.logger.info(f"Created session for user {user.username}")
        except Exception as e:
            db.session.rollback()
            raise AuthenticationException(
                f"Failed to create session for user {user.username}",
                AuthenticationResult.PROVIDER_ERROR,
                {"error": str(e)},
            )

        return session

    def validate_session(self, session_id: str) -> Optional[UserSession]:
        """
        Validate a user session

        Args:
            session_id: Session ID to validate

        Returns:
            UserSession if valid, None otherwise
        """
        session = UserSession.query.filter_by(session_id=session_id).first()

        if session and session.is_valid():
            session.update_activity()
            try:
                from database import db

                db.session.commit()
            except Exception as e:
                self.logger.warning(f"Failed to update session activity: {e}")
            return session

        return None

    def invalidate_session(self, session_id: str) -> bool:
        """
        Invalidate a user session

        Args:
            session_id: Session ID to invalidate

        Returns:
            True if session was invalidated, False if not found
        """
        from database import db

        session = UserSession.query.filter_by(session_id=session_id).first()

        if session:
            session.invalidate()
            try:
                db.session.commit()
                self.logger.info(f"Invalidated session: {session_id}")
                return True
            except Exception as e:
                db.session.rollback()
                self.logger.error(f"Failed to invalidate session {session_id}: {e}")

        return False

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions for this provider

        Returns:
            Number of sessions cleaned up
        """
        from database import db

        try:
            # Find expired sessions for users of this provider
            expired_sessions = (
                db.session.query(UserSession)
                .join(User)
                .filter(
                    User.auth_provider == self.provider_type,
                    UserSession.expires_at < datetime.utcnow(),
                )
                .all()
            )

            count = len(expired_sessions)

            for session in expired_sessions:
                session.invalidate()

            db.session.commit()

            if count > 0:
                self.logger.info(f"Cleaned up {count} expired sessions")

            return count

        except Exception as e:
            db.session.rollback()
            self.logger.error(f"Failed to cleanup expired sessions: {e}")
            return 0

    def get_provider_info(self) -> Dict[str, Any]:
        """
        Get provider information and status

        Returns:
            Dictionary with provider information
        """
        return {
            "name": self.name,
            "type": self.provider_type.value,
            "enabled": self.enabled,
            "priority": self.priority,
            "config_valid": len(self.validate_configuration()) == 0,
            "health": self.health_check(),
        }

    def supports_feature(self, feature: str) -> bool:
        """
        Check if provider supports a specific feature

        Args:
            feature: Feature name to check

        Returns:
            True if feature is supported
        """
        # Base features supported by all providers
        base_features = [
            "authentication",
            "user_info",
            "session_management",
            "health_check",
        ]

        return feature in base_features

    def __str__(self) -> str:
        return f"{self.__class__.__name__}({self.provider_type.value})"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.provider_type.value}, enabled={self.enabled}, priority={self.priority})"
