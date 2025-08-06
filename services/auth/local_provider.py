"""
ABOUTME: Local authentication provider for database-stored user credentials
ABOUTME: Implements secure bcrypt password hashing and local user management

File: services/auth/local_provider.py

Description:
    Local authentication provider that manages user credentials stored in the TrakBridge
    database. Implements secure password hashing using bcrypt, user registration, password
    reset functionality, and comprehensive security controls. Serves as the failsafe
    authentication method when external providers (OIDC/LDAP) are unavailable.

Key features:
    - Secure bcrypt password hashing with configurable work factor
    - User registration with optional email verification
    - Password policy enforcement (length, complexity, expiration)
    - Account lockout and brute force protection
    - Password reset with secure token generation
    - Session management with configurable timeouts
    - Comprehensive audit logging for all authentication events
    - Administrative user management functions
    - Health monitoring and self-diagnostics

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Standard library imports
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
import bcrypt

# Local application imports
from models.user import AccountStatus, AuthProvider, User, UserRole

from .base_provider import (
    AuthenticationException,
    AuthenticationResponse,
    AuthenticationResult,
    BaseAuthenticationProvider,
)

# Module-level logger
logger = logging.getLogger(__name__)


class PasswordPolicyViolation(AuthenticationException):
    """Exception for password policy violations"""

    def __init__(self, message: str, violations: List[str]):
        super().__init__(message, AuthenticationResult.INVALID_CREDENTIALS)
        self.violations = violations


class LocalAuthProvider(BaseAuthenticationProvider):
    """
    Local authentication provider using database-stored credentials
    """

    def __init__(self, config: Dict[str, Any] = None):
        # Initialize config if not provided
        config = config or {}

        # Set all attributes BEFORE calling super().__init__() because validation runs there
        self.password_policy = config.get("password_policy", {})
        self.min_length = self.password_policy.get("min_length", 8)
        self.require_uppercase = self.password_policy.get("require_uppercase", True)
        self.require_lowercase = self.password_policy.get("require_lowercase", True)
        self.require_numbers = self.password_policy.get("require_numbers", True)
        self.require_special_chars = self.password_policy.get(
            "require_special_chars", True
        )
        self.max_age_days = self.password_policy.get("max_age_days", 90)

        # Registration settings
        self.allow_registration = config.get("allow_registration", False)
        self.require_email_verification = config.get(
            "require_email_verification", False
        )
        self.default_role = UserRole(config.get("default_role", "user"))

        # Security settings
        self.bcrypt_rounds = config.get("bcrypt_rounds", 12)
        self.password_reset_timeout = config.get("password_reset_timeout_hours", 1)

        # Now call parent constructor which will validate configuration
        super().__init__(AuthProvider.LOCAL, config)

        logger.info(
            f"Local authentication provider initialized (registration: {self.allow_registration})"
        )

    def authenticate(
        self, username: str, password: str = None, **kwargs
    ) -> AuthenticationResponse:
        """
        Authenticate user with username and password

        Args:
            username: Username to authenticate
            password: Password to verify
            **kwargs: Additional parameters (ignored for local auth)

        Returns:
            AuthenticationResponse with authentication result
        """
        if not username or not password:
            return AuthenticationResponse(
                result=AuthenticationResult.INVALID_CREDENTIALS,
                message="Username and password are required",
            )

        try:
            # Find user by username
            user = User.query.filter_by(
                username=username, auth_provider=AuthProvider.LOCAL
            ).first()

            if not user:
                # Log failed attempt for non-existent user
                self.logger.warning(
                    f"Authentication attempt for non-existent user: {username}"
                )
                return AuthenticationResponse(
                    result=AuthenticationResult.USER_NOT_FOUND,
                    message="Invalid username or password",
                )

            # Check account status
            if not user.is_active():
                if user.status == AccountStatus.DISABLED:
                    return AuthenticationResponse(
                        result=AuthenticationResult.USER_DISABLED,
                        message="Account is disabled",
                    )
                elif user.is_locked():
                    return AuthenticationResponse(
                        result=AuthenticationResult.USER_LOCKED,
                        message="Account is temporarily locked",
                        details={
                            "locked_until": (
                                user.locked_until.isoformat()
                                if user.locked_until
                                else None
                            ),
                            "failed_attempts": user.failed_login_attempts,
                        },
                    )

            # Check password expiration
            if self._is_password_expired(user):
                return AuthenticationResponse(
                    result=AuthenticationResult.PASSWORD_EXPIRED,
                    message="Password has expired",
                    details={
                        "password_changed_at": (
                            user.password_changed_at.isoformat()
                            if user.password_changed_at
                            else None
                        )
                    },
                )

            # Verify password
            if not user.check_password(password):
                # Increment failed login attempts
                user.increment_failed_login()
                try:
                    from database import db

                    db.session.commit()
                except Exception as e:
                    self.logger.error(f"Failed to update failed login count: {e}")

                self.logger.warning(
                    f"Failed password authentication for user: {username}"
                )
                return AuthenticationResponse(
                    result=AuthenticationResult.INVALID_CREDENTIALS,
                    message="Invalid username or password",
                    details={"failed_attempts": user.failed_login_attempts},
                )

            # Successful authentication
            user.reset_failed_login()
            try:
                from database import db

                db.session.commit()
            except Exception as e:
                self.logger.error(f"Failed to reset failed login count: {e}")

            self.logger.info(f"Successful local authentication for user: {username}")
            return AuthenticationResponse(
                result=AuthenticationResult.SUCCESS,
                user=user,
                message="Authentication successful",
                details={"provider": "local"},
            )

        except Exception as e:
            self.logger.error(
                f"Local authentication error for {username}: {e}", exc_info=True
            )
            return AuthenticationResponse(
                result=AuthenticationResult.PROVIDER_ERROR,
                message="Authentication service error",
                details={"error": str(e)},
            )

    def get_user_info(self, username: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Get user information from local database

        Args:
            username: Username to look up
            **kwargs: Additional parameters (ignored)

        Returns:
            Dictionary with user information or None if not found
        """
        try:
            user = User.query.filter_by(
                username=username, auth_provider=AuthProvider.LOCAL
            ).first()

            if user:
                return {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role.value,
                    "status": user.status.value,
                    "created_at": user.created_at.isoformat(),
                    "last_login": (
                        user.last_login.isoformat() if user.last_login else None
                    ),
                    "is_active": user.is_active(),
                    "is_locked": user.is_locked(),
                    "password_expired": self._is_password_expired(user),
                }

            return None

        except Exception as e:
            self.logger.error(f"Error getting user info for {username}: {e}")
            return None

    def validate_configuration(self) -> List[str]:
        """
        Validate local provider configuration

        Returns:
            List of configuration issues
        """
        issues = []

        # Validate password policy
        if self.min_length < 4:
            issues.append("Password minimum length should be at least 4 characters")

        if self.bcrypt_rounds < 10 or self.bcrypt_rounds > 15:
            issues.append("Bcrypt rounds should be between 10 and 15")

        if self.max_age_days is not None and self.max_age_days < 0:
            issues.append("Password max age days cannot be negative")

        if not isinstance(self.allow_registration, bool):
            issues.append("allow_registration must be a boolean value")

        # Validate default role
        try:
            UserRole(self.config.get("default_role", "user"))
        except ValueError:
            issues.append(f"Invalid default_role: {self.config.get('default_role')}")

        return issues

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check for local authentication

        Returns:
            Dictionary with health status
        """
        try:
            # Test database connectivity by counting local users
            from database import db

            user_count = (
                db.session.query(User)
                .filter_by(auth_provider=AuthProvider.LOCAL)
                .count()
            )

            # Test bcrypt functionality
            test_hash = bcrypt.hashpw(
                b"test", bcrypt.gensalt(rounds=self.bcrypt_rounds)
            )
            test_verify = bcrypt.checkpw(b"test", test_hash)

            if not test_verify:
                raise Exception("Bcrypt verification failed")

            return {
                "status": "healthy",
                "provider": "local",
                "user_count": user_count,
                "bcrypt_rounds": self.bcrypt_rounds,
                "allow_registration": self.allow_registration,
                "password_policy_enabled": bool(self.password_policy),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "provider": "local",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def create_user(
        self,
        username: str,
        password: str,
        email: str = None,
        full_name: str = None,
        role: UserRole = None,
    ) -> User:
        """
        Create a new local user

        Args:
            username: Username for the new user
            password: Password for the new user
            email: Email address
            full_name: Full name
            role: User role (defaults to configured default role)

        Returns:
            Created User instance

        Raises:
            AuthenticationException: If user creation fails
        """
        if not self.allow_registration and role != UserRole.ADMIN:
            raise AuthenticationException(
                "User registration is not allowed",
                AuthenticationResult.CONFIGURATION_ERROR,
            )

        # Validate password policy
        policy_violations = self.validate_password(password)
        if policy_violations:
            raise PasswordPolicyViolation(
                "Password does not meet policy requirements", policy_violations
            )

        # Check if username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            raise AuthenticationException(
                f"Username '{username}' already exists",
                AuthenticationResult.INVALID_CREDENTIALS,
            )

        # Check if email already exists (if provided)
        if email:
            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                raise AuthenticationException(
                    f"Email '{email}' already exists",
                    AuthenticationResult.INVALID_CREDENTIALS,
                )

        try:
            # Create new user
            user = User.create_local_user(
                username=username,
                password=password,
                email=email,
                full_name=full_name,
                role=role or self.default_role,
            )

            from database import db

            db.session.add(user)
            db.session.commit()

            self.logger.info(f"Created new local user: {username}")
            return user

        except Exception as e:
            from database import db

            db.session.rollback()
            self.logger.error(f"Failed to create user {username}: {e}")
            raise AuthenticationException(
                f"Failed to create user: {str(e)}", AuthenticationResult.PROVIDER_ERROR
            )

    def change_password(
        self, username: str, current_password: str, new_password: str
    ) -> bool:
        """
        Change user password

        Args:
            username: Username
            current_password: Current password for verification
            new_password: New password to set

        Returns:
            True if password was changed successfully

        Raises:
            AuthenticationException: If password change fails
        """
        # Find user
        user = User.query.filter_by(
            username=username, auth_provider=AuthProvider.LOCAL
        ).first()

        if not user:
            raise AuthenticationException(
                "User not found", AuthenticationResult.USER_NOT_FOUND
            )

        # Verify current password
        if not user.check_password(current_password):
            raise AuthenticationException(
                "Current password is incorrect",
                AuthenticationResult.INVALID_CREDENTIALS,
            )

        # Validate new password policy
        policy_violations = self.validate_password(new_password)
        if policy_violations:
            raise PasswordPolicyViolation(
                "New password does not meet policy requirements", policy_violations
            )

        try:
            # Set new password
            user.set_password(new_password)

            from database import db

            db.session.commit()

            self.logger.info(f"Password changed for user: {username}")
            return True

        except Exception as e:
            from database import db

            db.session.rollback()
            self.logger.error(f"Failed to change password for {username}: {e}")
            raise AuthenticationException(
                f"Failed to change password: {str(e)}",
                AuthenticationResult.PROVIDER_ERROR,
            )

    def reset_password(self, username: str, new_password: str) -> bool:
        """
        Reset user password (admin function)

        Args:
            username: Username
            new_password: New password to set

        Returns:
            True if password was reset successfully

        Raises:
            AuthenticationException: If password reset fails
        """
        # Find user
        user = User.query.filter_by(
            username=username, auth_provider=AuthProvider.LOCAL
        ).first()

        if not user:
            raise AuthenticationException(
                "User not found", AuthenticationResult.USER_NOT_FOUND
            )

        # Validate new password policy
        policy_violations = self.validate_password(new_password)
        if policy_violations:
            raise PasswordPolicyViolation(
                "New password does not meet policy requirements", policy_violations
            )

        try:
            # Set new password
            user.set_password(new_password)
            user.unlock_account()  # Unlock account if it was locked

            from database import db

            db.session.commit()

            self.logger.info(f"Password reset for user: {username}")
            return True

        except Exception as e:
            from database import db

            db.session.rollback()
            self.logger.error(f"Failed to reset password for {username}: {e}")
            raise AuthenticationException(
                f"Failed to reset password: {str(e)}",
                AuthenticationResult.PROVIDER_ERROR,
            )

    def validate_password(self, password: str) -> List[str]:
        """
        Validate password against policy

        Args:
            password: Password to validate

        Returns:
            List of policy violations (empty if valid)
        """
        violations = []

        if len(password) < self.min_length:
            violations.append(
                f"Password must be at least {self.min_length} characters long"
            )

        if self.require_uppercase and not re.search(r"[A-Z]", password):
            violations.append("Password must contain at least one uppercase letter")

        if self.require_lowercase and not re.search(r"[a-z]", password):
            violations.append("Password must contain at least one lowercase letter")

        if self.require_numbers and not re.search(r"\d", password):
            violations.append("Password must contain at least one number")

        if self.require_special_chars and not re.search(
            r'[!@#$%^&*(),.?":{}|<>]', password
        ):
            violations.append("Password must contain at least one special character")

        return violations

    def generate_secure_password(self, length: int = 12) -> str:
        """
        Generate a secure password that meets policy requirements

        Args:
            length: Password length (minimum is policy min_length)

        Returns:
            Generated password
        """
        import string

        length = max(length, self.min_length)

        # Character sets
        lowercase = string.ascii_lowercase
        uppercase = string.ascii_uppercase
        numbers = string.digits
        special = "!@#$%^&*"

        # Ensure at least one character from each required set
        password = []

        if self.require_lowercase:
            password.append(secrets.choice(lowercase))
        if self.require_uppercase:
            password.append(secrets.choice(uppercase))
        if self.require_numbers:
            password.append(secrets.choice(numbers))
        if self.require_special_chars:
            password.append(secrets.choice(special))

        # Fill remaining length with random characters from all sets
        all_chars = lowercase + uppercase + numbers + special
        for _ in range(length - len(password)):
            password.append(secrets.choice(all_chars))

        # Shuffle the password
        secrets.SystemRandom().shuffle(password)

        return "".join(password)

    def get_user_stats(self) -> Dict[str, Any]:
        """
        Get statistics for local users

        Returns:
            Dictionary with user statistics
        """
        try:
            from database import db

            total_users = User.query.filter_by(auth_provider=AuthProvider.LOCAL).count()
            active_users = User.query.filter_by(
                auth_provider=AuthProvider.LOCAL, status=AccountStatus.ACTIVE
            ).count()
            locked_users = User.query.filter_by(
                auth_provider=AuthProvider.LOCAL, status=AccountStatus.LOCKED
            ).count()
            disabled_users = User.query.filter_by(
                auth_provider=AuthProvider.LOCAL, status=AccountStatus.DISABLED
            ).count()

            # Users by role
            users_by_role = {}
            for role in UserRole:
                count = User.query.filter_by(
                    auth_provider=AuthProvider.LOCAL, role=role
                ).count()
                users_by_role[role.value] = count

            return {
                "total_users": total_users,
                "active_users": active_users,
                "locked_users": locked_users,
                "disabled_users": disabled_users,
                "users_by_role": users_by_role,
                "registration_enabled": self.allow_registration,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            self.logger.error(f"Failed to get user stats: {e}")
            return {"error": str(e)}

    def _is_password_expired(self, user: User) -> bool:
        """
        Check if user's password has expired

        Args:
            user: User to check

        Returns:
            True if password has expired
        """
        if (
            self.max_age_days is None or self.max_age_days <= 0
        ):  # None or 0 means no expiration
            return False

        if not user.password_changed_at:
            # If no password change date, consider it expired if max_age is set
            return True

        expiry_date = user.password_changed_at + timedelta(days=self.max_age_days)
        return datetime.now(timezone.utc) > expiry_date

    def supports_feature(self, feature: str) -> bool:
        """
        Check if local provider supports a specific feature

        Args:
            feature: Feature name to check

        Returns:
            True if feature is supported
        """
        local_features = [
            "authentication",
            "user_info",
            "session_management",
            "health_check",
            "password_change",
            "password_reset",
            "user_creation",
            "password_policy",
            "account_lockout",
        ]

        return feature in local_features
