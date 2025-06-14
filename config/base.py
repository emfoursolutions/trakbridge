# =============================================================================
# config/base.py - Base Configuration System
# =============================================================================

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import quote_plus

from .secrets import get_secret_manager, SecretManager

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads configuration from YAML files and combines with secrets."""

    def __init__(self, environment: str = "development"):
        self.environment = environment
        self.config_dir = Path(__file__).parent / "settings"
        self.secret_manager = get_secret_manager(environment)
        self._config_cache: Dict[str, Any] = {}

    def load_config_file(self, filename: str) -> Dict[str, Any]:
        """Load a YAML configuration file."""
        if filename in self._config_cache:
            return self._config_cache[filename]

        config_path = self.config_dir / filename
        if not config_path.exists():
            logger.warning(f"Configuration file not found: {config_path}")
            return {}

        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}

            self._config_cache[filename] = config
            logger.debug(f"Loaded configuration from {filename}")
            return config

        except Exception as e:
            logger.error(f"Failed to load configuration file {filename}: {e}")
            return {}

    def get_config_value(self, config: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        """Get a nested configuration value."""
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def merge_environment_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge environment-specific configuration."""
        base_config = config.get("default", {}).copy()
        env_config = self.get_config_value(config, "environments", self.environment, default={})

        # Deep merge environment config
        self._deep_merge(base_config, env_config)
        return base_config

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Deep merge two dictionaries."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value


