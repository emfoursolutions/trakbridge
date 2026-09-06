"""
File: config/base.py

Description:
    Loads the Base Configuration for TrakBridge

Author: Emfour Solutions
Created: 2025-07-05
"""

# Standard library imports
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote_plus

# Third-party imports
import yaml

# Local application imports
from .authentication_loader import load_authentication_config
from .secrets import get_secret_manager
from .validator import ConfigValidationError, ConfigValidator

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads configuration from YAML files with multi-source support and combines with secrets."""

    def __init__(self, environment: str = "development"):
        self.environment = environment

        # Multi-source configuration directories
        self.external_config_dir = Path(
            os.environ.get("TRAKBRIDGE_CONFIG_DIR", "/app/external_config")
        )
        self.bundled_config_dir = Path(__file__).parent / "settings"

        # Backup dir for corrupted config files (created lazily on first
        # backup — not at init, to avoid failing when running under a user
        # that cannot mkdir the target).
        self.backup_dir = Path(
            os.environ.get("TRAKBRIDGE_BACKUP_DIR", "/app/backups")
        )

        # Legacy compatibility
        self.config_dir = self.bundled_config_dir

        self.secret_manager = get_secret_manager(environment)
        self.validator = ConfigValidator()
        self._config_cache: Dict[str, Any] = {}

        # Log configuration source information
        logger.info("Configuration sources:")
        logger.info(
            f"  External: {self.external_config_dir} (exists: {self.external_config_dir.exists()})"
        )
        logger.info(
            f"  Bundled:  {self.bundled_config_dir} (exists: {self.bundled_config_dir.exists()})"
        )

    def load_config_file(self, filename: str) -> Dict[str, Any]:
        """
        Load a YAML configuration file with multi-source support.

        Priority order:
        1. External config directory (mounted volume)
        2. Bundled config directory (container defaults)
        """
        cache_key = f"{filename}:{self.environment}"
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]

        config = {}
        config_sources = []

        # Try external config first (highest priority)
        external_path = self.external_config_dir / filename
        if external_path.exists():
            try:
                with open(external_path, "r") as f:
                    external_config = yaml.safe_load(f) or {}
                config.update(external_config)
                config_sources.append(f"external:{external_path}")
                logger.debug(f"Loaded external config from {external_path}")
            except Exception as e:
                logger.error(f"Failed to load external config {external_path}: {e}")

        # Try bundled config as fallback
        bundled_path = self.bundled_config_dir / filename
        if bundled_path.exists():
            try:
                with open(bundled_path, "r") as f:
                    bundled_config = yaml.safe_load(f) or {}

                # If we have external config, merge bundled as defaults
                if config:
                    # Deep merge: bundled provides defaults, external overrides
                    merged_config = self._deep_merge_configs(bundled_config, config)
                    config = merged_config
                    config_sources.append(f"bundled:{bundled_path} (merged)")
                else:
                    # No external config, use bundled as primary
                    config = bundled_config
                    config_sources.append(f"bundled:{bundled_path}")

                logger.debug(f"Loaded bundled config from {bundled_path}")
            except Exception as e:
                logger.error(f"Failed to load bundled config {bundled_path}: {e}")

        # Log the effective configuration source
        if config_sources:
            logger.info(
                f"Configuration '{filename}' loaded from: {', '.join(config_sources)}"
            )
        else:
            logger.warning(f"Configuration file '{filename}' not found in any source")

        # Cache the merged result
        self._config_cache[cache_key] = config
        return config

    def _deep_merge_configs(
        self, base_config: Dict[str, Any], override_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Deep merge two configuration dictionaries.

        Args:
            base_config: Base configuration (provides defaults)
            override_config: Override configuration (takes precedence)

        Returns:
            Merged configuration dictionary
        """
        result = base_config.copy()

        for key, value in override_config.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                # Recursively merge nested dictionaries
                result[key] = self._deep_merge_configs(result[key], value)
            else:
                # Override the value
                result[key] = value

        return result

    @staticmethod
    def get_config_value(
        config: Dict[str, Any], *keys: str, default: Any = None
    ) -> Any:
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
        env_config = self.get_config_value(
            config, "environments", self.environment, default={}
        )

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

    # ------------------------------------------------------------------ #
    # Safe-load path: validation, backup, auto-repair, minimal fallback.
    # External-first, SINGLE-SOURCE (no deep merge) — used for files where
    # accidental list-merging would be a security risk (plugins.yaml
    # whitelist, performance.yaml circuit breaker config).
    # ------------------------------------------------------------------ #
    def load_config_safe(
        self,
        config_name: str,
        required_fields: Optional[List[str]] = None,
        validate: bool = True,
    ) -> Dict[str, Any]:
        """
        Load a config file with validation, auto-backup + auto-repair on
        corruption, and a minimal-default fallback of last resort.

        External file wins over bundled — no merge. On external validation
        failure the corrupted file is backed up (best-effort; a failing
        backup does NOT block the load) and replaced with the bundled
        default. If both external and bundled are missing/invalid, the
        validator's minimal default is returned.
        """
        external_path = self.external_config_dir / config_name
        bundled_path = self.bundled_config_dir / config_name

        if external_path.exists():
            try:
                data = self._load_and_validate(
                    external_path, config_name, required_fields, validate
                )
                logger.info(f"Loaded external config from {external_path}")
                return data
            except Exception as e:
                logger.error(
                    f"External config failed validation: {external_path} - {e}"
                )
                self._backup_corrupted_file(external_path, str(e))
                repaired = self._auto_repair_from_bundled(
                    external_path, bundled_path, config_name, required_fields, validate
                )
                if repaired is not None:
                    return repaired

        if bundled_path.exists():
            try:
                data = self._load_and_validate(
                    bundled_path, config_name, required_fields, validate
                )
                logger.info(f"Using bundled config: {bundled_path}")
                return data
            except Exception as e:
                logger.error(f"Bundled config failed validation: {bundled_path} - {e}")

        logger.warning(f"Using minimal default configuration for {config_name}")
        return self.validator.minimal_default(config_name)

    def _load_and_validate(
        self,
        file_path: Path,
        config_name: str,
        required_fields: Optional[List[str]],
        validate: bool,
    ) -> Dict[str, Any]:
        """Delegate to ConfigValidator unless caller opted out of schema check."""
        if validate:
            return self.validator.load_and_validate(
                file_path, config_name, required_fields
            )
        # No-schema path: still parse + require dict + honor required_fields
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            raise ConfigValidationError(
                "Configuration file is empty", str(file_path)
            )
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Invalid YAML syntax: {e}", str(file_path)
            )
        if not isinstance(data, dict):
            raise ConfigValidationError(
                f"Configuration must be a dictionary, got {type(data).__name__}",
                str(file_path),
            )
        if required_fields:
            for field in required_fields:
                if field not in data:
                    raise ConfigValidationError(
                        f"Required field '{field}' is missing",
                        str(file_path),
                        field,
                    )
        return data

    def _backup_corrupted_file(self, file_path: Path, error_message: str) -> None:
        """
        Copy a corrupted config file to backup_dir with a timestamped name +
        .error sidecar. Best-effort: any failure (permission denied,
        unwritable dir) is logged but does NOT propagate — the load path
        must remain resilient.
        """
        if not file_path.exists():
            return
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(
                f"Cannot create backup dir {self.backup_dir}: {e} — skipping backup"
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{file_path.name}.corrupted.{timestamp}"
        try:
            shutil.copy2(file_path, backup_path)
            error_file = backup_path.with_suffix(backup_path.suffix + ".error")
            with open(error_file, "w") as f:
                f.write(f"Backup created: {datetime.now().isoformat()}\n")
                f.write(f"Original file: {file_path}\n")
                f.write(f"Error: {error_message}\n")
            logger.info(f"Backed up corrupted config to: {backup_path}")
        except OSError as e:
            logger.warning(f"Failed to backup corrupted config: {e}")

    def _auto_repair_from_bundled(
        self,
        external_path: Path,
        bundled_path: Path,
        config_name: str,
        required_fields: Optional[List[str]],
        validate: bool,
    ) -> Optional[Dict[str, Any]]:
        """Copy bundled default over the corrupted external file and reload."""
        if not bundled_path.exists():
            return None
        logger.info(
            f"Auto-repairing: replacing corrupted {external_path} with bundled default"
        )
        try:
            shutil.copy2(bundled_path, external_path)
            data = self._load_and_validate(
                external_path, config_name, required_fields, validate
            )
            logger.info(f"Auto-repair successful for {config_name}")
            return data
        except (OSError, ConfigValidationError) as e:
            logger.error(f"Auto-repair failed: {e}")
            return None

    def validate_all_configs(self) -> Dict[str, Union[bool, str]]:
        """
        Validate every YAML config found in the bundled dir. Returns a dict
        mapping filename to True (valid) or an error-message string.
        """
        results: Dict[str, Union[bool, str]] = {}
        if not self.bundled_config_dir.exists():
            return results
        for path in self.bundled_config_dir.glob("*.yaml"):
            config_name = path.name
            try:
                self.load_config_safe(config_name)
                results[config_name] = True
            except Exception as e:
                results[config_name] = str(e)
        return results


# Module-level lazy singleton — parallels get_secret_manager. Reuse via
# get_config_loader() so callers share one instance and avoid duplicate
# startup logging on every plugin reload.
_config_loader_instance: Optional["ConfigLoader"] = None


def get_config_loader() -> "ConfigLoader":
    """Return the shared ConfigLoader singleton, creating it on first call."""
    global _config_loader_instance
    if _config_loader_instance is None:
        environment = os.environ.get("FLASK_ENV", "development")
        _config_loader_instance = ConfigLoader(environment)
    return _config_loader_instance


class BaseConfig:
    """Base configuration class with common functionality."""

    def __init__(self, environment: str = None):
        self.environment = environment or os.environ.get("FLASK_ENV", "development")
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

        # Load authentication configuration using secure loader
        try:
            auth_config_raw = load_authentication_config(self.environment)
            self.auth_config = auth_config_raw.get("authentication", {})
            logger.info("Loaded authentication configuration using secure loader")
        except Exception as e:
            logger.error(f"Failed to load authentication config: {e}")
            # Fallback to default authentication config
            self.auth_config = {
                "session": {
                    "lifetime_hours": 8,
                    "secure_cookies": self.environment == "production",
                },
                "provider_priority": ["local"],
                "providers": {
                    "local": {"enabled": True},
                    "ldap": {"enabled": False},
                    "oidc": {"enabled": False},
                },
            }
            logger.warning("Using fallback authentication configuration")

    @property
    def SECRET_KEY(self) -> str:
        """Get secret key from secure sources."""
        return self.secret_manager.get_secret(
            "SECRET_KEY",
            default="dev-secret-key-change-in-production",
            required=self.environment == "production",
        )

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Build database URI from configuration and secrets."""
        # Check if explicit DB_TYPE is set - this takes precedence over DATABASE_URL
        explicit_db_type = self.secret_manager.get_secret("DB_TYPE")

        if explicit_db_type:
            # DB_TYPE explicitly set - build URI from components regardless of DATABASE_URL
            db_type = explicit_db_type
            if db_type == "sqlite":
                return self._build_sqlite_uri()
            elif db_type == "mysql":
                return self._build_mysql_uri()
            elif db_type == "postgresql":
                return self._build_postgresql_uri()
            else:
                raise ValueError(f"Unsupported database type: {db_type}")

        # Check for explicit DATABASE_URL (fallback when DB_TYPE not set)
        database_url = self.secret_manager.get_secret("DATABASE_URL")
        if database_url:
            return database_url

        # Fall back to building URI from configuration defaults
        db_type = self._get_database_type()

        if db_type == "sqlite":
            return self._build_sqlite_uri()
        elif db_type == "mysql":
            return self._build_mysql_uri()
        elif db_type == "postgresql":
            return self._build_postgresql_uri()
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _build_sqlite_uri(self) -> str:
        """Build SQLite database URI."""
        # Note: DATABASE_URL precedence is handled in SQLALCHEMY_DATABASE_URI property
        # This method builds URI from individual components when DB_TYPE=sqlite is explicitly set

        db_name = self.secret_manager.get_secret(
            "DB_NAME",
            self.db_config.get("defaults", {})
            .get("sqlite", {})
            .get("name", "data/app.db"),
        )

        # For testing environment, use in-memory database unless explicit DB_NAME is provided
        if self.environment == "testing" and not self.secret_manager.get_secret(
            "DB_NAME"
        ):
            return self.db_config.get("database_uri", "sqlite:///:memory:")

        # For Docker/production, use absolute paths; for development, use relative to app root
        if os.path.isabs(db_name):
            db_path = db_name
        else:
            # Use app root directory (parent of config directory) as base path
            app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            db_path = os.path.join(app_root, db_name)
        return f"sqlite:///{db_path}"

    def _build_mysql_uri(self) -> str:
        """Build MySQL/MariaDB database URI with compatibility parameters."""
        defaults = self.db_config.get("defaults", {}).get("mysql", {})

        user = self.secret_manager.get_secret("DB_USER", defaults.get("user", "root"))
        password = self.secret_manager.get_secret("DB_PASSWORD", "")
        host = self.secret_manager.get_secret(
            "DB_HOST", defaults.get("host", "localhost")
        )
        port = self.secret_manager.get_secret(
            "DB_PORT", str(defaults.get("port", 3306))
        )
        name = self.secret_manager.get_secret(
            "DB_NAME", defaults.get("name", "trakbridge_db")
        )

        password_encoded = quote_plus(password) if password else ""

        # Build base URI with MariaDB 11 compatibility parameters
        base_uri = f"mysql+pymysql://{user}:{password_encoded}@{host}:{port}/{name}"

        # Basic connection parameters (detailed config handled in connect_args)
        params = [
            "charset=utf8mb4",  # Ensure UTF-8 encoding
        ]

        return f"{base_uri}?{'&'.join(params)}"

    def _build_postgresql_uri(self) -> str:
        """Build PostgreSQL database URI."""
        defaults = self.db_config.get("defaults", {}).get("postgresql", {})

        user = self.secret_manager.get_secret(
            "DB_USER", defaults.get("user", "postgres")
        )
        password = self.secret_manager.get_secret("DB_PASSWORD", "")
        host = self.secret_manager.get_secret(
            "DB_HOST", defaults.get("host", "localhost")
        )
        port = self.secret_manager.get_secret(
            "DB_PORT", str(defaults.get("port", 5432))
        )
        name = self.secret_manager.get_secret(
            "DB_NAME", defaults.get("name", "trakbridge_db")
        )

        password_encoded = quote_plus(password) if password else ""
        return f"postgresql+psycopg2://{user}:{password_encoded}@{host}:{port}/{name}"

    def _get_database_type(self) -> str:
        """
        Determine database type from configuration or DATABASE_URL.

        Priority order:
        1. Explicit DB_TYPE environment variable (highest priority)
        2. Database type from DATABASE_URL scheme
        3. Configuration file default
        4. Fallback to sqlite
        """
        # Check explicit DB_TYPE first (highest priority)
        explicit_type = self.secret_manager.get_secret("DB_TYPE")
        if explicit_type:
            return explicit_type

        # Try to detect from DATABASE_URL scheme
        database_url = self.secret_manager.get_secret("DATABASE_URL")
        if database_url:
            if database_url.startswith("postgresql://") or database_url.startswith(
                "postgres://"
            ):
                return "postgresql"
            elif database_url.startswith("mysql://") or database_url.startswith(
                "mysql+"
            ):
                return "mysql"
            elif database_url.startswith("sqlite://"):
                return "sqlite"

        # Fall back to config file or default
        return self.db_config.get("type", "sqlite")

    @property
    def SQLALCHEMY_ENGINE_OPTIONS(self) -> Dict[str, Any]:
        """Get database engine options."""
        db_type = self._get_database_type()
        engine_options = (
            self.db_config.get("engine_options", {}).get(db_type, {}).copy()
        )

        # SQLite validation: Remove pool settings that SQLite doesn't support
        if db_type == "sqlite":
            invalid_sqlite_options = ["pool_size", "max_overflow", "pool_timeout"]
            for option in invalid_sqlite_options:
                if option in engine_options:
                    logger.warning(f"Removing invalid SQLite engine option: {option}")
                    engine_options.pop(option)

        return engine_options

    @property
    def SQLALCHEMY_TRACK_MODIFICATIONS(self) -> bool:
        return self.db_config.get("track_modifications", False)

    @property
    def SQLALCHEMY_RECORD_QUERIES(self) -> bool:
        return self.db_config.get("record_queries", False)

    @property
    def SQLALCHEMY_SESSION_OPTIONS(self) -> Dict[str, Any]:
        return self.db_config.get("session_options", {})

    # Application settings
    @property
    def MAX_WORKER_THREADS(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "MAX_WORKER_THREADS",
                str(self.threading_config.get("max_worker_threads", 4)),
            )
        )

    @property
    def DEFAULT_POLL_INTERVAL(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "DEFAULT_POLL_INTERVAL",
                str(self.app_config.get("default_poll_interval", 120)),
            )
        )

    @property
    def MAX_CONCURRENT_STREAMS(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "MAX_CONCURRENT_STREAMS",
                str(self.app_config.get("max_concurrent_streams", 50)),
            )
        )

    @property
    def HTTP_TIMEOUT(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "HTTP_TIMEOUT", str(self.app_config.get("http_timeout", 30))
            )
        )

    @property
    def HTTP_MAX_CONNECTIONS(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "HTTP_MAX_CONNECTIONS",
                str(self.app_config.get("http_max_connections", 100)),
            )
        )

    @property
    def HTTP_MAX_CONNECTIONS_PER_HOST(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "HTTP_MAX_CONNECTIONS_PER_HOST",
                str(self.app_config.get("http_max_connections_per_host", 10)),
            )
        )

    @property
    def ASYNC_TIMEOUT(self) -> int:
        return int(
            self.secret_manager.get_secret(
                "ASYNC_TIMEOUT", str(self.app_config.get("async_timeout", 60))
            )
        )

    @property
    def LOG_LEVEL(self) -> str:
        return self.secret_manager.get_secret(
            "LOG_LEVEL", self.logging_config.get("level", "INFO")
        )

    @property
    def LOG_DIR(self) -> str:
        return self.secret_manager.get_secret(
            "LOG_DIR",
            self.logging_config.get("file_logging", {}).get("directory", "logs"),
        )

    @property
    def DEBUG(self) -> bool:
        """Get debug mode setting."""
        return (
            self.secret_manager.get_secret(
                "DEBUG",
                str(self.app_config.get("debug", self.environment == "development")),
            ).lower()
            == "true"
        )

    @property
    def APPLICATION_URL(self) -> str:
        """Get application URL from secure sources."""
        return self.secret_manager.get_secret(
            "TRAKBRIDGE_APPLICATION_URL",
            self.app_config.get("application_url", "https://localhost"),
        )

    @property
    def TESTING(self) -> bool:
        """Get testing mode setting."""
        return self.environment == "testing"

    def get_feature_flag(self, feature_name: str, default: bool = False) -> bool:
        """Get feature flag value."""
        features = self.app_config.get("features", {})
        env_features = features.get("environments", {}).get(self.environment, {})

        # Check environment-specific feature first, then global, then default
        if feature_name in env_features:
            return env_features[feature_name]
        elif feature_name in features:
            return features[feature_name]
        else:
            return default

    def get_api_setting(self, setting_path: str, default: Any = None) -> Any:
        """Get API-related setting using dot notation."""
        api_config = self.app_config.get("api", {})

        # Check environment-specific API settings first
        env_api_config = api_config.get("environments", {}).get(self.environment, {})

        # Split the path and traverse the config
        keys = setting_path.split(".")

        # Try environment-specific first
        value = self._get_nested_value(env_api_config, keys)
        if value is not None:
            return value

        # Try global API config
        value = self._get_nested_value(api_config, keys)
        if value is not None:
            return value

        return default

    @staticmethod
    def _get_nested_value(config: Dict[str, Any], keys: list) -> Any:
        """Get nested value from config using list of keys."""
        value = config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _resolve_config_secrets(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively resolve environment variable placeholders in configuration.

        Replaces ${VARIABLE_NAME} patterns with actual environment variable values
        using the SecretManager.

        Args:
            config: Configuration dictionary potentially containing placeholders

        Returns:
            Configuration dictionary with resolved values
        """
        import copy
        import re

        logger = logging.getLogger(__name__)

        # Deep copy to avoid modifying original config
        resolved_config = copy.deepcopy(config)

        def resolve_value(value):
            """Resolve placeholders in a single value."""
            if not isinstance(value, str):
                return value

            # Pattern to match ${VARIABLE_NAME} placeholders
            pattern = r"\$\{([^}]+)\}"
            matches = re.findall(pattern, value)

            if not matches:
                return value

            resolved_value = value
            for var_name in matches:
                # Get the secret value using SecretManager
                secret_value = self.secret_manager.get_secret(var_name.strip())

                if secret_value is not None:
                    # Replace the placeholder with the actual value
                    placeholder = f"${{{var_name}}}"
                    resolved_value = resolved_value.replace(placeholder, secret_value)
                    logger.debug(
                        f"Resolved authentication config placeholder: {placeholder}"
                    )
                else:
                    # Log warning if environment variable is not found
                    logger.warning(
                        f"Environment variable '{var_name}' not found for authentication config placeholder: ${{{var_name}}}"
                    )

            return resolved_value

        def resolve_recursive(obj):
            """Recursively resolve placeholders in nested structures."""
            if isinstance(obj, dict):
                return {key: resolve_recursive(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [resolve_recursive(item) for item in obj]
            else:
                return resolve_value(obj)

        return resolve_recursive(resolved_config)

    def reload_config(self):
        """Public method to reload all configuration files."""
        self._load_configurations()

    def validate_config(self) -> list:
        """Validate configuration and return list of issues."""
        issues = []

        # Validate required secrets in production
        if self.environment == "production":
            required_secrets = ["SECRET_KEY"]
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
            ("MAX_WORKER_THREADS", self.MAX_WORKER_THREADS),
            ("DEFAULT_POLL_INTERVAL", self.DEFAULT_POLL_INTERVAL),
            ("MAX_CONCURRENT_STREAMS", self.MAX_CONCURRENT_STREAMS),
            ("HTTP_TIMEOUT", self.HTTP_TIMEOUT),
        ]

        for setting_name, value in numeric_settings:
            if not isinstance(value, int) or value <= 0:
                issues.append(f"Invalid {setting_name}: must be a positive integer")

        return issues

    def get_auth_config(self) -> Dict[str, Any]:
        """Get authentication configuration."""
        return self.auth_config

    def get_auth_setting(self, setting_path: str, default: Any = None) -> Any:
        """
        Get authentication setting using dot notation.

        Args:
            setting_path: Dot-separated path to setting (e.g., 'security.max_login_attempts')
            default: Default value if setting not found

        Returns:
            Setting value or default
        """
        return (
            self._get_nested_value(self.auth_config, setting_path.split(".")) or default
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary (for debugging/inspection)."""
        return {
            "environment": self.environment,
            "database": {
                "type": self._get_database_type(),
                "track_modifications": self.SQLALCHEMY_TRACK_MODIFICATIONS,
                "record_queries": self.SQLALCHEMY_RECORD_QUERIES,
            },
            "application": {
                "debug": self.DEBUG,
                "testing": self.TESTING,
                "default_poll_interval": self.DEFAULT_POLL_INTERVAL,
                "max_concurrent_streams": self.MAX_CONCURRENT_STREAMS,
                "http_timeout": self.HTTP_TIMEOUT,
            },
            "threading": {
                "max_worker_threads": self.MAX_WORKER_THREADS,
            },
            "logging": {
                "level": self.LOG_LEVEL,
                "directory": self.LOG_DIR,
            },
            "authentication": {
                "providers_enabled": len(
                    [
                        p
                        for p in self.auth_config.get("providers", [])
                        if p.get("enabled", False)
                    ]
                ),
                "max_login_attempts": self.get_auth_setting(
                    "security.max_login_attempts", 5
                ),
                "session_timeout": self.get_auth_setting(
                    "security.session_timeout_hours", 24
                ),
            },
        }
