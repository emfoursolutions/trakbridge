"""
File: config/environments.py

Description:
    Loads the Environment Variable Configuration for TrakBridge

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import os

# Third-party imports
from typing import Any, Dict

# Local application imports
from .base import BaseConfig

logger = logging.getLogger(__name__)


class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""

    def __init__(self):
        super().__init__("development")

    @property
    def DEBUG(self) -> bool:
        """Enable debug mode in development."""
        return True

    @property
    def SQLALCHEMY_RECORD_QUERIES(self) -> bool:
        """Enable query recording in development."""
        return True

    @property
    def LOG_LEVEL(self) -> str:
        """Use DEBUG logging level in development."""
        return self.secret_manager.get_secret("LOG_LEVEL", "DEBUG")

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Development-specific database engine options."""
        base_options = super().SQLALCHEMY_ENGINE_OPTIONS
        db_type = self.secret_manager.get_secret(
            "DB_TYPE", self.db_config.get("type", "sqlite")
        )

        # Development-specific overrides
        dev_overrides = {
            "sqlite": {
                "echo": self.get_feature_flag("enable_sql_echo", False),
                "pool_pre_ping": True,
                "pool_recycle": 300,
                "connect_args": {"check_same_thread": False, "timeout": 20},
            },
            "mysql": {
                "echo": self.get_feature_flag("enable_sql_echo", False),
                "pool_pre_ping": True,
                "pool_recycle": 1800,  # 30 minutes
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
                "connect_args": {
                    "connect_timeout": 60,
                    "read_timeout": 30,
                    "write_timeout": 30,
                },
            },
            "postgresql": {
                "echo": self.get_feature_flag("enable_sql_echo", False),
                "pool_pre_ping": True,
                "pool_recycle": 1800,  # 30 minutes
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
                "connect_args": {
                    "connect_timeout": 10,
                    "application_name": "TrakBridge_Dev",
                },
            },
        }

        # Merge base options with development overrides
        if db_type in dev_overrides:
            merged_options = base_options.copy()
            merged_options.update(dev_overrides[db_type])
            return merged_options

        return base_options


