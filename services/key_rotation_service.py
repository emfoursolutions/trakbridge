"""
File: services/key_rotation_service.py

Description:
    Enterprise-grade key rotation service providing secure encryption key management
    with automated database backup and web interface integration. This service handles
    the critical process of rotating encryption keys while maintaining data integrity
    and providing comprehensive logging and monitoring capabilities.

Key features:
    - Multi-database backup support with PostgreSQL, MySQL, and SQLite compatibility
    - Automated database backup creation before key rotation with size tracking
    - Thread-safe key rotation process with background execution and progress monitoring
    - Comprehensive key storage detection supporting environment variables and file-based storage
    - Secure key validation and testing before rotation to prevent data corruption
    - Real-time rotation progress logging with timestamp tracking and error reporting
    - Automatic key storage method detection and seamless key file management
    - Application restart detection with deployment-specific restart instructions
    - Flask application context management for background thread operations
    - Comprehensive error handling with rollback capabilities and audit trail

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

import logging
# Standard library imports
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Third-party imports
from flask import current_app

# Local application imports
from services.encryption_service import (EncryptionService,
                                         get_encryption_service)
from utils.security_helpers import (SecureSubprocessRunner,
                                    create_secure_backup_path,
                                    secure_file_permissions,
                                    validate_backup_directory,
                                    validate_database_params,
                                    validate_safe_path)

# Module level logging
logger = logging.getLogger(__name__)


class KeyRotationService:
    """Service for rotating encryption keys with database backup and web interface"""

    def __init__(self):
        self.rotation_log: List[Dict[str, Any]] = []
        self.is_rotating = False
        self.rotation_thread: Optional[threading.Thread] = None

    def get_database_info(self, app_context=None) -> Dict[str, Any]:
        """Get database type and connection information"""

        def _get_db_info():
            try:
                from database import db

                # Get database URI
                db_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")

                # Determine database type
                if "sqlite" in db_uri.lower():
                    db_type = "sqlite"
                    db_path = db_uri.replace("sqlite:///", "")
                    if db_path.startswith("/"):
                        db_path = db_path
                    else:
                        # Relative path, make it absolute
                        db_path = os.path.join(os.getcwd(), db_path)
                elif "mysql" in db_uri.lower():
                    db_type = "mysql"
                    db_path = db_uri
                elif "postgresql" in db_uri.lower():
                    db_type = "postgresql"
                    db_path = db_uri
                else:
                    db_type = "unknown"
                    db_path = db_uri

                return {
                    "type": db_type,
                    "uri": db_uri,
                    "path": db_path,
                    "engine": str(db.engine),
                }
            except Exception as e:
                logger.error(f"Error getting database info: {e}")
                return {
                    "type": "unknown",
                    "uri": "unknown",
                    "path": "unknown",
                    "error": str(e),
                }

        # If we have an app context, use it
        if app_context:
            with app_context:
                return _get_db_info()
        else:
            return _get_db_info()

    def create_database_backup(self, app_context=None) -> Dict[str, Any]:
        """Create a backup of the database based on its type"""
        try:
            db_info = self.get_database_info(app_context)
            db_type = db_info["type"]

            # Create backup directory
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if db_type == "sqlite":
                return self._backup_sqlite(db_info, backup_dir, timestamp)
            elif db_type == "mysql":
                return self._backup_mysql(db_info, backup_dir, timestamp)
            elif db_type == "postgresql":
                return self._backup_postgresql(db_info, backup_dir, timestamp)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported database type: {db_type}",
                    "backup_path": None,
                }

        except Exception as e:
            logger.error(f"Error creating database backup: {e}")
            return {"success": False, "error": str(e), "backup_path": None}

    @staticmethod
    def _backup_sqlite(
        db_info: Dict[str, Any], backup_dir: Path, timestamp: str
    ) -> Dict[str, Any]:
        """Backup SQLite database"""
        try:
            db_path = db_info["path"]
            backup_path = backup_dir / f"trakbridge_sqlite_{timestamp}.db"

            # Copy the database file
            shutil.copy2(db_path, backup_path)

            return {
                "success": True,
                "backup_path": str(backup_path),
                "size": backup_path.stat().st_size,
                "type": "sqlite",
            }
        except Exception as e:
            return {"success": False, "error": str(e), "backup_path": None}

    @staticmethod
    def _backup_mysql(
        db_info: Dict[str, Any], backup_dir: Path, timestamp: str
    ) -> Dict[str, Any]:
        """Backup MySQL database with security validation"""
        try:
            # Validate backup directory
            if not validate_backup_directory(backup_dir):
                raise ValueError("Invalid backup directory")

            # Extract and validate database name from URI
            uri = db_info["uri"]
            db_name = uri.split("/")[-1].split("?")[0]
            if not db_name or not db_name.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Invalid database name")

            # Create secure backup path
            filename = f"trakbridge_mysql_{timestamp}.sql"
            backup_path = create_secure_backup_path(backup_dir, filename)

            # Initialize secure subprocess runner
            runner = SecureSubprocessRunner(["mysqldump"])

            # Build base command
            cmd = [
                "mysqldump",
                "--single-transaction",
                "--routines",
                "--triggers",
                db_name,
            ]

            # Handle credentials securely if in URI
            env = os.environ.copy()
            if "@" in uri:
                try:
                    # Extract and validate credentials
                    auth_host = uri.split("://")[1].split("/")[0]
                    if ":" in auth_host.split("@")[0]:
                        user_pass = auth_host.split("@")[0]
                        user, password = user_pass.split(":", 1)

                        # Validate credentials
                        db_params = validate_database_params({"username": user})

                        # Use environment variable for password (safer than command line)
                        env["MYSQL_PWD"] = password
                        cmd.extend(["-u", db_params["username"]])
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse database credentials: {e}")
                    raise ValueError("Invalid database URI format")

            # Validate command before execution
            if not runner.validate_command(cmd):
                raise ValueError("Command failed security validation")

            with open(backup_path, "w") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    shell=False,
                )

            # Set secure file permissions on backup file
            secure_file_permissions(backup_path, 0o600)

            if result.returncode == 0:
                return {
                    "success": True,
                    "backup_path": str(backup_path),
                    "size": backup_path.stat().st_size,
                    "type": "mysql",
                }
            else:
                return {
                    "success": False,
                    "error": f"mysqldump failed: {result.stderr}",
                    "backup_path": None,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "backup_path": None}

    @staticmethod
    def _backup_postgresql(
        db_info: Dict[str, Any], backup_dir: Path, timestamp: str
    ) -> Dict[str, Any]:
        """Backup PostgreSQL database with security validation"""
        try:
            # Validate backup directory
            if not validate_backup_directory(backup_dir):
                raise ValueError("Invalid backup directory")

            # Extract and validate database name from URI
            uri = db_info["uri"]
            db_name = uri.split("/")[-1]
            if not db_name or not db_name.replace("_", "").replace("-", "").isalnum():
                raise ValueError("Invalid database name")

            # Create secure backup path
            filename = f"trakbridge_postgresql_{timestamp}.sql"
            backup_path = create_secure_backup_path(backup_dir, filename)

            # Use pg_dump
            cmd = [
                "pg_dump",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                db_name,
            ]

            # Handle credentials securely if in URI
            env = os.environ.copy()
            if "@" in uri:
                try:
                    # Extract and validate credentials
                    auth_host = uri.split("://")[1].split("/")[0]
                    if ":" in auth_host.split("@")[0]:
                        user_pass = auth_host.split("@")[0]
                        user, password = user_pass.split(":", 1)

                        # Validate credentials
                        db_params = validate_database_params({"username": user})

                        cmd.extend(["-U", db_params["username"]])
                        # Set password environment variable
                        env["PGPASSWORD"] = password
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse database credentials: {e}")
                    raise ValueError("Invalid database URI format")

            # Initialize secure subprocess runner and validate command
            runner = SecureSubprocessRunner(["pg_dump"])
            if not runner.validate_command(cmd):
                raise ValueError("Command failed security validation")

            with open(backup_path, "w") as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    shell=False,
                )

            # Set secure file permissions on backup file
            secure_file_permissions(backup_path, 0o600)

            if result.returncode == 0:
                return {
                    "success": True,
                    "backup_path": str(backup_path),
                    "size": backup_path.stat().st_size,
                    "type": "postgresql",
                }
            else:
                return {
                    "success": False,
                    "error": f"pg_dump failed: {result.stderr}",
                    "backup_path": None,
                }

        except Exception as e:
            return {"success": False, "error": str(e), "backup_path": None}

    def get_key_storage_info(self, app_context=None) -> Dict[str, Any]:
        """Detect current key storage method"""

        def _get_storage_info():
            try:
                # Check environment variable
                if os.environ.get("TB_MASTER_KEY"):
                    return {
                        "method": "environment_variable",
                        "name": "TB_MASTER_KEY",
                        "secure": True,
                    }

                # Check key file
                app_root = current_app.root_path
                key_file_paths = [
                    os.path.join(app_root, "secrets", "tb_master_key"),
                ]

                for key_file_path in key_file_paths:
                    if os.path.exists(key_file_path):
                        return {"method": "file", "path": key_file_path, "secure": True}

                return {
                    "method": "generated",
                    "secure": False,
                    "warning": "Using generated key - not persistent",
                }

            except Exception as e:
                return {"method": "unknown", "error": str(e), "secure": False}

        # If we have an app context, use it
        if app_context:
            with app_context:
                return _get_storage_info()
        else:
            return _get_storage_info()

    def update_key_storage(self, new_key: str, app_context=None) -> Dict[str, Any]:
        """Update key storage method with new key"""

        def _update_storage():
            try:
                storage_info = self.get_key_storage_info()
                method = storage_info.get("method")

                if method == "environment_variable":
                    return {
                        "success": True,
                        "method": "environment_variable",
                        "instruction": f"Set environment variable: "
                        f'export TB_MASTER_KEY="{new_key}"',
                    }

                elif method == "file":
                    key_file_path = storage_info.get("path")
                    if key_file_path:
                        # Create directory if it doesn't exist
                        os.makedirs(os.path.dirname(key_file_path), exist_ok=True)

                        # Validate path security before writing
                        allowed_dirs = [
                            os.path.dirname(key_file_path),
                            os.path.join(current_app.root_path, "secrets"),
                        ]
                        if not validate_safe_path(key_file_path, allowed_dirs):
                            return {"success": False, "error": "Invalid key file path"}

                        # Write new key to file
                        with open(key_file_path, "w") as f:
                            f.write(new_key)

                        # Set secure file permissions
                        secure_file_permissions(key_file_path, 0o600)

                        return {
                            "success": True,
                            "method": "file",
                            "path": key_file_path,
                            "message": "Key file updated successfully",
                        }

                else:
                    # Create key file as default
                    app_root = current_app.root_path
                    key_file_path = os.path.join(app_root, "secrets", "tb_master_key")
                    os.makedirs(os.path.dirname(key_file_path), exist_ok=True)

                    # Validate path security before writing
                    allowed_dirs = [os.path.join(current_app.root_path, "secrets")]
                    if not validate_safe_path(key_file_path, allowed_dirs):
                        return {"success": False, "error": "Invalid key file path"}

                    with open(key_file_path, "w") as f:
                        f.write(new_key)

                    # Set secure file permissions
                    secure_file_permissions(key_file_path, 0o600)

                    return {
                        "success": True,
                        "method": "file",
                        "path": key_file_path,
                        "message": "Created new key file",
                    }

            except Exception as e:
                return {"success": False, "error": str(e)}

        # If we have an app context, use it
        if app_context:
            with app_context:
                return _update_storage()
        else:
            return _update_storage()

    def start_rotation(
        self, new_key: str, create_backup: bool = True, flask_app=None
    ) -> Dict[str, Any]:
        """Start key rotation in a background thread"""
        if self.is_rotating:
            return {"success": False, "error": "Key rotation already in progress"}

        self.is_rotating = True
        self.rotation_log = []

        # Get the Flask app instance for the background thread
        if flask_app is None:
            try:
                # Try to get the current app and use its stored app_context_factory
                flask_app = current_app._get_current_object()
            except (RuntimeError, AttributeError):
                # If we're already outside of app context, we need the app passed in
                return {
                    "success": False,
                    "error": "Flask app instance required when called outside of app context",
                }

        # Get the app context factory from the Flask app
        app_context_factory = getattr(flask_app, "app_context_factory", None)
        if app_context_factory is None:
            return {
                "success": False,
                "error": "Flask app does not have app_context_factory configured",
            }

        # Pre-fetch all data that requires app context before starting the thread
        try:
            db_info = self.get_database_info()
            storage_info = self.get_key_storage_info()
            app_root = current_app.root_path
            # db_config = current_app.config.copy()
        except RuntimeError:
            return {
                "success": False,
                "error": "Must be called within Flask application context",
            }

        def rotation_worker():
            try:
                # Set up Flask application context for the background thread using the factory
                with app_context_factory():
                    self._log("Starting key rotation process...")

                    # Step 1: Create backup
                    if create_backup:
                        self._log("Creating database backup...")
                        backup_result = self._create_database_backup_with_data(db_info)
                        if backup_result["success"]:
                            self._log(f"Backup created: {backup_result['backup_path']}")
                        else:
                            self._log(f"Backup failed: {backup_result['error']}")
                            return None

                    # Step 2: Test new key
                    self._log("Testing new encryption key...")
                    test_service = EncryptionService(new_key)
                    test_encrypted = test_service.encrypt_value("test")
                    test_decrypted = test_service.decrypt_value(test_encrypted)

                    if test_decrypted != "test":
                        self._log("New key test failed")
                        return None

                    self._log("New key test successful")

                    # Step 3: Rotate database keys
                    self._log("Rotating database keys...")
                    encryption_service = get_encryption_service()
                    result = encryption_service.rotate_database_keys(new_key)

                    if result["success"]:
                        self._log(f"{result['message']}")
                        self._log(
                            f"Rotated {result['rotated_count']} certificate passwords"
                        )

                        if result["errors"]:
                            for error in result["errors"]:
                                self._log(f"Error: {error}")
                    else:
                        self._log(
                            f"Key rotation failed: {result.get('error', 'Unknown error')}"
                        )
                        return None

                    # Step 4: Update key storage
                    self._log("Updating key storage...")
                    storage_result = self._update_key_storage_with_data(
                        new_key, storage_info, app_root
                    )
                    if storage_result["success"]:
                        self._log(
                            f"Key storage updated: {storage_result.get('message', 'Success')}"
                        )
                    else:
                        self._log(
                            f"Key storage update failed: {storage_result.get('error')}"
                        )

                    self._log("Key rotation completed successfully!")
                    self._log(
                        "IMPORTANT: Restart the application for changes to take effect."
                    )

            except Exception as e:
                self._log(f"Key rotation failed: {e}")
                logger.exception("Key rotation failed with exception")
            finally:
                self.is_rotating = False

            return None

        self.rotation_thread = threading.Thread(target=rotation_worker, daemon=True)
        self.rotation_thread.start()

        return {"success": True, "message": "Key rotation started in background"}

    def get_rotation_status(self) -> Dict[str, Any]:
        """Get current rotation status and log"""
        return {
            "is_rotating": self.is_rotating,
            "log": self.rotation_log.copy(),
            "completed": not self.is_rotating and len(self.rotation_log) > 0,
        }

    def _log(self, message: str):
        """Add a log entry with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {"timestamp": timestamp, "message": message}
        self.rotation_log.append(log_entry)
        logger.info(f"Key Rotation: {message}")

    def _create_database_backup_with_data(
        self, db_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a backup of the database using pre-fetched data"""
        try:
            db_type = db_info["type"]

            # Create backup directory
            backup_dir = Path("backups")
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if db_type == "sqlite":
                return self._backup_sqlite(db_info, backup_dir, timestamp)
            elif db_type == "mysql":
                return self._backup_mysql(db_info, backup_dir, timestamp)
            elif db_type == "postgresql":
                return self._backup_postgresql(db_info, backup_dir, timestamp)
            else:
                return {
                    "success": False,
                    "error": f"Unsupported database type: {db_type}",
                    "backup_path": None,
                }

        except Exception as e:
            logger.error(f"Error creating database backup: {e}")
            return {"success": False, "error": str(e), "backup_path": None}

    def _update_key_storage_with_data(
        self, new_key: str, storage_info: Dict[str, Any], app_root: str
    ) -> Dict[str, Any]:
        """Update key storage method with new key using pre-fetched data"""
        try:
            method = storage_info.get("method")

            if method == "environment_variable":
                return {
                    "success": True,
                    "method": "environment_variable",
                    "instruction": f'Set environment variable: export TB_MASTER_KEY="{new_key}"',
                }

            elif method == "file":
                key_file_path = storage_info.get("path")
                if key_file_path:
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(key_file_path), exist_ok=True)

                    # Validate path security before writing
                    allowed_dirs = [
                        os.path.dirname(key_file_path),
                        os.path.join(app_root, "secrets"),
                    ]
                    if not validate_safe_path(key_file_path, allowed_dirs):
                        return {"success": False, "error": "Invalid key file path"}

                    # Write new key to file
                    with open(key_file_path, "w") as f:
                        f.write(new_key)

                    # Set secure file permissions
                    secure_file_permissions(key_file_path, 0o600)

                    return {
                        "success": True,
                        "method": "file",
                        "path": key_file_path,
                        "message": "Key file updated successfully",
                    }

            else:
                # Create key file as default
                key_file_path = os.path.join(app_root, "secrets", "tb_master_key")
                os.makedirs(os.path.dirname(key_file_path), exist_ok=True)

                # Validate path security before writing
                allowed_dirs = [os.path.join(app_root, "secrets")]
                if not validate_safe_path(key_file_path, allowed_dirs):
                    return {"success": False, "error": "Invalid key file path"}

                with open(key_file_path, "w") as f:
                    f.write(new_key)

                # Set secure file permissions
                secure_file_permissions(key_file_path, 0o600)

                return {
                    "success": True,
                    "method": "file",
                    "path": key_file_path,
                    "message": "Created new key file",
                }

        except Exception as e:
            return {"success": False, "error": str(e)}
        """Attempt to restart the application"""
        try:
            # This is a complex operation that depends on deployment method
            # For now, we'll provide instructions

            # Check if we're running in a container
            if os.path.exists("/.dockerenv"):
                return {
                    "success": False,
                    "method": "container",
                    "instruction": "Restart the Docker container to apply new key",
                }

            # Check if we're running with systemd
            try:
                runner = SecureSubprocessRunner(["systemctl"])
                cmd = ["systemctl", "is-active", "trakbridge"]
                if runner.validate_command(cmd):
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        shell=False,
                    )
                    if result.returncode == 0:
                        return {
                            "success": True,
                            "method": "systemd",
                            "instruction": "Run: sudo systemctl restart trakbridge",
                        }
            except FileNotFoundError:
                pass

            # Check if we're running with supervisor
            try:
                runner = SecureSubprocessRunner(["supervisorctl"])
                cmd = ["supervisorctl", "status", "trakbridge"]
                if runner.validate_command(cmd):
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        shell=False,
                    )
                    if result.returncode == 0:
                        return {
                            "success": True,
                            "method": "supervisor",
                            "instruction": "Run: supervisorctl restart trakbridge",
                        }
            except FileNotFoundError:
                pass

            return {
                "success": False,
                "method": "manual",
                "instruction": "Manually restart the application process",
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "instruction": "Manually restart the application",
            }


# Global instance
key_rotation_service = KeyRotationService()


def get_key_rotation_service():
    """Get the key rotation service instance"""
    return key_rotation_service
