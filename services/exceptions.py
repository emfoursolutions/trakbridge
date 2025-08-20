"""
File: services/exceptions.py

Description:
    Custom exception hierarchy providing structured error handling for the TrakBridge
    application. This module defines specialized exception classes for different
    subsystems and error conditions, enabling precise error categorization and
    targeted exception handling throughout the application.

Key features:
    - Hierarchical exception structure with base classes for major subsystems
    - Stream management exceptions for database, configuration, and runtime errors
    - Plugin system exceptions for connection, configuration, and timeout scenarios
    - TAK server communication exceptions for authentication and connectivity issues
    - Encryption service exceptions for cryptographic operations and key management
    - Configuration validation exceptions for application setup and validation
    - Clear exception naming conventions for easy identification and handling


Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""


class StreamManagerError(Exception):
    """Base exception for StreamManager errors"""

    pass


class StreamNotFoundError(StreamManagerError):
    """Raised when a stream is not found in the database"""

    pass


class StreamConfigurationError(StreamManagerError):
    """Raised when stream configuration is invalid"""

    pass


class StreamStartupError(StreamManagerError):
    """Raised when stream fails to start"""

    pass


# Database Connection Exceptions
class DatabaseError(Exception):
    """Base exception for database-related errors"""

    def __init__(
        self,
        message: str,
        original_error: Exception = None,
        troubleshooting_steps: list = None,
    ):
        super().__init__(message)
        self.original_error = original_error
        self.troubleshooting_steps = troubleshooting_steps or []


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails"""

    def __init__(self, message: str = None, original_error: Exception = None):
        default_message = "Unable to connect to the database server"
        super().__init__(
            message or default_message,
            original_error,
            [
                "Verify the database server is running",
                "Check network connectivity to the database host",
                "Ensure the database port is accessible",
                "Verify firewall settings allow database connections",
            ],
        )


class DatabaseAuthenticationError(DatabaseError):
    """Raised when database authentication fails"""

    def __init__(self, message: str = None, original_error: Exception = None):
        default_message = "Database authentication failed"
        super().__init__(
            message or default_message,
            original_error,
            [
                "Check database username and password",
                "Verify database user has necessary permissions",
                "Ensure credentials are properly configured in secrets",
                "Check if database user account is locked or expired",
            ],
        )


class DatabaseNotFoundError(DatabaseError):
    """Raised when specified database or host cannot be found"""

    def __init__(self, message: str = None, original_error: Exception = None):
        default_message = "Database or host not found"
        super().__init__(
            message or default_message,
            original_error,
            [
                "Verify the database name is correct",
                "Check that the database exists on the server",
                "Ensure the database host/IP address is correct",
                "Verify DNS resolution for the database hostname",
            ],
        )


class DatabaseConfigurationError(DatabaseError):
    """Raised when database configuration is invalid"""

    def __init__(self, message: str = None, original_error: Exception = None):
        default_message = "Database configuration is invalid"
        super().__init__(
            message or default_message,
            original_error,
            [
                "Review database connection settings",
                "Check environment variables and configuration files",
                "Verify database URL format is correct",
                "Ensure all required configuration parameters are set",
            ],
        )


class StreamTimeoutError(StreamManagerError):
    """Raised when stream operations timeout"""

    pass


class DatabaseError(StreamManagerError):
    """Raised when database operations fail"""

    pass


class PluginError(Exception):
    """Base exception for plugin-related errors"""

    pass


class PluginNotFoundError(PluginError):
    """Raised when a plugin is not found"""

    pass


class PluginConfigurationError(PluginError):
    """Raised when plugin configuration is invalid"""

    pass


class PluginConnectionError(PluginError):
    """Raised when plugin connection fails"""

    pass


class PluginTimeoutError(PluginError):
    """Raised when plugin operations timeout"""

    pass


class TAKServerError(Exception):
    """Base exception for TAK server errors"""

    pass


class TAKServerConnectionError(TAKServerError):
    """Raised when TAK server connection fails"""

    pass


class TAKServerAuthenticationError(TAKServerError):
    """Raised when TAK server authentication fails"""

    pass


class TAKServerTimeoutError(TAKServerError):
    """Raised when TAK server operations timeout"""

    pass


class EncryptionError(Exception):
    """Base exception for encryption errors"""

    pass


class EncryptionKeyError(EncryptionError):
    """Raised when encryption key is invalid or missing"""

    pass


class EncryptionDataError(EncryptionError):
    """Raised when encryption/decryption of data fails"""

    pass


class ConfigurationError(Exception):
    """Base exception for configuration errors"""

    pass


class ConfigurationValidationError(ConfigurationError):
    """Raised when configuration validation fails"""

    pass


class ConfigurationMissingError(ConfigurationError):
    """Raised when required configuration is missing"""

    pass