class ProductionConfig(BaseConfig):
    """Production environment configuration."""

    def __init__(self):
        super().__init__("production")

    @property
    def DEBUG(self) -> bool:
        """Disable debug mode in production."""
        return False

    @property
    def SQLALCHEMY_RECORD_QUERIES(self) -> bool:
        """Disable query recording in production for performance."""
        return False

    @property
    def SECRET_KEY(self) -> str:
        """Require secret key in production."""
        secret_key = self.secret_manager.get_secret("SECRET_KEY", required=True)
        if not secret_key or secret_key == "dev-secret-key-change-in-production":
            raise ValueError("SECRET_KEY must be set to a secure value in production")
        return secret_key

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Production-optimized database engine options."""
        base_options = super().SQLALCHEMY_ENGINE_OPTIONS
        db_type = self.secret_manager.get_secret(
            "DB_TYPE", self.db_config.get("type", "sqlite")
        )

        # Production-specific overrides
        prod_overrides = {
            "sqlite": {
                # SQLite not recommended for production, but if used:
                "pool_pre_ping": True,
                "pool_recycle": 300,
                "connect_args": {"check_same_thread": False, "timeout": 30},
            },
            "mysql": {
                "pool_pre_ping": True,
                "pool_recycle": 3600,  # 1 hour
                "pool_size": 50,
                "max_overflow": 100,
                "pool_timeout": 60,
                "connect_args": {
                    "connect_timeout": 30,
                    "read_timeout": 60,
                    "write_timeout": 60,
                    "autocommit": False,
                },
            },
            "postgresql": {
                "pool_pre_ping": True,
                "pool_recycle": 3600,  # 1 hour
                "pool_size": 50,
                "max_overflow": 100,
                "pool_timeout": 60,
                "connect_args": {
                    "connect_timeout": 10,
                    "application_name": "TrakBridge_Prod",
                    "sslmode": "prefer",
                },
            },
        }

        # Merge base options with production overrides
        if db_type in prod_overrides:
            merged_options = base_options.copy()
            merged_options.update(prod_overrides[db_type])
            return merged_options

        return base_options

    @property
    def MAX_WORKER_THREADS(self) -> int:
        """Enhanced thread pool for production."""
        return int(
            self.secret_manager.get_secret(
                "MAX_WORKER_THREADS",
                str(self.threading_config.get("max_worker_threads", 8)),
            )
        )

    @property
    def MAX_CONCURRENT_STREAMS(self) -> int:
        """Enhanced concurrent streams for production."""
        return int(
            self.secret_manager.get_secret(
                "MAX_CONCURRENT_STREAMS",
                str(self.app_config.get("max_concurrent_streams", 200)),
            )
        )

    def validate_config(self) -> list:
        """Enhanced validation for production environment."""
        issues = super().validate_config()

        # Additional production-specific validations
        if self.secret_manager.get_secret("DB_TYPE", "sqlite") == "sqlite":
            issues.append("SQLite is not recommended for production use")

        # Check for secure settings
        if self.HTTP_TIMEOUT < 30:
            issues.append("HTTP_TIMEOUT should be at least 30 seconds in production")

        if self.MAX_WORKER_THREADS < 4:
            issues.append("MAX_WORKER_THREADS should be at least 4 in production")

        # Check for SSL/TLS settings if using external databases
        db_type = self.secret_manager.get_secret("DB_TYPE", "sqlite")
        if db_type in ["mysql", "postgresql"]:
            db_host = self.secret_manager.get_secret("DB_HOST", "localhost")
            if db_host not in ["localhost", "127.0.0.1"]:
                # External database - recommend SSL
                logger.warning(
                    "Using external database without explicit SSL configuration"
                )

        return issues


class TestingConfig(BaseConfig):
    """Testing environment configuration."""

    def __init__(self):
        super().__init__("testing")

    @property
    def TESTING(self) -> bool:
        """Enable testing mode."""
        return True

    @property
    def DEBUG(self) -> bool:
        """Disable debug mode in testing for cleaner output."""
        return False

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Use in-memory database for testing."""
        return "sqlite:///:memory:"

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Simplified engine options for testing."""
        return {"pool_pre_ping": False, "connect_args": {"check_same_thread": False}}

    @property
    def MAX_WORKER_THREADS(self) -> int:
        """Reduced thread pool for testing."""
        return 2

    @property
    def MAX_CONCURRENT_STREAMS(self) -> int:
        """Reduced concurrent streams for testing."""
        return 5

    @property
    def HTTP_TIMEOUT(self) -> int:
        """Reduced timeout for faster tests."""
        return 5

    @property
    def DEFAULT_POLL_INTERVAL(self) -> int:
        """Reduced poll interval for faster tests."""
        return 5

    @property
    def ASYNC_TIMEOUT(self) -> int:
        """Reduced async timeout for faster tests."""
        return 10

    @property
    def LOG_LEVEL(self) -> str:
        """Use WARNING level to reduce test output noise."""
        return self.secret_manager.get_secret("LOG_LEVEL", "WARNING")


class StagingConfig(ProductionConfig):
    """Staging environment configuration - inherits from production but with some relaxed settings."""

    def __init__(self):
        super().__init__()
        self.environment = "staging"
        # Reload configurations with staging environment
        self.loader.environment = "staging"
        self._load_configurations()

    @property
    def DEBUG(self) -> bool:
        """Allow debug mode in staging if explicitly set."""
        return self.secret_manager.get_secret("DEBUG", "false").lower() == "true"

    @property
    def SQLALCHEMY_RECORD_QUERIES(self) -> bool:
        """Allow query recording in staging for debugging."""
        return (
            self.secret_manager.get_secret("SQLALCHEMY_RECORD_QUERIES", "false").lower()
            == "true"
        )

    @property
    def LOG_LEVEL(self) -> str:
        """Use INFO level in staging by default."""
        return self.secret_manager.get_secret("LOG_LEVEL", "INFO")

    @property
    def MAX_WORKER_THREADS(self) -> int:
        """Moderate thread pool for staging."""
        return int(
            self.secret_manager.get_secret(
                "MAX_WORKER_THREADS",
                str(self.threading_config.get("max_worker_threads", 6)),
            )
        )

    @property
    def MAX_CONCURRENT_STREAMS(self) -> int:
        """Moderate concurrent streams for staging."""
        return int(
            self.secret_manager.get_secret(
                "MAX_CONCURRENT_STREAMS",
                str(self.app_config.get("max_concurrent_streams", 100)),
            )
        )

    def validate_config(self) -> list:
        """Relaxed validation for staging environment."""
        issues = []

        # Basic validation without strict production requirements
        try:
            self.SQLALCHEMY_DATABASE_URI
        except Exception as e:
            issues.append(f"Database configuration error: {e}")

        # Check numeric settings
        if self.MAX_WORKER_THREADS <= 0:
            issues.append("MAX_WORKER_THREADS must be positive")

        if self.MAX_CONCURRENT_STREAMS <= 0:
            issues.append("MAX_CONCURRENT_STREAMS must be positive")

        return issues


# Configuration factory
def get_config(environment: str = None) -> BaseConfig:
    """Get configuration instance for the specified environment."""
    if environment is None:
        environment = os.environ.get("FLASK_ENV", "development")

    config_map = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
        "staging": StagingConfig,
    }

    config_class = config_map.get(environment)
    if not config_class:
        logger.warning(f"Unknown environment '{environment}', using development config")
        config_class = DevelopmentConfig

    return config_class()


# Configuration dictionary for backwards compatibility
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "staging": StagingConfig,
    "default": DevelopmentConfig,
}
