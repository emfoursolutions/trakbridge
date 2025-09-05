"""
File: config/validators.py

Description:
    Loads the configuration validation methods.

Author: Emfour Solutions
Created: 2025-07-05
"""

# Standard library imports
import ipaddress
import logging
import os
from pathlib import Path

# Third-party imports
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yaml

logger = logging.getLogger(__name__)


class ConfigValidator:
    """Comprehensive configuration validation system."""

    def __init__(self, environment: str):
        self.environment = environment
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_config(self, config_instance) -> Dict[str, List[str]]:
        """Validate complete configuration."""
        self.errors.clear()
        self.warnings.clear()

        # Validate core settings
        self._validate_database_config(config_instance)
        self._validate_app_config(config_instance)
        self._validate_security_config(config_instance)
        self._validate_network_config(config_instance)
        self._validate_logging_config(config_instance)

        # Environment-specific validation
        if self.environment == "production":
            self._validate_production_config(config_instance)
        elif self.environment == "development":
            self._validate_development_config(config_instance)
        elif self.environment == "testing":
            self._validate_testing_config(config_instance)

        return {"errors": self.errors.copy(), "warnings": self.warnings.copy()}

    def _validate_database_config(self, config):
        """Validate database configuration."""
        try:
            db_uri = config.SQLALCHEMY_DATABASE_URI

            # Validate URI format
            if not db_uri:
                self.errors.append("Database URI is required")
                return

            # Parse URI
            parsed = urlparse(db_uri)

            # Validate SQLite
            if parsed.scheme == "sqlite":
                if self.environment == "production":
                    self.warnings.append("SQLite is not recommended for production use")

                # Check if file path is writable
                if parsed.path and parsed.path != ":memory:":
                    db_path = Path(parsed.path)
                    if not db_path.parent.exists():
                        self.errors.append(f"Database directory does not exist: {db_path.parent}")
                    elif not os.access(db_path.parent, os.W_OK):
                        self.errors.append(f"Database directory is not writable: {db_path.parent}")

            # Validate MySQL/PostgreSQL
            elif parsed.scheme in ["mysql", "postgresql"]:
                if not parsed.hostname:
                    self.errors.append("Database host is required for MySQL/PostgreSQL")
                if not parsed.username:
                    self.errors.append("Database username is required for MySQL/PostgreSQL")
                if not parsed.path or parsed.path == "/":
                    self.errors.append("Database name is required for MySQL/PostgreSQL")

            # Validate engine options
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
            if engine_options:
                self._validate_engine_options(engine_options)

        except Exception as e:
            self.errors.append(f"Database configuration validation failed: {e}")

    def _validate_engine_options(self, options: Dict[str, Any]):
        """Validate database engine options."""
        # Validate pool settings
        if "pool_size" in options:
            pool_size = options["pool_size"]
            if not isinstance(pool_size, int) or pool_size < 1:
                self.errors.append("pool_size must be a positive integer")
            elif pool_size > 100:
                self.warnings.append("pool_size is very large (>100), consider reducing")

        if "max_overflow" in options:
            max_overflow = options["max_overflow"]
            if not isinstance(max_overflow, int) or max_overflow < 0:
                self.errors.append("max_overflow must be a non-negative integer")

        if "pool_timeout" in options:
            pool_timeout = options["pool_timeout"]
            if not isinstance(pool_timeout, (int, float)) or pool_timeout < 0:
                self.errors.append("pool_timeout must be a non-negative number")

    def _validate_app_config(self, config):
        """Validate application configuration."""
        # Validate worker threads
        max_workers = config.MAX_WORKER_THREADS
        if not isinstance(max_workers, int) or max_workers < 1:
            self.errors.append("MAX_WORKER_THREADS must be a positive integer")
        elif max_workers > 100:
            self.warnings.append("MAX_WORKER_THREADS is very large (>100)")

        # Validate concurrent streams
        max_streams = config.MAX_CONCURRENT_STREAMS
        if not isinstance(max_streams, int) or max_streams < 1:
            self.errors.append("MAX_CONCURRENT_STREAMS must be a positive integer")
        elif max_streams > 1000:
            self.warnings.append("MAX_CONCURRENT_STREAMS is very large (>1000)")

        # Validate timeouts
        timeouts = [
            ("HTTP_TIMEOUT", config.HTTP_TIMEOUT),
            ("ASYNC_TIMEOUT", config.ASYNC_TIMEOUT),
            ("DEFAULT_POLL_INTERVAL", config.DEFAULT_POLL_INTERVAL),
        ]

        for name, value in timeouts:
            if not isinstance(value, int) or value < 1:
                self.errors.append(f"{name} must be a positive integer")
            elif value > 3600:
                self.warnings.append(f"{name} is very large (>1 hour)")

    def _validate_security_config(self, config):
        """Validate security configuration."""
        # Validate secret key
        secret_key = config.SECRET_KEY
        if not secret_key:
            self.errors.append("SECRET_KEY is required")
        elif len(secret_key) < 16:
            self.errors.append("SECRET_KEY must be at least 16 characters long")
        elif secret_key == "dev-secret-key-change-in-production":
            if self.environment == "production":
                self.errors.append("SECRET_KEY must be changed from default in production")
            else:
                self.warnings.append("Using default SECRET_KEY - change for production")

    def _validate_network_config(self, config):
        """Validate network-related configuration."""
        # Validate HTTP settings
        http_max_conn = config.HTTP_MAX_CONNECTIONS
        if not isinstance(http_max_conn, int) or http_max_conn < 1:
            self.errors.append("HTTP_MAX_CONNECTIONS must be a positive integer")

        http_max_conn_per_host = config.HTTP_MAX_CONNECTIONS_PER_HOST
        if not isinstance(http_max_conn_per_host, int) or http_max_conn_per_host < 1:
            self.errors.append("HTTP_MAX_CONNECTIONS_PER_HOST must be a positive integer")

        if http_max_conn_per_host > http_max_conn:
            self.warnings.append(
                "HTTP_MAX_CONNECTIONS_PER_HOST should not exceed HTTP_MAX_CONNECTIONS"
            )

    def _validate_logging_config(self, config):
        """Validate logging configuration."""
        # Validate log level
        log_level = config.LOG_LEVEL
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if log_level not in valid_levels:
            self.errors.append(f"LOG_LEVEL must be one of: {', '.join(valid_levels)}")

        # Validate log directory
        log_dir = config.LOG_DIR
        if log_dir:
            log_path = Path(log_dir)
            if not log_path.exists():
                try:
                    log_path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    self.errors.append(f"Cannot create log directory {log_dir}: {e}")
            elif not os.access(log_path, os.W_OK):
                self.errors.append(f"Log directory is not writable: {log_dir}")

    def _validate_production_config(self, config):
        """Production-specific validation."""
        # Require secure settings
        if config.DEBUG:
            self.errors.append("DEBUG must be False in production")

        if config.SQLALCHEMY_RECORD_QUERIES:
            self.warnings.append(
                "SQLALCHEMY_RECORD_QUERIES should be False in production for performance"
            )

        # Validate timeouts for production
        if config.HTTP_TIMEOUT < 30:
            self.warnings.append("HTTP_TIMEOUT should be at least 30 seconds in production")

        if config.MAX_WORKER_THREADS < 4:
            self.warnings.append("MAX_WORKER_THREADS should be at least 4 in production")

        # Check for external database SSL
        db_uri = config.SQLALCHEMY_DATABASE_URI
        if db_uri and "localhost" not in db_uri and "127.0.0.1" not in db_uri:
            self.warnings.append("External database detected - ensure SSL/TLS is configured")

    def _validate_development_config(self, config):
        """Development-specific validation."""
        if not config.DEBUG:
            self.warnings.append("DEBUG should be True in development for better debugging")

        if config.HTTP_TIMEOUT > 60:
            self.warnings.append("HTTP_TIMEOUT is very high for development")

    def _validate_testing_config(self, config):
        """Testing-specific validation."""
        if not config.TESTING:
            self.errors.append("TESTING must be True in testing environment")

        if config.DEBUG:
            self.warnings.append("DEBUG should be False in testing for consistent behavior")

        # Validate test database
        db_uri = config.SQLALCHEMY_DATABASE_URI
        if ":memory:" not in db_uri and "test" not in db_uri.lower():
            self.warnings.append("Testing should use in-memory or test-specific database")


