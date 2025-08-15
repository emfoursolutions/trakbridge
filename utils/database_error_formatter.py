"""
ABOUTME: Database error message formatter for user-friendly error handling
ABOUTME: Converts technical database errors to actionable user guidance

File: utils/database_error_formatter.py

Description:
    Utility module for converting technical database errors into user-friendly
    error messages with actionable troubleshooting steps. Analyzes exception
    details to provide specific guidance based on the type of database error
    encountered, such as authentication failures, connection issues, or
    configuration problems.

Key features:
    - Error type detection from exception messages and types
    - User-friendly error message generation with clear explanations
    - Actionable troubleshooting steps for common database issues
    - Support for PostgreSQL, MySQL, and SQLite specific error patterns
    - Logging integration for technical error details
    - Structured error response format for API and web interfaces

Author: Emfour Solutions
Created: 2025-08-14
Last Modified: 2025-08-14
Version: 1.0.0
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Union

from services.exceptions import (
    DatabaseAuthenticationError,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseNotFoundError,
)

logger = logging.getLogger(__name__)


def analyze_database_error(error: Exception) -> Tuple[str, List[str]]:
    """
    Analyze a database error and return user-friendly message with troubleshooting steps.
    
    Args:
        error: The original database exception
        
    Returns:
        Tuple of (user_friendly_message, troubleshooting_steps)
    """
    error_str = str(error).lower()
    error_type = type(error).__name__
    
    # PostgreSQL specific errors
    if "psycopg2" in str(type(error)) or "postgresql" in error_str:
        return _analyze_postgresql_error(error_str, error_type)
    
    # MySQL specific errors  
    elif "mysql" in error_str or "pymysql" in str(type(error)):
        return _analyze_mysql_error(error_str, error_type)
    
    # SQLite specific errors
    elif "sqlite" in error_str:
        return _analyze_sqlite_error(error_str, error_type)
    
    # SQLAlchemy generic errors
    elif "sqlalchemy" in str(type(error)).lower():
        return _analyze_sqlalchemy_error(error_str, error_type)
    
    # Generic database error
    return _analyze_generic_error(error_str, error_type)


def _analyze_postgresql_error(error_str: str, error_type: str) -> Tuple[str, List[str]]:
    """Analyze PostgreSQL-specific errors."""
    
    # Authentication failures
    if "password authentication failed" in error_str:
        return (
            "Database authentication failed. The username or password is incorrect.",
            [
                "Verify the database username and password are correct",
                "Check that the user exists in PostgreSQL",
                "Ensure the password is properly set in Docker secrets or environment variables",
                "Verify pg_hba.conf allows password authentication for the user"
            ]
        )
    
    # Connection refused
    if "connection refused" in error_str or "could not connect" in error_str:
        return (
            "Cannot connect to the PostgreSQL database server.",
            [
                "Verify PostgreSQL server is running",
                "Check that the database host and port are correct",
                "Ensure PostgreSQL is accepting connections on the specified port",
                "Verify firewall settings allow connections to PostgreSQL"
            ]
        )
    
    # Database does not exist
    if "database" in error_str and ("does not exist" in error_str or "not exist" in error_str):
        return (
            "The specified database does not exist on the PostgreSQL server.",
            [
                "Verify the database name is spelled correctly",
                "Check that the database has been created on the PostgreSQL server",
                "Ensure you have permission to access the database",
                "Create the database if it doesn't exist"
            ]
        )
    
    # Role/user does not exist
    if "role" in error_str and ("does not exist" in error_str or "not exist" in error_str):
        return (
            "The database user does not exist on the PostgreSQL server.",
            [
                "Verify the username is spelled correctly",
                "Check that the database user has been created",
                "Ensure the user has appropriate permissions",
                "Create the database user if needed"
            ]
        )
    
    # Generic PostgreSQL error
    return (
        "PostgreSQL database error occurred.",
        [
            "Check PostgreSQL server logs for detailed error information",
            "Verify database connection settings",
            "Ensure PostgreSQL service is running properly"
        ]
    )


def _analyze_mysql_error(error_str: str, error_type: str) -> Tuple[str, List[str]]:
    """Analyze MySQL-specific errors."""
    
    # Authentication failures
    if "access denied" in error_str:
        return (
            "MySQL authentication failed. Access denied for the specified user.",
            [
                "Verify the MySQL username and password are correct",
                "Check that the user exists in MySQL",
                "Ensure the user has permission to connect from the current host",
                "Verify the password is properly configured"
            ]
        )
    
    # Connection errors
    if "can't connect" in error_str or "connection refused" in error_str:
        return (
            "Cannot connect to the MySQL database server.",
            [
                "Verify MySQL server is running",
                "Check that the database host and port are correct",
                "Ensure MySQL is accepting connections",
                "Verify firewall settings allow MySQL connections"
            ]
        )
    
    # Database doesn't exist
    if "unknown database" in error_str:
        return (
            "The specified MySQL database does not exist.",
            [
                "Verify the database name is correct",
                "Check that the database has been created",
                "Create the database if it doesn't exist",
                "Ensure proper permissions to access the database"
            ]
        )
    
    # Generic MySQL error
    return (
        "MySQL database error occurred.",
        [
            "Check MySQL server logs for detailed information",
            "Verify database connection configuration",
            "Ensure MySQL service is running properly"
        ]
    )


def _analyze_sqlite_error(error_str: str, error_type: str) -> Tuple[str, List[str]]:
    """Analyze SQLite-specific errors."""
    
    # File permissions
    if "permission denied" in error_str or "readonly" in error_str:
        return (
            "Cannot access SQLite database file due to permission issues.",
            [
                "Check file permissions on the database file",
                "Ensure the application has write access to the database directory",
                "Verify the database file is not read-only",
                "Check filesystem permissions and ownership"
            ]
        )
    
    # Database locked
    if "database is locked" in error_str:
        return (
            "SQLite database is locked by another process.",
            [
                "Close any other applications using the database",
                "Wait for other operations to complete",
                "Check for zombie processes holding database locks",
                "Restart the application if the lock persists"
            ]
        )
    
    # File not found
    if "no such file" in error_str or "not found" in error_str:
        return (
            "SQLite database file not found.",
            [
                "Verify the database file path is correct",
                "Check that the database file exists",
                "Ensure the application has permission to create the file",
                "Verify the directory exists and is writable"
            ]
        )
    
    # Generic SQLite error
    return (
        "SQLite database error occurred.",
        [
            "Check database file path and permissions",
            "Verify SQLite database file integrity",
            "Ensure sufficient disk space is available"
        ]
    )


def _analyze_sqlalchemy_error(error_str: str, error_type: str) -> Tuple[str, List[str]]:
    """Analyze SQLAlchemy-specific errors."""
    
    # Invalid connection string
    if "invalid" in error_str and ("url" in error_str or "connection" in error_str):
        return (
            "Database connection configuration is invalid.",
            [
                "Check the database URL format",
                "Verify all connection parameters are correct",
                "Ensure required connection parameters are provided",
                "Review database configuration settings"
            ]
        )
    
    # Pool connection errors
    if "pool" in error_str or "timeout" in error_str:
        return (
            "Database connection pool error or timeout.",
            [
                "Check database server performance and load",
                "Verify connection pool settings",
                "Ensure database server can handle the connection load",
                "Consider increasing connection timeout values"
            ]
        )
    
    # Generic SQLAlchemy error
    return (
        "Database connection error occurred.",
        [
            "Check database connection settings",
            "Verify database server is accessible",
            "Review application logs for more details",
            "Ensure database service is running properly"
        ]
    )


def _analyze_generic_error(error_str: str, error_type: str) -> Tuple[str, List[str]]:
    """Analyze generic database errors."""
    
    # Network/connection issues
    if any(keyword in error_str for keyword in ["network", "timeout", "refused", "unreachable"]):
        return (
            "Network connection to database failed.",
            [
                "Check network connectivity to the database server",
                "Verify the database server address and port",
                "Ensure firewall rules allow database connections",
                "Check if the database service is running"
            ]
        )
    
    # Permission issues
    if any(keyword in error_str for keyword in ["permission", "denied", "unauthorized", "forbidden"]):
        return (
            "Database access permission denied.",
            [
                "Verify database user credentials",
                "Check user permissions and privileges",
                "Ensure the user account is not locked",
                "Review database access control settings"
            ]
        )
    
    # Generic error
    return (
        "An unexpected database error occurred.",
        [
            "Check the application logs for more details",
            "Verify database server status",
            "Review database connection configuration",
            "Contact system administrator if the problem persists"
        ]
    )


def create_database_exception(error: Exception) -> DatabaseError:
    """
    Create an appropriate DatabaseError subclass based on the original error.
    
    Args:
        error: The original database exception
        
    Returns:
        Appropriate DatabaseError subclass with user-friendly message
    """
    error_str = str(error).lower()
    
    # Authentication errors
    if any(keyword in error_str for keyword in [
        "password authentication failed", "access denied", "authentication", "login"
    ]):
        return DatabaseAuthenticationError(original_error=error)
    
    # Connection errors
    elif any(keyword in error_str for keyword in [
        "connection refused", "could not connect", "can't connect", "network", "timeout"
    ]):
        return DatabaseConnectionError(original_error=error)
    
    # Not found errors
    elif any(keyword in error_str for keyword in [
        "does not exist", "not exist", "unknown database", "no such file", "not found"
    ]):
        return DatabaseNotFoundError(original_error=error)
    
    # Configuration errors
    elif any(keyword in error_str for keyword in [
        "invalid", "configuration", "url", "malformed", "syntax"
    ]):
        return DatabaseConfigurationError(original_error=error)
    
    # Generic database error
    else:
        message, steps = analyze_database_error(error)
        return DatabaseError(message, error, steps)


def format_error_response(error: DatabaseError) -> Dict[str, Union[str, List[str]]]:
    """
    Format a database error into a structured response for API or web display.
    
    Args:
        error: DatabaseError instance
        
    Returns:
        Dictionary with error information and troubleshooting steps
    """
    return {
        "error": "Database Error",
        "message": str(error),
        "type": type(error).__name__,
        "troubleshooting_steps": getattr(error, 'troubleshooting_steps', []),
        "technical_details": str(error.original_error) if hasattr(error, 'original_error') and error.original_error else None
    }


def log_database_error(error: Exception, context: str = "Database operation") -> None:
    """
    Log database error with appropriate level and context.
    
    Args:
        error: The database exception
        context: Context description for the error
    """
    # Create user-friendly exception for consistent logging
    db_error = create_database_exception(error)
    
    # Log technical details for debugging
    logger.error(
        f"{context} failed: {str(db_error)}",
        extra={
            "error_type": type(error).__name__,
            "original_error": str(error),
            "troubleshooting_steps": db_error.troubleshooting_steps
        },
        exc_info=True
    )
    
    # Log user-friendly message at warning level
    logger.warning(f"Database error for users: {str(db_error)}")