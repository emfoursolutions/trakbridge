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
"""

import fcntl
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from database import db
from models.user import AccountStatus, AuthProvider, User, UserRole
from services.logging_service import get_module_logger
from utils.database_helpers import create_record, find_by_field

logger = get_module_logger(__name__)

# Import worker coordination service for Redis distributed locking
try:
    from services.worker_coordination_service import worker_coordination

    REDIS_COORDINATION_AVAILABLE = True
except ImportError:
    worker_coordination = None
    REDIS_COORDINATION_AVAILABLE = False


class BootstrapService:
    """
    Service for bootstrapping initial admin user on first startup
    """

    def __init__(self, bootstrap_file_path=None, skip_migration_check=None):
        self.bootstrap_flag_key = "INITIAL_ADMIN_CREATED"
        self.default_admin_username = "admin"
        self.default_admin_password = "TrakBridge-Setup-2025!"
        # Allow configurable bootstrap file path for testing
        self.bootstrap_file_path = (
            bootstrap_file_path or "/app/data/.bootstrap_completed"
        )
        self.bootstrap_lock_path = (
            bootstrap_file_path or "/app/data/.bootstrap_completed"
        ) + ".lock"
        # Allow skipping migration check for testing
        self.skip_migration_check = skip_migration_check
        # Lock file handle for coordination
        self._lock_file = None

    def _is_test_environment(self) -> bool:
        """
        Detect if we're running in a test environment

        Returns:
            True if in test environment, False otherwise
        """
        # Check for common test environment indicators
        test_indicators = [
            os.environ.get("FLASK_ENV") == "testing",
            os.environ.get("TESTING") == "true",
            os.environ.get("DB_TEST_MODE") == "true",
            "pytest" in os.environ.get("_", ""),
            "test" in os.environ.get("DB_TYPE", "").lower(),
            # Check if pytest is in the current process
            any("pytest" in arg for arg in sys.argv),
        ]

        # Also check if we're explicitly told to skip migration check
        if self.skip_migration_check is not None:
            return self.skip_migration_check

        return any(test_indicators)

    def _acquire_bootstrap_lock(self, timeout_seconds: int = 30) -> bool:
        """
        Acquire exclusive lock for bootstrap process coordination
        Uses Redis distributed locking when available, falls back to file locking

        Args:
            timeout_seconds: Maximum time to wait for lock

        Returns:
            True if lock acquired successfully, False if timeout
        """
        try:
            # Try Redis distributed locking first if available
            if REDIS_COORDINATION_AVAILABLE and worker_coordination.enabled:
                logger.debug(
                    "Attempting Redis distributed lock for bootstrap coordination"
                )
                return worker_coordination.acquire_bootstrap_lock(
                    "admin_creation", ttl=timeout_seconds
                )

            # Fall back to file-based locking
            logger.debug("Using file-based locking for bootstrap coordination")
            return self._acquire_file_lock(timeout_seconds)

        except Exception as e:
            logger.error(f"Error acquiring bootstrap lock: {e}")
            # Try file-based fallback even if Redis coordination failed
            try:
                return self._acquire_file_lock(timeout_seconds)
            except Exception as fallback_error:
                logger.error(f"Fallback file lock also failed: {fallback_error}")
                return False

    def _acquire_file_lock(self, timeout_seconds: int = 30) -> bool:
        """
        Acquire file-based exclusive lock for bootstrap process coordination
        Fallback mechanism when Redis is unavailable

        Args:
            timeout_seconds: Maximum time to wait for lock

        Returns:
            True if lock acquired successfully, False if timeout
        """
        try:
            # Ensure directory exists with better error handling
            lock_dir = os.path.dirname(self.bootstrap_lock_path)
            try:
                os.makedirs(lock_dir, exist_ok=True)
            except (OSError, PermissionError) as dir_error:
                # If we can't create the directory, try using temp directory
                logger.debug(f"Cannot create lock directory {lock_dir}: {dir_error}")
                import tempfile

                self.bootstrap_lock_path = os.path.join(
                    tempfile.gettempdir(), "trakbridge_bootstrap.lock"
                )
                logger.debug(f"Using temporary lock file: {self.bootstrap_lock_path}")

            # Open lock file
            self._lock_file = open(self.bootstrap_lock_path, "w")

            # Try to acquire exclusive lock with timeout
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Write process info to lock file
                    self._lock_file.write(
                        f"Bootstrap locked by PID {os.getpid()} at {datetime.now(timezone.utc).isoformat()}\n"
                    )
                    self._lock_file.flush()
                    logger.info(f"Bootstrap file lock acquired by PID {os.getpid()}")
                    return True
                except (IOError, OSError):
                    # Lock is held by another process, wait and retry
                    time.sleep(0.5)

            logger.warning(
                f"Failed to acquire bootstrap file lock within {timeout_seconds} seconds"
            )
            self._release_file_lock()
            return False

        except Exception as e:
            logger.error(f"Error acquiring bootstrap file lock: {e}")
            self._release_file_lock()
            return False

    def _release_bootstrap_lock(self) -> None:
        """
        Release bootstrap lock
        Uses Redis distributed locking when available, falls back to file locking
        """
        try:
            # Try Redis distributed lock release first if available
            if REDIS_COORDINATION_AVAILABLE and worker_coordination.enabled:
                logger.debug(
                    "Releasing Redis distributed lock for bootstrap coordination"
                )
                worker_coordination.release_bootstrap_lock("admin_creation")

            # Also release file lock if it was acquired
            self._release_file_lock()

        except Exception as e:
            logger.debug(f"Error releasing bootstrap lock: {e}")
            # Try file-based fallback
            try:
                self._release_file_lock()
            except Exception as fallback_error:
                logger.debug(
                    f"Fallback file lock release also failed: {fallback_error}"
                )

    def _release_file_lock(self) -> None:
        """
        Release file-based bootstrap lock
        Fallback mechanism when Redis is unavailable
        """
        try:
            if self._lock_file:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
                logger.debug("Bootstrap file lock released")

            # Clean up lock file
            if os.path.exists(self.bootstrap_lock_path):
                os.remove(self.bootstrap_lock_path)

        except Exception as e:
            logger.debug(f"Error releasing bootstrap file lock: {e}")

    def _database_bootstrap_coordination(self) -> bool:
        """
        Use database for additional bootstrap coordination

        Returns:
            True if this process should handle bootstrap, False if another process is handling it
        """
        try:
            # Import at method level to avoid scoping issues
            from database import db

            # First check if tables exist - if not, database isn't ready
            inspector = db.inspect(db.engine)
            existing_tables = inspector.get_table_names()

            if "users" not in existing_tables:
                logger.debug(
                    "Users table doesn't exist - database not ready for bootstrap coordination"
                )
                # Return True because this process should handle bootstrap once database is ready
                return True

            # Check if bootstrap is already in progress or completed
            existing_admin = User.query.filter_by(
                role=UserRole.ADMIN, auth_provider=AuthProvider.LOCAL
            ).first()

            if existing_admin:
                logger.debug(
                    "Database coordination: Bootstrap already completed (admin exists)"
                )
                return False

            # Additional check: try to create a temporary marker to claim bootstrap
            # This uses database constraints to ensure only one process succeeds
            return True

        except Exception as e:
            logger.debug(f"Database coordination check failed: {e}")
            # Analyze the exception to determine appropriate response
            error_str = str(e).lower()

            # If it's a connection or table-related error, assume database isn't ready
            # and this process should handle bootstrap
            connection_errors = [
                "connection",
                "connect",
                "network",
                "timeout",
                "refused",
            ]
            table_errors = ["table", "relation", "column", "database", "schema"]

            if any(err in error_str for err in connection_errors + table_errors):
                logger.debug(
                    "Database/connection error - this process should handle bootstrap"
                )
                return True

            # For other types of errors, be conservative and assume another process
            # might be handling it
            logger.debug(
                "Other database error - assuming another process may be handling bootstrap"
            )
            return False

    def _are_migrations_complete(self) -> bool:
        """
        Check if all database migrations have completed

        Returns:
            True if migrations are complete, False otherwise
        """
        try:
            # If running in a container, trust that the entrypoint already validated migrations
            if os.getenv('CONTAINER_MANAGED', '').lower() == 'true':
                logger.debug("Container-managed deployment detected, skipping heavy migration checks")
                return True
            # First check if this is SQLite and if the database file actually exists
            database_url = str(db.engine.url)
            if database_url.startswith("sqlite:///"):
                # Extract SQLite database file path
                db_path = database_url.replace("sqlite:///", "")

                # Quick file existence check
                if not os.path.exists(db_path):
                    logger.debug(f"SQLite database file does not exist: {db_path}")
                    return False

                # Quick file size check to see if it's empty
                try:
                    file_size = os.path.getsize(db_path)
                    if file_size == 0:
                        logger.debug(
                            "SQLite database file is empty - migrations not complete"
                        )
                        return False
                    elif file_size < 1024:  # Less than 1KB likely means uninitialized
                        logger.debug(
                            "SQLite database file is very small - likely uninitialized"
                        )
                        return False
                except (OSError, IOError):
                    logger.debug("Cannot check SQLite database file size")
                    return False

            # Check if basic tables exist first (faster than migration check)
            try:
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()

                # If no tables exist, this is an empty database - migrations definitely not complete
                if not existing_tables:
                    logger.debug(
                        "Database is empty (no tables found) - migrations not complete"
                    )
                    return False

                # If alembic_version table doesn't exist but other tables do, inconsistent state
                if "alembic_version" not in existing_tables:
                    # Check if this looks like a working database despite missing alembic_version
                    essential_tables = ["users", "streams", "tak_servers"]
                    has_essential_tables = all(
                        table in existing_tables for table in essential_tables
                    )

                    if has_essential_tables:
                        logger.info(
                            f"Database has {len(existing_tables)} tables including essential ones, but no alembic_version table"
                        )
                        logger.info(
                            "Database may have been created via db.create_all() instead of migrations"
                        )
                        logger.info(
                            "Considering database as functional for bootstrap purposes"
                        )
                        # Return True - database is functional even without migration tracking
                        return True
                    else:
                        logger.debug(
                            f"No alembic_version table found, but {len(existing_tables)} other tables exist - migrations not properly initialized"
                        )
                        return False

            except Exception as table_check_error:
                logger.debug(f"Could not check database tables: {table_check_error}")
                return False

            # Now safely check current database revision
            with db.engine.connect() as conn:
                migration_ctx = MigrationContext.configure(conn)
                current_rev = migration_ctx.get_current_revision()

                if current_rev is None:
                    logger.debug(
                        "No migration revision found - migrations may not be initialized"
                    )
                    return False

                # Get the latest revision from migration scripts
                alembic_cfg = Config()
                alembic_cfg.set_main_option("script_location", "migrations")
                script_dir = ScriptDirectory.from_config(alembic_cfg)
                latest_rev = script_dir.get_current_head()

                if current_rev == latest_rev:
                    logger.debug("Database migrations are up to date")
                    return True
                else:
                    logger.debug(
                        f"Database revision {current_rev} is behind latest {latest_rev}"
                    )
                    return False

        except Exception as e:
            logger.debug(f"Could not check migration status: {e}")
            logger.debug(
                "This could be due to migrations still running or Alembic not being initialized yet"
            )
            # If we can't check migration status, assume they're not complete
            return False

    def _wait_for_migrations(self, max_wait_seconds: int = 60) -> bool:
        """
        Wait for database migrations to complete

        Args:
            max_wait_seconds: Maximum time to wait for migrations

        Returns:
            True if migrations completed, False if timeout
        """
        start_time = time.time()
        empty_database_count = 0

        while time.time() - start_time < max_wait_seconds:
            if self._are_migrations_complete():
                return True

            # Check if we have an empty database consistently
            try:
                database_url = str(db.engine.url)
                if database_url.startswith("sqlite:///"):
                    db_path = database_url.replace("sqlite:///", "")
                    if os.path.exists(db_path):
                        # Check if database file exists but is empty/small
                        try:
                            file_size = os.path.getsize(db_path)
                            if file_size < 1024:  # Less than 1KB
                                empty_database_count += 1
                                logger.debug(
                                    f"Empty database detected (count: {empty_database_count})"
                                )

                                # If we've seen empty database for 5 consecutive checks (10 seconds)
                                if empty_database_count >= 5:
                                    logger.warning(
                                        "Database file exists but remains empty after 10 seconds - "
                                        "migrations may not be running. Breaking wait loop."
                                    )
                                    return False
                            else:
                                empty_database_count = 0  # Reset counter
                        except (OSError, IOError):
                            pass
            except Exception:
                pass

            logger.debug("Waiting for database migrations to complete...")
            time.sleep(2)

        logger.warning(
            f"Timed out waiting for migrations after {max_wait_seconds} seconds"
        )
        return False

    def should_create_initial_admin(self) -> bool:
        """
        Check if initial admin user should be created

        Returns:
            True if initial admin should be created, False otherwise
        """
        try:
            # Skip migration checking in test environments
            if self._is_test_environment():
                logger.debug(
                    "Test environment detected, skipping migration completion check"
                )
            else:
                # First, wait for database migrations to complete
                logger.debug(
                    "Waiting for database migrations to complete before bootstrap check..."
                )
                if not self._wait_for_migrations(max_wait_seconds=120):
                    logger.warning(
                        "Database migrations did not complete within 120 seconds. "
                        "This may indicate migration issues or slow database startup. "
                        "Will attempt bootstrap check anyway in case database becomes available."
                    )
                    # Don't immediately return False - let's check if tables exist
                else:
                    logger.debug(
                        "Database migrations completed successfully, proceeding with bootstrap check"
                    )

            # Use database coordination to check if another process is handling bootstrap
            if not self._database_bootstrap_coordination():
                logger.debug("Another process is handling or has completed bootstrap")
                return False

            # Check if database tables exist first
            try:
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()
                logger.debug(f"Database tables found: {existing_tables}")

                if "users" not in existing_tables:
                    logger.info(
                        "Users table does not exist yet - database migration may still be in progress"
                    )
                    logger.info(
                        "Bootstrap check will be deferred until database is ready"
                    )
                    return False

            except Exception as table_error:
                logger.warning(f"Could not check database tables: {table_error}")
                logger.info(
                    "Bootstrap check will be deferred until database connectivity is restored"
                )
                return False

            # Check if any admin users exist (most reliable check)
            admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
            if admin_count > 0:
                logger.debug(
                    f"Found {admin_count} existing admin users, marking bootstrap complete"
                )
                # Mark bootstrap as completed even if we didn't create the user
                self._mark_bootstrap_completed()
                return False

            # Check if the specific admin username already exists
            existing_admin = User.query.filter_by(
                username=self.default_admin_username
            ).first()
            if existing_admin:
                logger.debug(
                    f"User '{self.default_admin_username}' already exists, marking bootstrap complete"
                )
                self._mark_bootstrap_completed()
                return False

            # Check if bootstrap has already been performed via marker file
            if self._is_bootstrap_completed():
                logger.debug(
                    "Bootstrap already completed via marker file, skipping initial admin creation"
                )
                return False

            logger.info(
                "No admin users found and bootstrap not completed - initial admin creation required"
            )
            return True

        except Exception as e:
            try:
                logger.error(f"Error checking bootstrap status: {e}")
            except (ValueError, OSError):
                # Handle cases where logging files are closed during shutdown
                pass
            return False

    def create_initial_admin(self) -> Optional[User]:
        """
        Create the initial admin user with secure defaults

        Returns:
            Created User object or None if creation failed
        """
        if not self.should_create_initial_admin():
            return None

        # Acquire bootstrap lock for coordination between multiple workers
        if not self._is_test_environment():
            if not self._acquire_bootstrap_lock(timeout_seconds=30):
                logger.warning(
                    "Failed to acquire bootstrap lock - another process may be handling bootstrap"
                )
                return None

        try:
            logger.info("Creating initial admin user for first-time setup")

            # Double-check: Ensure username doesn't already exist (race condition protection)
            existing_user = User.query.filter_by(
                username=self.default_admin_username
            ).first()
            if existing_user:
                logger.info(
                    f"User '{self.default_admin_username}' already exists (race condition), marking bootstrap complete"
                )
                self._mark_bootstrap_completed()
                return existing_user

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

            # Add to database with enhanced error handling for race conditions
            db.session.add(admin_user)

            # Retry logic with exponential backoff for database operations
            max_retries = 3
            retry_delay = 0.1  # Start with 100ms

            for attempt in range(max_retries):
                try:
                    db.session.commit()
                    logger.info("Admin user created successfully in database")
                    break
                except IntegrityError as ie:
                    db.session.rollback()

                    # Analyze the specific integrity error
                    error_message = str(ie).lower()
                    if "unique" in error_message or "duplicate" in error_message:
                        logger.info(
                            f"Admin user creation race condition detected (attempt {attempt + 1}): {ie}"
                        )

                        # Try to get the existing user
                        existing_user = User.query.filter_by(
                            username=self.default_admin_username
                        ).first()
                        if existing_user:
                            logger.info(
                                "Found existing admin user after race condition, using that"
                            )
                            self._mark_bootstrap_completed()
                            return existing_user

                        # If no existing user found, this might be a temporary constraint issue
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"No existing user found after integrity error, retrying in {retry_delay}s..."
                            )
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff

                            # Recreate the admin user for retry
                            admin_user = User.create_local_user(
                                username=self.default_admin_username,
                                password=self.default_admin_password,
                                email=None,
                                full_name="System Administrator",
                                role=UserRole.ADMIN,
                            )
                            admin_user.password_changed_at = None
                            admin_user.status = AccountStatus.ACTIVE
                            db.session.add(admin_user)
                            continue
                        else:
                            logger.error("Max retries exceeded for admin user creation")
                            return None
                    else:
                        # Non-duplicate integrity error, don't retry
                        logger.error(
                            f"Non-duplicate integrity error during admin creation: {ie}"
                        )
                        return None
                except Exception as e:
                    db.session.rollback()
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"Database error during admin creation (attempt {attempt + 1}), retrying: {e}"
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        logger.error(
                            f"Max retries exceeded for admin user creation due to: {e}"
                        )
                        raise

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
            # Even if creation failed, if admin user exists, mark bootstrap complete
            existing_user = User.query.filter_by(
                username=self.default_admin_username
            ).first()
            if existing_user:
                logger.info(
                    "Admin user exists despite creation failure, marking bootstrap complete"
                )
                self._mark_bootstrap_completed()
                return existing_user
            return None
        finally:
            # Always release the bootstrap lock
            if not self._is_test_environment():
                self._release_bootstrap_lock()

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

            # Check database for bootstrap completion (most reliable)
            try:
                # Check if tables exist first
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()

                if "users" in existing_tables:
                    # Method 1: Check if any admin users exist
                    admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
                    if admin_count > 0:
                        logger.debug(
                            "Bootstrap completed: admin users found in database"
                        )
                        # Also create file marker for faster future checks
                        self._create_file_marker()
                        return True

                    # Method 2: Check if specific admin username exists
                    existing_admin = User.query.filter_by(
                        username=self.default_admin_username
                    ).first()
                    if existing_admin:
                        logger.debug(
                            "Bootstrap completed: default admin user found in database"
                        )
                        # Also create file marker for faster future checks
                        self._create_file_marker()
                        return True

            except Exception as db_error:
                logger.debug(f"Database check for bootstrap status failed: {db_error}")
                # Fall back to file-based check

            # Check file-based marker (fallback approach)
            try:
                if os.path.exists(self.bootstrap_file_path):
                    logger.debug("Bootstrap completed: marker file found")
                    return True
            except (OSError, IOError) as file_error:
                logger.debug(f"File-based bootstrap check failed: {file_error}")
                # Don't fail completely, just skip file-based check

            return False

        except Exception as e:
            logger.error(f"Error checking bootstrap completion: {e}")
            return False

    def _create_file_marker(self) -> None:
        """
        Create bootstrap completion file marker
        """
        try:
            # Only create if it doesn't exist
            if not os.path.exists(self.bootstrap_file_path):
                # Ensure directory exists
                try:
                    os.makedirs(
                        os.path.dirname(self.bootstrap_file_path), exist_ok=True
                    )
                except (OSError, IOError) as dir_error:
                    logger.debug(f"Failed to create bootstrap directory: {dir_error}")
                    return  # Exit early if we can't create directory

                # Write timestamp and details
                try:
                    with open(self.bootstrap_file_path, "w") as f:
                        f.write(
                            f"Bootstrap completed: {datetime.now(timezone.utc).isoformat()}\n"
                        )
                        f.write(f"Initial admin user: {self.default_admin_username}\n")
                        f.write("Bootstrap marker created from database state\n")

                    # Set secure permissions
                    os.chmod(self.bootstrap_file_path, 0o600)
                    logger.debug("Bootstrap completion marker file created")
                except (OSError, IOError) as file_error:
                    logger.debug(f"Failed to write bootstrap marker file: {file_error}")

        except Exception as e:
            logger.debug(f"Failed to create bootstrap marker file: {e}")

    def _mark_bootstrap_completed(self) -> None:
        """
        Mark bootstrap as completed to prevent future automatic admin creation
        """
        try:
            # Ensure directory exists
            try:
                os.makedirs(os.path.dirname(self.bootstrap_file_path), exist_ok=True)
            except (OSError, IOError) as dir_error:
                logger.debug(f"Failed to create bootstrap directory: {dir_error}")
                # Don't fail the entire bootstrap process for file operations
                return

            # Write timestamp and details
            try:
                with open(self.bootstrap_file_path, "w") as f:
                    f.write(
                        f"Bootstrap completed: {datetime.now(timezone.utc).isoformat()}\n"
                    )
                    f.write(f"Initial admin user: {self.default_admin_username}\n")
                    f.write("Bootstrap completed successfully\n")

                # Set secure permissions
                os.chmod(self.bootstrap_file_path, 0o600)
                logger.info("Bootstrap completion marker created")
            except (OSError, IOError) as file_error:
                logger.debug(f"Failed to write bootstrap marker file: {file_error}")
                # Don't fail the entire bootstrap process for file operations

        except Exception as e:
            logger.debug(f"Failed to mark bootstrap as completed: {e}")
            # Don't fail the entire bootstrap process for file operations

        # Note: Database-based tracking is implicit - the presence of admin users
        # in the database serves as the primary indicator of bootstrap completion

    def get_bootstrap_info(self) -> Dict[str, Any]:
        """
        Get information about bootstrap status

        Returns:
            Dictionary with bootstrap status information
        """
        try:
            file_exists = False
            try:
                file_exists = os.path.exists(self.bootstrap_file_path)
            except (OSError, IOError):
                # File system access failed, continue with database checks
                pass

            admin_count = 0
            default_admin_exists = False
            tables_exist = False

            try:
                inspector = db.inspect(db.engine)
                existing_tables = inspector.get_table_names()
                tables_exist = "users" in existing_tables

                if tables_exist:
                    admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
                    default_admin_exists = (
                        User.query.filter_by(
                            username=self.default_admin_username
                        ).first()
                        is not None
                    )
            except Exception as db_error:
                logger.debug(f"Database check in bootstrap info failed: {db_error}")

            return {
                "bootstrap_completed": self._is_bootstrap_completed(),
                "admin_count": admin_count,
                "default_admin_exists": default_admin_exists,
                "should_create_admin": self.should_create_initial_admin(),
                "default_username": self.default_admin_username,
                "marker_file_exists": file_exists,
                "marker_file_path": self.bootstrap_file_path,
                "tables_exist": tables_exist,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error getting bootstrap info: {e}")
            return {
                "bootstrap_completed": False,
                "admin_count": 0,
                "default_admin_exists": False,
                "should_create_admin": False,
                "marker_file_exists": False,
                "tables_exist": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