class ConfigTypeChecker:
    """Type checking for configuration values."""

    @staticmethod
    def validate_string(value: Any, field_name: str) -> Optional[str]:
        """Validate string value."""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        return None

    @staticmethod
    def validate_integer(
        value: Any, field_name: str, min_value: int = None, max_value: int = None
    ) -> Optional[str]:
        """Validate integer value."""
        if not isinstance(value, int):
            return f"{field_name} must be an integer"
        if min_value is not None and value < min_value:
            return f"{field_name} must be at least {min_value}"
        if max_value is not None and value > max_value:
            return f"{field_name} must be at most {max_value}"
        return None

    @staticmethod
    def validate_boolean(value: Any, field_name: str) -> Optional[str]:
        """Validate boolean value."""
        if not isinstance(value, bool):
            return f"{field_name} must be a boolean"
        return None

    @staticmethod
    def validate_url(value: Any, field_name: str) -> Optional[str]:
        """Validate URL value."""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        try:
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                return f"{field_name} must be a valid URL"
        except Exception:
            return f"{field_name} must be a valid URL"
        return None

    @staticmethod
    def validate_ip_address(value: Any, field_name: str) -> Optional[str]:
        """Validate IP address value."""
        if not isinstance(value, str):
            return f"{field_name} must be a string"
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return f"{field_name} must be a valid IP address"
        return None

    @staticmethod
    def validate_port(value: Any, field_name: str) -> Optional[str]:
        """Validate port number."""
        error = ConfigTypeChecker.validate_integer(value, field_name, 1, 65535)
        if error:
            return error
        return None


def validate_config_file(file_path: str) -> List[str]:
    """Validate YAML configuration file syntax."""
    errors = []
    try:
        with open(file_path, "r") as f:
            yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error in {file_path}: {e}")
    except Exception as e:
        errors.append(f"Error reading {file_path}: {e}")
    return errors
