"""
ABOUTME: Security utility functions for input validation and safe operations
ABOUTME: Provides path validation, command sanitization, and security checks

File: utils/security_helpers.py

Description:
    Security utility functions to prevent common vulnerabilities including path traversal,
    command injection, and input validation. Used throughout TrakBridge to ensure secure
    operations with user input, file paths, and system commands.

Key functions:
    - Path validation and traversal prevention
    - Command argument sanitization
    - Input validation helpers
    - Secure file operation wrappers
    - Database parameter validation

Author: Emfour Solutions
Created: 2025-07-27
Last Modified: 2025-07-27
Version: 1.0.0
"""

import os
import re
import logging
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

logger = logging.getLogger(__name__)


def validate_safe_path(
    file_path: Union[str, Path], allowed_base_dirs: List[Union[str, Path]]
) -> bool:
    """
    Validate that a file path is safe and within allowed directories.

    Prevents path traversal attacks by ensuring the resolved path
    is within one of the allowed base directories.

    Args:
        file_path: Path to validate
        allowed_base_dirs: List of allowed base directories

    Returns:
        True if path is safe, False otherwise
    """
    try:
        # Convert to Path object and resolve to absolute path
        path_obj = Path(file_path).resolve()
        abs_path = str(path_obj)

        # Check against each allowed base directory
        for base_dir in allowed_base_dirs:
            base_path = Path(base_dir).resolve()
            try:
                # Check if the path is within the base directory
                path_obj.relative_to(base_path)
                return True
            except ValueError:
                # Path is not within this base directory
                continue

        logger.warning(
            f"Path validation failed: {file_path} not in allowed directories"
        )
        return False

    except (OSError, ValueError) as e:
        logger.error(f"Path validation error for {file_path}: {e}")
        return False


def sanitize_filename(filename: str, max_length: int = 255) -> Optional[str]:
    """
    Sanitize a filename to prevent security issues.

    Args:
        filename: Original filename
        max_length: Maximum allowed length

    Returns:
        Sanitized filename or None if invalid
    """
    if not filename or not isinstance(filename, str):
        return None

    # Remove path components
    filename = os.path.basename(filename)

    # Remove dangerous characters and sequences
    # Allow alphanumeric, dots, hyphens, underscores
    sanitized = re.sub(r"[^a-zA-Z0-9.\-_]", "_", filename)

    # Prevent hidden files and parent directory references
    if sanitized.startswith(".") or sanitized in ("..", "."):
        sanitized = "file_" + sanitized

    # Limit length
    if len(sanitized) > max_length:
        name, ext = os.path.splitext(sanitized)
        name = name[: max_length - len(ext) - 4] + "..."
        sanitized = name + ext

    return sanitized if sanitized else None


