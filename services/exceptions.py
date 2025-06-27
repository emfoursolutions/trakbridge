# =============================================================================
# services/exceptions.py - Custom Exception Classes
# =============================================================================

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