class BaseConfig:
    """Base configuration class with common functionality."""

    def __init__(self, environment: str = None):
        self.environment = environment or os.environ.get('FLASK_ENV', 'development')
        self.loader = ConfigLoader(self.environment)
        self.secret_manager = get_secret_manager(self.environment)

        # Load all configuration
        self._load_configurations()

    def _load_configurations(self):
        """Load all configuration files."""
        # Load database configuration
        db_config = self.loader.load_config_file("database.yaml")
        self.db_config = self.loader.merge_environment_config(db_config)

        # Load application configuration
        app_config = self.loader.load_config_file("app.yaml")
        self.app_config = self.loader.merge_environment_config(app_config)

        # Load threading configuration
        threading_config = self.loader.load_config_file("threading.yaml")
        self.threading_config = self.loader.merge_environment_config(threading_config)

        # Load logging configuration
        logging_config = self.loader.load_config_file("logging.yaml")
        self.logging_config = self.loader.merge_environment_config(logging_config)

    @property
    def SECRET_KEY(self) -> str:
        """Get secret key from secure sources."""
        return self.secret_manager.get_secret(
            'SECRET_KEY',
            default='dev-secret-key-change-in-production',
            required=self.environment == 'production'
        )

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Build database URI from configuration and secrets."""
        db_type = self.secret_manager.get_secret('DB_TYPE', self.db_config.get('type', 'sqlite'))

        if db_type == 'sqlite':
            return self._build_sqlite_uri()
        elif db_type == 'mysql':
            return self._build_mysql_uri()
        elif db_type == 'postgresql':
            return self._build_postgresql_uri()
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _build_sqlite_uri(self) -> str:
        """Build SQLite database URI."""
        db_uri = self.secret_manager.get_secret('DATABASE_URL')
        if db_uri:
            return db_uri

        db_name = self.secret_manager.get_secret(
            'DB_NAME',
            self.db_config.get('defaults', {}).get('sqlite', {}).get('name', 'app.db')
        )

        if self.environment == 'testing':
            return self.db_config.get('database_uri', 'sqlite:///:memory:')

        db_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', db_name)
        return f'sqlite:///{db_path}'

    def _build_mysql_uri(self) -> str:
        """Build MySQL database URI."""
        defaults = self.db_config.get('defaults', {}).get('mysql', {})

        user = self.secret_manager.get_secret('DB_USER', defaults.get('user', 'root'))
        password = self.secret_manager.get_secret('DB_PASSWORD', '')
        host = self.secret_manager.get_secret('DB_HOST', defaults.get('host', 'localhost'))
        port = self.secret_manager.get_secret('DB_PORT', str(defaults.get('port', 3306)))
        name = self.secret_manager.get_secret('DB_NAME', defaults.get('name', 'trakbridge'))

        password_encoded = quote_plus(password) if password else ''
        return f'mysql+pymysql://{user}:{password_encoded}@{host}:{port}/{name}?charset=utf8mb4'

    def _build_postgresql_uri(self) -> str:
        """Build PostgreSQL database URI."""
        defaults = self.db_config.get('defaults', {}).get('postgresql', {})

        user = self.secret_manager.get_secret('DB_USER', defaults.get('user', 'postgres'))
        password = self.secret_manager.get_secret('DB_PASSWORD', '')
        host = self.secret_manager.get_secret('DB_HOST', defaults.get('host', 'localhost'))
        port = self.secret_manager.get_secret('DB_PORT', str(defaults.get('port', 5432)))
        name = self.secret_manager.get_secret('DB_NAME', defaults.get('name', 'trakbridge'))

        password_encoded = quote_plus(password) if password else ''
        return f'postgresql://{user}:{password_encoded}@{host}:{port}/{name}'

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Get database engine options."""
        db_type = self.secret_manager.get_secret('DB_TYPE', self.db_config.get('type', 'sqlite'))
        return self.db_config.get('engine_options', {}).get(db_type, {})

    @property
    def SQLALCHEMY_TRACK_MODIFICATIONS(self) -> bool:
        return self.db_config.get('track_modifications', False)

    @property
    def SQLALCHEMY_RECORD_QUERIES(self) -> bool:
        return self.db_config.get('record_queries', False)

    @property
    def SQLALCHEMY_SESSION_OPTIONS(self) -> Dict[str, Any]:
        return self.db_config.get('session_options', {})

    # Application settings
    @property
    def MAX_WORKER_THREADS(self) -> int:
        return int(self.secret_manager.get_secret(
            'MAX_WORKER_THREADS',
            str(self.threading_config.get('max_worker_threads', 4))
        ))

    @property
    def DEFAULT_POLL_INTERVAL(self) -> int:
        return int(self.secret_manager.get_secret(
            'DEFAULT_POLL_INTERVAL',
            str(self.app_config.get('default_poll_interval', 120))
        ))

    @property
    def MAX_CONCURRENT_STREAMS(self) -> int:
        return int(self.secret_manager.get_secret(
            'MAX_CONCURRENT_STREAMS',
            str(self.app_config.get('max_concurrent_streams', 50))
        ))

    @property
    def HTTP_TIMEOUT(self) -> int:
        return int(self.secret_manager.get_secret(
            'HTTP_TIMEOUT',
            str(self.app_config.get('http_timeout', 30))
        ))

    @property
    def HTTP_MAX_CONNECTIONS(self) -> int:
        return int(self.secret_manager.get_secret(
            'HTTP_MAX_CONNECTIONS',
            str(self.app_config.get('http_max_connections', 100))
        ))

    @property
    def HTTP_MAX_CONNECTIONS_PER_HOST(self) -> int:
        return int(self.secret_manager.get_secret(
            'HTTP_MAX_CONNECTIONS_PER_HOST',
            str(self.app_config.get('http_max_connections_per_host', 10))
        ))

    @property
    def ASYNC_TIMEOUT(self) -> int:
        return int(self.secret_manager.get_secret(
            'ASYNC_TIMEOUT',
            str(self.app_config.get('async_timeout', 60))
        ))

    @property
    def LOG_LEVEL(self) -> str:
        return self.secret_manager.get_secret(
            'LOG_LEVEL',
            self.logging_config.get('level', 'INFO')
        )

    @property
    def LOG_DIR(self) -> str:
        return self.secret_manager.get_secret(
            'LOG_DIR',
            self.logging_config.get('file_logging', {}).get('directory', 'logs')
        )

    @property
    def DEBUG(self) -> bool:
        """Get debug mode setting."""
        return self.secret_manager.get_secret(
            'DEBUG',
            str(self.app_config.get('debug', self.environment == 'development'))
        ).lower() == 'true'

    @property
    def TESTING(self) -> bool:
        """Get testing mode setting."""
        return self.environment == 'testing'

    def get_feature_flag(self, feature_name: str, default: bool = False) -> bool:
        """Get feature flag value."""
        features = self.app_config.get('features', {})
        env_features = features.get('environments', {}).get(self.environment, {})

        # Check environment-specific feature first, then global, then default
        if feature_name in env_features:
            return env_features[feature_name]
        elif feature_name in features:
            return features[feature_name]
        else:
            return default

    def get_api_setting(self, setting_path: str, default: Any = None) -> Any:
        """Get API-related setting using dot notation."""
        api_config = self.app_config.get('api', {})

        # Check environment-specific API settings first
        env_api_config = api_config.get('environments', {}).get(self.environment, {})

        # Split the path and traverse the config
        keys = setting_path.split('.')

        # Try environment-specific first
        value = self._get_nested_value(env_api_config, keys)
        if value is not None:
            return value

        # Try global API config
        value = self._get_nested_value(api_config, keys)
        if value is not None:
            return value

        return default

    def _get_nested_value(self, config: Dict[str, Any], keys: list) -> Any:
        """Get nested value from config using list of keys."""
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def validate_config(self) -> list:
        """Validate configuration and return list of issues."""
        issues = []

        # Validate required secrets in production
        if self.environment == 'production':
            required_secrets = ['SECRET_KEY']
            for secret in required_secrets:
                if not self.secret_manager.get_secret(secret):
                    issues.append(f"Required secret '{secret}' not found in production")

        # Validate database configuration
        try:
            self.SQLALCHEMY_DATABASE_URI
        except Exception as e:
            issues.append(f"Database configuration error: {e}")

        # Validate numeric settings
        numeric_settings = [
            ('MAX_WORKER_THREADS', self.MAX_WORKER_THREADS),
            ('DEFAULT_POLL_INTERVAL', self.DEFAULT_POLL_INTERVAL),
            ('MAX_CONCURRENT_STREAMS', self.MAX_CONCURRENT_STREAMS),
            ('HTTP_TIMEOUT', self.HTTP_TIMEOUT),
        ]

        for setting_name, value in numeric_settings:
            if not isinstance(value, int) or value <= 0:
                issues.append(f"Invalid {setting_name}: must be a positive integer")

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary (for debugging/inspection)."""
        return {
            'environment': self.environment,
            'database': {
                'type': self.secret_manager.get_secret('DB_TYPE', self.db_config.get('type', 'sqlite')),
                'track_modifications': self.SQLALCHEMY_TRACK_MODIFICATIONS,
                'record_queries': self.SQLALCHEMY_RECORD_QUERIES,
            },
            'application': {
                'debug': self.DEBUG,
                'testing': self.TESTING,
                'default_poll_interval': self.DEFAULT_POLL_INTERVAL,
                'max_concurrent_streams': self.MAX_CONCURRENT_STREAMS,
                'http_timeout': self.HTTP_TIMEOUT,
            },
            'threading': {
                'max_worker_threads': self.MAX_WORKER_THREADS,
            },
            'logging': {
                'level': self.LOG_LEVEL,
                'directory': self.LOG_DIR,
            }
        }