def validate_database_params(params: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate and sanitize database connection parameters.

    Args:
        params: Database parameters dictionary

    Returns:
        Sanitized parameters dictionary

    Raises:
        ValueError: If parameters are invalid
    """
    validated = {}

    # Validate hostname
    if "host" in params:
        host = str(params["host"]).strip()
        if not re.match(r"^[a-zA-Z0-9.-]+$", host):
            raise ValueError("Invalid hostname format")
        validated["host"] = host

    # Validate port
    if "port" in params:
        try:
            port = int(params["port"])
            if not (1 <= port <= 65535):
                raise ValueError("Port must be between 1 and 65535")
            validated["port"] = str(port)
        except (ValueError, TypeError):
            raise ValueError("Invalid port number")

    # Validate database name
    if "database" in params:
        db_name = str(params["database"]).strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", db_name):
            raise ValueError("Invalid database name format")
        validated["database"] = db_name

    # Validate username
    if "username" in params:
        username = str(params["username"]).strip()
        if not re.match(r"^[a-zA-Z0-9_.-]+$", username):
            raise ValueError("Invalid username format")
        validated["username"] = username

    return validated


def sanitize_command_args(args: List[str]) -> List[str]:
    """
    Sanitize command line arguments to prevent injection attacks.

    Args:
        args: List of command arguments

    Returns:
        List of sanitized arguments

    Raises:
        ValueError: If arguments contain dangerous content
    """
    sanitized = []

    for arg in args:
        if not isinstance(arg, str):
            arg = str(arg)

        # Check for dangerous characters and sequences
        dangerous_patterns = [
            r"[;&|`$()]",  # Shell metacharacters
            r"\.\./",  # Path traversal
            r"^\s*$",  # Empty/whitespace only
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, arg):
                raise ValueError(f"Dangerous content in argument: {arg}")

        # Additional validation for specific argument types
        if arg.startswith("-"):
            # Validate option flags
            if not re.match(r"^-[a-zA-Z0-9-]+$", arg):
                raise ValueError(f"Invalid option format: {arg}")

        sanitized.append(arg)

    return sanitized


def create_secure_backup_path(base_dir: Union[str, Path], filename: str) -> Path:
    """
    Create a secure backup file path within the specified base directory.

    Args:
        base_dir: Base directory for backups
        filename: Desired filename

    Returns:
        Secure backup file path

    Raises:
        ValueError: If path is not secure
    """
    # Sanitize the filename
    safe_filename = sanitize_filename(filename)
    if not safe_filename:
        raise ValueError("Invalid filename")

    # Create the full path
    base_path = Path(base_dir).resolve()
    backup_path = base_path / safe_filename

    # Validate the path is within the base directory
    if not validate_safe_path(backup_path, [base_path]):
        raise ValueError("Backup path is not within allowed directory")

    # Ensure base directory exists
    base_path.mkdir(parents=True, exist_ok=True)

    return backup_path


def validate_backup_directory(backup_dir: Union[str, Path]) -> bool:
    """
    Validate that a backup directory is safe to use.

    Args:
        backup_dir: Directory path to validate

    Returns:
        True if directory is safe to use
    """
    try:
        dir_path = Path(backup_dir).resolve()

        # Check if it's a valid directory path
        if not dir_path.is_absolute():
            logger.warning(f"Backup directory must be absolute path: {backup_dir}")
            return False

        # Prevent backing up to system directories
        system_dirs = [
            Path("/"),
            Path("/etc"),
            Path("/bin"),
            Path("/usr"),
            Path("/var"),
            Path("/sys"),
            Path("/proc"),
            Path("/dev"),
        ]

        for sys_dir in system_dirs:
            try:
                dir_path.relative_to(sys_dir)
                logger.warning(f"Backup directory in system path: {backup_dir}")
                return False
            except ValueError:
                continue

        return True

    except (OSError, ValueError) as e:
        logger.error(f"Backup directory validation error: {e}")
        return False


def validate_file_extension(filename: str, allowed_extensions: List[str]) -> bool:
    """
    Validate that a file has an allowed extension.

    Args:
        filename: Filename to check
        allowed_extensions: List of allowed extensions (including dot)

    Returns:
        True if extension is allowed
    """
    if not filename or not allowed_extensions:
        return False

    file_ext = os.path.splitext(filename.lower())[1]
    return file_ext in [ext.lower() for ext in allowed_extensions]


def secure_file_permissions(file_path: Union[str, Path], mode: int = 0o600) -> None:
    """
    Set secure permissions on a file.

    Args:
        file_path: Path to file
        mode: Permission mode (default: 0o600 - owner read/write only)
    """
    try:
        os.chmod(file_path, mode)
        logger.debug(f"Set secure permissions {oct(mode)} on {file_path}")
    except OSError as e:
        logger.warning(f"Failed to set secure permissions on {file_path}: {e}")


class SecureSubprocessRunner:
    """
    Secure wrapper for subprocess operations with validation.
    """

    def __init__(self, allowed_commands: List[str] = None):
        """
        Initialize with allowed commands.

        Args:
            allowed_commands: List of allowed command names
        """
        self.allowed_commands = allowed_commands or []

    def validate_command(self, cmd: List[str]) -> bool:
        """
        Validate that a command is safe to execute.

        Args:
            cmd: Command and arguments list

        Returns:
            True if command is safe
        """
        if not cmd or not isinstance(cmd, list):
            return False

        command_name = os.path.basename(cmd[0])

        # Check if command is in allowed list
        if self.allowed_commands and command_name not in self.allowed_commands:
            logger.warning(f"Command not in allowed list: {command_name}")
            return False

        # Validate all arguments
        try:
            sanitize_command_args(cmd)
            return True
        except ValueError as e:
            logger.warning(f"Command validation failed: {e}")
            return False

    def run_secure_command(self, cmd: List[str], **kwargs) -> bool:
        """
        Run a command with security validation.

        Args:
            cmd: Command and arguments
            **kwargs: Additional subprocess arguments

        Returns:
            True if command executed successfully
        """
        if not self.validate_command(cmd):
            raise ValueError("Command failed security validation")

        import subprocess

        try:
            # Remove potentially dangerous kwargs
            safe_kwargs = {
                k: v for k, v in kwargs.items() if k not in ["shell", "executable"]
            }

            # Ensure shell is never True
            safe_kwargs["shell"] = False

            result = subprocess.run(cmd, **safe_kwargs)
            return result.returncode == 0

        except Exception as e:
            logger.error(f"Secure command execution failed: {e}")
            return False
