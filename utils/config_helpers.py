"""
ABOUTME: Centralized configuration access utilities to reduce boilerplate patterns
ABOUTME: Provides consistent config access methods and common configuration operations

File: utils/config_helpers.py

Description:
    Centralized configuration access utilities to standardize the repetitive config
    access patterns found in 19+ files throughout TrakBridge. Provides safe config
    access with defaults, nested key access, and common configuration operations.

Key features:
    - Safe config access with default values
    - Nested configuration key access with dot notation
    - Environment variable integration
    - Configuration validation utilities
    - Plugin configuration helpers
    - Type-safe configuration access

Author: Emfour Solutions
Created: 2025-09-02
Last Modified: 2025-09-02
Version: 1.0.0
"""

import os
from typing import Any, Dict, List, Optional, Union, Type, TypeVar
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

T = TypeVar("T")


def safe_config_get(config: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Safely get a configuration value with default.
    Backwards-compatible replacement for config.get(key, default).

    Args:
        config: Configuration dictionary
        key: Configuration key
        default: Default value if key not found

    Returns:
        Configuration value or default
    """
    return config.get(key, default)


def nested_config_get(
    config: Dict[str, Any], key_path: str, default: Any = None
) -> Any:
    """
    Get nested configuration value using dot notation.

    Args:
        config: Configuration dictionary
        key_path: Dot-separated key path (e.g., "auth.providers.ldap.enabled")
        default: Default value if path not found

    Returns:
        Configuration value or default

    Usage:
        # Instead of: config.get("auth", {}).get("providers", {}).get("ldap", {}).get("enabled", False)
        # Use:        nested_config_get(config, "auth.providers.ldap.enabled", False)
    """
    keys = key_path.split(".")
    current = config

    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]

    return current


def nested_config_set(config: Dict[str, Any], key_path: str, value: Any) -> None:
    """
    Set nested configuration value using dot notation.

    Args:
        config: Configuration dictionary to modify
        key_path: Dot-separated key path
        value: Value to set

    Usage:
        nested_config_set(config, "auth.providers.ldap.enabled", True)
    """
    keys = key_path.split(".")
    current = config

    # Navigate to the parent of the final key
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            # Convert non-dict values to dicts to continue nesting
            logger.warning(
                f"Overwriting non-dict value at {key} in config path {key_path}"
            )
            current[key] = {}
        current = current[key]

    # Set the final value
    current[keys[-1]] = value


def config_get_typed(
    config: Dict[str, Any], key: str, expected_type: Type[T], default: T
) -> T:
    """
    Get configuration value with type checking and conversion.

    Args:
        config: Configuration dictionary
        key: Configuration key
        expected_type: Expected type (int, str, bool, etc.)
        default: Default value of expected type

    Returns:
        Typed configuration value or default

    Usage:
        port = config_get_typed(config, "port", int, 5000)
        enabled = config_get_typed(config, "enabled", bool, True)
    """
    value = config.get(key, default)

    if value is None:
        return default

    # Handle boolean string conversion
    if expected_type == bool and isinstance(value, str):
        return value.lower() in ("true", "1", "yes", "on")

    # Handle type conversion
    try:
        if not isinstance(value, expected_type):
            return expected_type(value)
        return value
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Failed to convert config value {key}={value} to {expected_type.__name__}: {e}"
        )
        return default


def get_environment_config(
    config: Dict[str, Any], env_var_prefix: str = "TRAKBRIDGE_"
) -> Dict[str, Any]:
    """
    Get configuration values with environment variable overrides.

    Args:
        config: Base configuration dictionary
        env_var_prefix: Prefix for environment variables

    Returns:
        Configuration with environment variable overrides applied

    Usage:
        config = get_environment_config(base_config, "TRAKBRIDGE_")
        # Environment variable TRAKBRIDGE_DATABASE_URL overrides config["database_url"]
    """
    result = config.copy()

    for env_key, env_value in os.environ.items():
        if env_key.startswith(env_var_prefix):
            # Convert TRAKBRIDGE_DATABASE_URL to database_url
            config_key = env_key[len(env_var_prefix) :].lower()

            # Handle nested keys (TRAKBRIDGE_AUTH_PROVIDERS_LDAP_ENABLED -> auth.providers.ldap.enabled)
            if "_" in config_key:
                nested_key = config_key.replace("_", ".")
                nested_config_set(result, nested_key, env_value)
            else:
                result[config_key] = env_value

    return result


def merge_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge multiple configuration dictionaries with nested merging.
    Later configs override earlier ones.

    Args:
        *configs: Configuration dictionaries to merge

    Returns:
        Merged configuration dictionary
    """

    def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = base.copy()

        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    if not configs:
        return {}

    result = configs[0].copy()
    for config in configs[1:]:
        result = deep_merge(result, config)

    return result


class ConfigHelper:
    """
    Configuration helper class for easier config management.

    Usage:
        helper = ConfigHelper(app.config)
        db_host = helper.get("database.host", "localhost")
        debug_mode = helper.get_bool("debug", False)
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value with dot notation support."""
        if "." in key:
            return nested_config_get(self.config, key, default)
        return self.config.get(key, default)

    def get_str(self, key: str, default: str = "") -> str:
        """Get string config value."""
        if "." in key:
            value = nested_config_get(self.config, key, default)
        else:
            value = self.config.get(key, default)

        if value is None:
            return default

        try:
            return str(value)
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert config value {key}={value} to str")
            return default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get integer config value."""
        if "." in key:
            value = nested_config_get(self.config, key, default)
        else:
            value = self.config.get(key, default)

        if value is None:
            return default

        # Handle type conversion
        try:
            if not isinstance(value, int):
                return int(value)
            return value
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert config value {key}={value} to int")
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean config value."""
        if "." in key:
            value = nested_config_get(self.config, key, default)
        else:
            value = self.config.get(key, default)

        if value is None:
            return default

        # Handle boolean string conversion
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")

        try:
            return bool(value)
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert config value {key}={value} to bool")
            return default

    def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Get list config value."""
        if default is None:
            default = []

        if "." in key:
            value = nested_config_get(self.config, key, default)
        else:
            value = self.config.get(key, default)

        if value is None:
            return default

        try:
            if isinstance(value, list):
                return value
            else:
                return list(value)
        except (ValueError, TypeError):
            logger.warning(f"Failed to convert config value {key}={value} to list")
            return default

    def set(self, key: str, value: Any) -> None:
        """Set config value with dot notation support."""
        if "." in key:
            nested_config_set(self.config, key, value)
        else:
            self.config[key] = value

    def has(self, key: str) -> bool:
        """Check if config key exists."""
        if "." in key:
            return nested_config_get(self.config, key, None) is not None
        return key in self.config

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section."""
        return self.get(section, {})


def validate_config_keys(
    config: Dict[str, Any], required_keys: List[str], section_name: str = "config"
) -> List[str]:
    """
    Validate that required configuration keys are present.

    Args:
        config: Configuration dictionary to validate
        required_keys: List of required keys (supports dot notation)
        section_name: Name of the section being validated (for error messages)

    Returns:
        List of missing keys
    """
    missing_keys = []

    for key in required_keys:
        if "." in key:
            value = nested_config_get(config, key, None)
        else:
            value = config.get(key, None)

        if value is None:
            missing_keys.append(key)

    if missing_keys:
        logger.error(f"Missing required {section_name} keys: {missing_keys}")

    return missing_keys


def get_flask_config_helper(app) -> ConfigHelper:
    """
    Get ConfigHelper instance for Flask app configuration.

    Args:
        app: Flask application instance

    Returns:
        ConfigHelper instance
    """
    return ConfigHelper(app.config)


# Convenience functions for common patterns
def get_auth_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get authentication configuration section."""
    return nested_config_get(config, "authentication", {})


def get_database_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get database configuration section."""
    return nested_config_get(config, "database", {})


def get_security_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get security configuration section."""
    return nested_config_get(config, "default.security", {})


def get_providers_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Get authentication providers configuration."""
    return nested_config_get(config, "authentication.providers", {})
