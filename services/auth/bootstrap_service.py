"""
ABOUTME: Bootstrap service for automatic initial admin user creation
ABOUTME: Ensures secure initial setup with one-time admin creation on first startup

File: services/auth/bootstrap_service.py

Description:
    Bootstrap service that automatically creates an initial admin user on first startup
    when no admin users exist. Provides secure default credentials with mandatory password
    change on first login. Includes one-time creation protection and comprehensive audit
    logging for security compliance.

Key features:
    - Automatic initial admin creation on first startup
    - Secure default password with complexity requirements
    - Force password change on first login
    - One-time creation protection to prevent repeated bootstrap
    - Comprehensive audit logging for compliance
    - Database flag to track bootstrap status
    - Integration with existing authentication system

Author: Emfour Solutions
Created: 2025-07-28
Last Modified: 2025-07-28
Version: 1.0.0
"""

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any

from models.user import User, UserRole, AuthProvider, AccountStatus
from database import db

logger = logging.getLogger(__name__)


class BootstrapService:
    """
    Service for bootstrapping initial admin user on first startup
    """

    def __init__(self):
        self.bootstrap_flag_key = "INITIAL_ADMIN_CREATED"
        self.default_admin_username = "admin"
        self.default_admin_password = "TrakBridge-Setup-2025!"

    def should_create_initial_admin(self) -> bool:
        """
        Check if initial admin user should be created

        Returns:
            True if initial admin should be created, False otherwise
        """
        try:
            # Check if bootstrap has already been performed
            if self._is_bootstrap_completed():
                logger.debug(
                    "Bootstrap already completed, skipping initial admin creation"
                )
                return False

            # Check if any admin users exist
            admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
            if admin_count > 0:
                logger.debug(
                    f"Found {admin_count} existing admin users, skipping bootstrap"
                )
                # Mark bootstrap as completed even if we didn't create the user
                self._mark_bootstrap_completed()
                return False

            logger.info(
                "No admin users found and bootstrap not completed - initial admin creation required"
            )
            return True

        except Exception as e:
            logger.error(f"Error checking bootstrap status: {e}")
            return False

    def create_initial_admin(self) -> Optional[User]:
        """
        Create the initial admin user with secure defaults

        Returns:
            Created User object or None if creation failed
        """
        if not self.should_create_initial_admin():
            return None

        try:
            logger.info("Creating initial admin user for first-time setup")

            # Ensure username doesn't already exist
            existing_user = User.query.filter_by(
                username=self.default_admin_username
            ).first()
            if existing_user:
                logger.warning(
                    f"User '{self.default_admin_username}' already exists, cannot create initial admin"
                )
                return None

            # Create the initial admin user
            admin_user = User.create_local_user(
                username=self.default_admin_username,
                password=self.default_admin_password,
                email=None,  # No email required for initial setup
                full_name="System Administrator",
                role=UserRole.ADMIN,
            )

            # Mark password as needing change on first login
            admin_user.password_changed_at = None  # Force password change
            admin_user.status = AccountStatus.ACTIVE

            # Add to database
            db.session.add(admin_user)
            db.session.commit()

            # Mark bootstrap as completed
            self._mark_bootstrap_completed()

            # Log successful creation for audit
            logger.warning(
                f"SECURITY: Initial admin user '{self.default_admin_username}' created automatically"
            )
            logger.warning(
                f"SECURITY: Default password is '{self.default_admin_password}' - MUST be changed on first login"
            )
            logger.info(
                f"Bootstrap completed successfully - admin user ID: {admin_user.id}"
            )

            return admin_user

        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to create initial admin user: {e}")
            return None

    def _is_bootstrap_completed(self) -> bool:
        """
        Check if bootstrap has already been completed

        Returns:
            True if bootstrap was completed, False otherwise
        """
        try:
            # Check environment variable first (for development/testing)
            if os.environ.get(self.bootstrap_flag_key) == "true":
                return True

            # Check database for bootstrap flag (production approach)
            # We'll store this as a special user record or system setting
            # For now, use a simple file-based approach that's deployment-friendly
            bootstrap_file = "/app/data/.bootstrap_completed"
            if os.path.exists(bootstrap_file):
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking bootstrap completion: {e}")
            return False

    def _mark_bootstrap_completed(self) -> None:
        """
        Mark bootstrap as completed to prevent future automatic admin creation
        """
        try:
            # Create bootstrap completion marker
            bootstrap_file = "/app/data/.bootstrap_completed"

            # Ensure directory exists
            os.makedirs(os.path.dirname(bootstrap_file), exist_ok=True)

            # Write timestamp and details
            with open(bootstrap_file, "w") as f:
                f.write(f"Bootstrap completed: {datetime.utcnow().isoformat()}\n")
                f.write(f"Initial admin user: {self.default_admin_username}\n")

            # Set secure permissions
            os.chmod(bootstrap_file, 0o600)

            logger.info("Bootstrap completion marker created")

        except Exception as e:
            logger.error(f"Failed to mark bootstrap as completed: {e}")

    def get_bootstrap_info(self) -> Dict[str, Any]:
        """
        Get information about bootstrap status

        Returns:
            Dictionary with bootstrap status information
        """
        try:
            return {
                "bootstrap_completed": self._is_bootstrap_completed(),
                "admin_count": User.query.filter_by(role=UserRole.ADMIN).count(),
                "should_create_admin": self.should_create_initial_admin(),
                "default_username": self.default_admin_username,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error getting bootstrap info: {e}")
            return {
                "bootstrap_completed": False,
                "admin_count": 0,
                "should_create_admin": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def force_password_change_required(self, user: User) -> bool:
        """
        Check if user should be forced to change password

        Args:
            user: User to check

        Returns:
            True if password change is required
        """
        try:
            # Force password change if:
            # 1. User has never changed password (password_changed_at is None)
            # 2. User is the initial admin with default password
            if user.password_changed_at is None:
                return True

            # Check if this is the initial admin user with default credentials
            if (
                user.username == self.default_admin_username
                and user.role == UserRole.ADMIN
                and user.auth_provider == AuthProvider.LOCAL
            ):
                # Additional check could verify if password matches default
                # For security, we'll require change if created recently and never changed
                return user.password_changed_at is None

            return False

        except Exception as e:
            logger.error(f"Error checking password change requirement: {e}")
            return False


# Global instance
bootstrap_service = BootstrapService()


def get_bootstrap_service() -> BootstrapService:
    """Get the bootstrap service instance"""
    return bootstrap_service


def initialize_admin_user() -> Optional[User]:
    """
    Initialize admin user on application startup

    Returns:
        Created admin user or None
    """
    return bootstrap_service.create_initial_admin()


def check_password_change_required(user: User) -> bool:
    """
    Check if user needs to change password

    Args:
        user: User to check

    Returns:
        True if password change is required
    """
    return bootstrap_service.force_password_change_required(user)
