"""
File: config/authentication_loader.py

Description:
    Secure authentication configuration loader with environment variable substitution
    and local development support

Author: Emfour Solutions
Created: 2025-08-03
"""

# Standard library imports
import logging
import os
import re
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional

# Third-party imports
import yaml

logger = logging.getLogger(__name__)


class SecureAuthenticationLoader:
    """
    Secure authentication configuration loader that supports:
    1. Local development files (authentication.yaml)
    2. Template-based CI/CD with environment variables
    3. Safe fallback configurations
    """

    def __init__(self, environment: str = "development"):
        self.environment = environment
        self.config_dir = Path(__file__).parent / "settings"

        # Configuration file paths
        self.local_config_path = self.config_dir / "authentication.yaml"
        self.template_path = self.config_dir / "authentication.yaml.template"
        self.example_path = self.config_dir / "authentication.yaml.example"

        # Initialize secret manager for secrets and environment variables
        from .secrets import get_secret_manager

        self.secret_manager = get_secret_manager(environment)

        # CI/CD detection
        self.is_ci = bool(os.getenv("CI"))

        logger.debug(f"Authentication loader initialized for environment: {environment}")
        logger.debug(f"CI/CD mode: {self.is_ci}")

    def load_authentication_config(self) -> Dict[str, Any]:
        """
        Load authentication configuration with the following priority:
        1. Local config file (development only)
        2. Template with environment variable substitution (CI/CD)
        3. Example file as fallback
        4. Default safe configuration
        """
        try:
            # Priority 1: Local config file (only in development, not in CI)
            if not self.is_ci and self.local_config_path.exists():
                logger.info("Loading authentication config from local file")
                return self._load_local_config()

            # Priority 2: Template with environment substitution (CI/CD or no local file)
            elif self.template_path.exists():
                logger.info(
                    "Loading authentication config from template with environment variables"
                )
                return self._load_template_config()

            # Priority 3: Example file as fallback
            elif self.example_path.exists():
                logger.warning(
                    "Loading authentication config from example file - consider creating template"
                )
                return self._load_example_config()

            # Priority 4: Default safe configuration
            else:
                logger.warning("No authentication config found - using default safe configuration")
                return self._get_default_config()

        except Exception as e:
            logger.error(f"Failed to load authentication config: {e}")
            logger.warning("Falling back to default safe configuration")
            return self._get_default_config()

    def _load_local_config(self) -> Dict[str, Any]:
        """Load local authentication.yaml file with environment variable substitution."""
        with open(self.local_config_path, "r") as f:
            template_content = f.read()

        # Substitute environment variables (same as template loading)
        substituted_content = self._substitute_environment_variables(template_content)

        # Convert null strings to proper YAML null values
        substituted_content = self._convert_null_strings(substituted_content)

        # Parse the substituted YAML
        config = yaml.safe_load(substituted_content) or {}

        logger.debug("Loaded authentication config from local file with environment substitution")
        return self._apply_environment_overrides(config)

    def _load_template_config(self) -> Dict[str, Any]:
        """Load template file with environment variable substitution."""
        with open(self.template_path, "r") as f:
            template_content = f.read()

        # Substitute environment variables
        substituted_content = self._substitute_environment_variables(template_content)

        # Convert null strings to proper YAML null values
        substituted_content = self._convert_null_strings(substituted_content)

        # Parse the substituted YAML
        config = yaml.safe_load(substituted_content) or {}

        logger.debug("Loaded authentication config from template with environment substitution")
        return self._apply_environment_overrides(config)

    def _load_example_config(self) -> Dict[str, Any]:
        """Load example file as fallback."""
        with open(self.example_path, "r") as f:
            config = yaml.safe_load(f) or {}

        logger.debug("Loaded authentication config from example file")
        return self._apply_environment_overrides(config)

    def _substitute_environment_variables(self, content: str) -> str:
        """
        Substitute environment variables in template content.
        Supports ${VAR_NAME:-default_value} syntax with nested braces.
        """

        # More sophisticated substitution to handle nested braces in default values
        def substitute_variables(text):
            result = []
            i = 0
            while i < len(text):
                if text[i : i + 2] == "${":
                    # Find the matching closing brace
                    brace_count = 1
                    start = i + 2
                    j = start
                    while j < len(text) and brace_count > 0:
                        if text[j] == "{":
                            brace_count += 1
                        elif text[j] == "}":
                            brace_count -= 1
                        j += 1

                    if brace_count == 0:
                        # Extract the variable expression
                        var_expr = text[start : j - 1]

                        # Process the variable using secret manager (checks secrets files first, then env vars)
                        if ":-" in var_expr:
                            var_name, default_value = var_expr.split(":-", 1)
                            value = self.secret_manager.get_secret(var_name.strip())
                            if value is None:
                                result.append(default_value.strip())
                            else:
                                result.append(value)
                        else:
                            # Simple variable substitution
                            var_name = var_expr.strip()
                            value = self.secret_manager.get_secret(var_name)
                            if value is None:
                                logger.warning(
                                    f"Variable {var_name} not found in secrets or environment, using empty string"
                                )
                                result.append("")
                            else:
                                result.append(value)

                        i = j
                    else:
                        # Unmatched braces, treat as literal
                        result.append(text[i])
                        i += 1
                else:
                    result.append(text[i])
                    i += 1

            return "".join(result)

        substituted = substitute_variables(content)

        # Convert boolean strings to proper boolean values
        substituted = self._convert_boolean_strings(substituted)

        return substituted

    def _convert_boolean_strings(self, content: str) -> str:
        """Convert string boolean values to proper YAML booleans."""
        # Convert common boolean string patterns
        boolean_replacements = {
            ': "true"': ": true",
            ': "false"': ": false",
            ': "True"': ": true",
            ': "False"': ": false",
            ': "TRUE"': ": true",
            ': "FALSE"': ": false",
        }

        for old, new in boolean_replacements.items():
            content = content.replace(old, new)

        return content

    def _convert_null_strings(self, content: str) -> str:
        """Convert string null values to proper YAML null."""
        # Convert "null" strings to proper YAML null
        null_replacements = {
            ': "null"': ": null",
            ': "None"': ": null",
            ': "NULL"': ": null",
        }

        for old, new in null_replacements.items():
            content = content.replace(old, new)

        return content

    def _apply_environment_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment-specific configuration overrides."""
        if self.environment in config:
            env_config = config[self.environment]
            if isinstance(env_config, dict) and "authentication" in env_config:
                # Deep merge environment-specific overrides
                base_auth = config.get("authentication", {})
                env_auth = env_config["authentication"]
                merged_auth = self._deep_merge(base_auth, env_auth)
                config["authentication"] = merged_auth

        return config

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _get_default_config(self) -> Dict[str, Any]:
        """Return a safe default authentication configuration."""
        return {
            "authentication": {
                "session": {
                    "lifetime_hours": 8,
                    "cleanup_interval_minutes": 60,
                    "secure_cookies": self.environment == "production",
                    "cookie_path": "/",
                },
                "provider_priority": ["local"],
                "providers": {
                    "local": {
                        "enabled": True,
                        "password_policy": {
                            "min_length": 8 if self.environment == "production" else 4,
                            "require_uppercase": self.environment == "production",
                            "require_lowercase": self.environment == "production",
                            "require_numbers": self.environment == "production",
                            "require_special": False,
                        },
                    },
                    "ldap": {"enabled": False},
                    "oidc": {"enabled": False},
                },
            }
        }

    def validate_config(self, config: Dict[str, Any]) -> Optional[str]:
        """
        Validate authentication configuration.
        Returns error message if invalid, None if valid.
        """
        try:
            auth_config = config.get("authentication", {})

            # Validate required sections
            if "providers" not in auth_config:
                return "Missing 'providers' section in authentication config"

            providers = auth_config["providers"]

            # Check if at least one provider is enabled
            enabled_providers = []
            for name, provider_config in providers.items():
                if provider_config.get("enabled", False):
                    enabled_providers.append(name)

            if not enabled_providers:
                return "No authentication providers are enabled"

            # Validate LDAP config if enabled
            if providers.get("ldap", {}).get("enabled", False):
                ldap_config = providers["ldap"]
                required_ldap_fields = [
                    "server",
                    "bind_dn",
                    "bind_password",
                    "user_search_base",
                ]
                for field in required_ldap_fields:
                    if not ldap_config.get(field):
                        return f"LDAP enabled but missing required field: {field}"

            # Validate OIDC config if enabled
            if providers.get("oidc", {}).get("enabled", False):
                oidc_config = providers["oidc"]
                required_oidc_fields = ["issuer", "client_id", "client_secret"]
                for field in required_oidc_fields:
                    if not oidc_config.get(field):
                        return f"OIDC enabled but missing required field: {field}"

            logger.debug("Authentication configuration validation passed")
            return None

        except Exception as e:
            return f"Authentication config validation error: {e}"

    def get_masked_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Return configuration with sensitive values masked for logging."""
        import copy

        masked_config = copy.deepcopy(config)

        # Mask sensitive fields
        sensitive_fields = [
            "bind_password",
            "client_secret",
            "password",
            "secret",
            "key",
            "token",
        ]

        def mask_sensitive_values(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = f"{path}.{key}" if path else key
                    if any(sensitive in key.lower() for sensitive in sensitive_fields):
                        obj[key] = "***MASKED***"
                    else:
                        mask_sensitive_values(value, current_path)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    mask_sensitive_values(item, f"{path}[{i}]")

        mask_sensitive_values(masked_config)
        return masked_config


# Create a singleton instance for the current environment
_authentication_loader: Optional[SecureAuthenticationLoader] = None


def get_authentication_loader(environment: str = None) -> SecureAuthenticationLoader:
    """Get the authentication loader singleton instance."""
    global _authentication_loader

    if environment is None:
        environment = os.getenv("FLASK_ENV", "development")

    if _authentication_loader is None or _authentication_loader.environment != environment:
        _authentication_loader = SecureAuthenticationLoader(environment)

    return _authentication_loader


def load_authentication_config(environment: str = None) -> Dict[str, Any]:
    """
    Convenience function to load authentication configuration.
    Returns the authentication configuration for the specified environment.
    """
    loader = get_authentication_loader(environment)
    config = loader.load_authentication_config()

    # Validate the configuration
    validation_error = loader.validate_config(config)
    if validation_error:
        logger.error(f"Authentication configuration validation failed: {validation_error}")
        if environment == "production":
            raise ValueError(f"Invalid authentication configuration: {validation_error}")
        else:
            logger.warning("Using default configuration due to validation failure")
            config = loader._get_default_config()

    # Log masked configuration for debugging
    if logger.isEnabledFor(logging.DEBUG):
        masked_config = loader.get_masked_config(config)
        logger.debug(f"Loaded authentication config: {masked_config}")

    return config
