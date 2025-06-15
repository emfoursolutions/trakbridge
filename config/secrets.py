# =============================================================================
# config/secrets.py - Secure Secret Management (Enhanced)
# =============================================================================

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from pathlib import Path
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SecretMetadata:
    """Metadata about a retrieved secret."""
    provider: str
    retrieved_at: float
    ttl: Optional[int] = None  # Time to live in seconds

    def is_expired(self) -> bool:
        """Check if the secret has expired."""
        if self.ttl is None:
            return False
        return time.time() - self.retrieved_at > self.ttl


class SecretProvider(ABC):
    """Abstract base class for secret providers."""

    @abstractmethod
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve a secret by key."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this secret provider is available."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the secret provider."""
        pass

    @property
    def priority(self) -> int:
        """Priority of this provider (lower number = higher priority)."""
        return 100  # Default priority

    def supports_refresh(self) -> bool:
        """Whether this provider supports refreshing secrets."""
        return False


class EnvironmentSecretProvider(SecretProvider):
    """Retrieve secrets from environment variables."""

    @property
    def name(self) -> str:
        return "Environment Variables"

    @property
    def priority(self) -> int:
        return 20  # Medium priority

    def is_available(self) -> bool:
        return True

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.environ.get(key, default)
        if value and value != default:
            logger.debug(f"Retrieved secret '{key}' from environment variables")
        return value


class DockerSecretProvider(SecretProvider):
    """Retrieve secrets from Docker Secrets (mounted files)."""

    SECRETS_PATH = Path("/run/secrets")

    print(f"Secrets path: {SECRETS_PATH}")
    print(f"Path exists: {SECRETS_PATH.exists()}")
    @property
    def name(self) -> str:
        return "Docker Secrets"

    @property
    def priority(self) -> int:
        return 10  # Highest priority

    def is_available(self) -> bool:
        return self.SECRETS_PATH.exists() and self.SECRETS_PATH.is_dir()

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Convert environment variable format to secret file name
        # DB_PASSWORD -> db_password
        secret_file = self.SECRETS_PATH / key.lower()

        if secret_file.exists():
            try:
                value = secret_file.read_text().strip()
                if value:
                    logger.debug(f"Retrieved secret '{key}' from Docker Secrets")
                    return value
            except Exception as e:
                logger.warning(f"Failed to read Docker secret '{key}': {e}")

        return default

    def supports_refresh(self) -> bool:
        return True


class DotEnvSecretProvider(SecretProvider):
    """Retrieve secrets from .env files (development only)."""

    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file or ".env"
        self._secrets: Dict[str, str] = {}
        self._last_modified: Optional[float] = None
        self._load_env_file()

    @property
    def name(self) -> str:
        return f"DotEnv File ({self.env_file})"

    @property
    def priority(self) -> int:
        return 30  # Lowest priority

    def is_available(self) -> bool:
        return Path(self.env_file).exists()

    def _should_reload(self) -> bool:
        """Check if the .env file has been modified."""
        env_path = Path(self.env_file)
        if not env_path.exists():
            return False

        try:
            current_modified = env_path.stat().st_mtime
            if self._last_modified is None or current_modified > self._last_modified:
                self._last_modified = current_modified
                return True
        except OSError:
            pass

        return False

    def _load_env_file(self):
        """Load environment variables from .env file."""
        env_path = Path(self.env_file)
        if not env_path.exists():
            return

        try:
            self._secrets.clear()
            with open(env_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        try:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key:  # Ignore empty keys
                                self._secrets[key] = value
                        except ValueError:
                            logger.warning(f"Invalid line {line_num} in {self.env_file}: {line}")

            logger.debug(f"Loaded {len(self._secrets)} secrets from {self.env_file}")
        except Exception as e:
            logger.warning(f"Failed to load .env file '{self.env_file}': {e}")

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Reload if file has been modified
        if self._should_reload():
            self._load_env_file()

        value = self._secrets.get(key, default)
        if value and key in self._secrets and value != default:
            logger.debug(f"Retrieved secret '{key}' from .env file")
        return value

    def supports_refresh(self) -> bool:
        return True


class ExternalSecretProvider(SecretProvider):
    """
    Base class for external secret managers (Vault, AWS Secrets Manager, etc.).
    Extend this class to implement specific providers.
    """

    @property
    def name(self) -> str:
        return "External Secret Manager"

    @property
    def priority(self) -> int:
        return 5  # Very high priority

    def is_available(self) -> bool:
        # Override in subclasses to check connectivity/authentication
        return False

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Override in subclasses to implement actual secret retrieval
        logger.warning(f"External secret provider not implemented for key '{key}'")
        return default


class SecretManager:
    """
    Manages multiple secret providers with priority-based fallback.
    """

    def __init__(self, environment: str = "development", enable_caching: bool = True):
        self.environment = environment
        self.enable_caching = enable_caching
        self.providers: List[SecretProvider] = []
        self._cache: Dict[str, tuple[str, SecretMetadata]] = {}
        self._setup_providers()

    def _setup_providers(self):
        """Setup secret providers based on environment and availability."""
        potential_providers = []

        # Always add Docker Secrets provider
        docker_provider = DockerSecretProvider()
        potential_providers.append(docker_provider)

        # Always add Environment variables
        potential_providers.append(EnvironmentSecretProvider())

        # .env files only in development/testing
        if self.environment in ["development", "testing"]:
            env_file = f".env.{self.environment}"
            dotenv_provider = DotEnvSecretProvider(env_file)
            potential_providers.append(dotenv_provider)

            # Fallback to standard .env
            fallback_provider = DotEnvSecretProvider(".env")
            potential_providers.append(fallback_provider)

        # Filter to only available providers and sort by priority
        self.providers = [p for p in potential_providers if p.is_available()]
        self.providers.sort(key=lambda x: x.priority)

        for provider in self.providers:
            logger.info(f"Secret provider available: {provider.name} (priority: {provider.priority})")

    def get_secret(self, key: str, default: Optional[str] = None, required: bool = False,
                   ttl: Optional[int] = None) -> Optional[str]:
        """
        Retrieve a secret from available providers in priority order.

        Args:
            key: Secret key to retrieve
            default: Default value if secret not found
            required: Raise exception if secret not found and no default
            ttl: Time to live for cached secrets in seconds

        Returns:
            Secret value or default

        Raises:
            ValueError: If required secret is not found
        """
        # First: Check cache
        if self.enable_caching and key in self._cache:
            cached_value, metadata = self._cache[key]
            if not metadata.is_expired():
                logger.debug(f"Retrieved secret '{key}' from cache (provider: {metadata.provider})")
                return cached_value
            else:
                # Remove expired entry
                del self._cache[key]
                logger.debug(f"Cache entry for '{key}' expired, refreshing")

        # Second: Try each provider in priority order
        for provider in self.providers:
            try:
                value = provider.get_secret(key, None)
                if value is not None:
                    # Cache the result if caching is enabled
                    if self.enable_caching:
                        metadata = SecretMetadata(
                            provider=provider.name,
                            retrieved_at=time.time(),
                            ttl=ttl
                        )
                        self._cache[key] = (value, metadata)

                    return value
            except Exception as e:
                logger.warning(f"Provider '{provider.name}' failed for key '{key}': {e}")
                continue

        # Third: check _FILE secret convention (Docker/Kubernetes)
        file_env_key = f"{key}_FILE"
        file_path = os.getenv(file_env_key)
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "r") as f:
                    value = f.read().strip()
                    if self.enable_caching:
                        metadata = SecretMetadata(
                            provider="FileEnv",
                            retrieved_at=time.time(),
                            ttl=ttl
                        )
                        self._cache[key] = (value, metadata)
                    logger.debug(f"Loaded secret '{key}' from file '{file_path}'")
                    return value
            except Exception as e:
                logger.warning(f"Failed to read secret file '{file_path}' for key '{key}': {e}")
        if required and default is None:
            available_providers = [p.name for p in self.providers]
            raise ValueError(
                f"Required secret '{key}' not found in any provider. "
                f"Available providers: {', '.join(available_providers)}"
            )

        return default

    def refresh_secret(self, key: str) -> bool:
        """
        Force refresh a secret from its source.

        Args:
            key: Secret key to refresh

        Returns:
            True if secret was refreshed, False otherwise
        """
        # Remove from cache
        if key in self._cache:
            del self._cache[key]

        # Try to refresh from providers that support it
        for provider in self.providers:
            if provider.supports_refresh():
                try:
                    value = provider.get_secret(key, None)
                    if value is not None:
                        logger.info(f"Refreshed secret '{key}' from {provider.name}")
                        return True
                except Exception as e:
                    logger.warning(f"Failed to refresh secret '{key}' from {provider.name}: {e}")

        return False

    def clear_cache(self):
        """Clear the secret cache."""
        self._cache.clear()
        logger.info("Secret cache cleared")

    def get_database_secrets(self) -> Dict[str, Optional[str]]:
        """Retrieve all database-related secrets."""
        secrets = {}
        db_keys = ['DB_PASSWORD', 'DB_USER', 'DB_HOST', 'DB_PORT', 'DB_NAME']

        for key in db_keys:
            secrets[key] = self.get_secret(key)

        return secrets

    def get_app_secrets(self) -> Dict[str, Optional[str]]:
        """Retrieve all application-related secrets."""
        secrets = {
            'SECRET_KEY': self.get_secret('SECRET_KEY', required=True),
            'JWT_SECRET_KEY': self.get_secret('JWT_SECRET_KEY'),
            'ENCRYPTION_KEY': self.get_secret('ENCRYPTION_KEY'),
        }
        return secrets

    def health_check(self) -> Dict[str, Any]:
        """Check the health of all secret providers."""
        health = {
            'providers': [],
            'total_providers': len(self.providers),
            'available_providers': 0,
            'cache_enabled': self.enable_caching,
            'cached_secrets': len(self._cache) if self.enable_caching else 0
        }

        for provider in self.providers:
            provider_health = {
                'name': provider.name,
                'priority': provider.priority,
                'available': False,
                'supports_refresh': provider.supports_refresh(),
                'error': None
            }

            try:
                provider_health['available'] = provider.is_available()
                if provider_health['available']:
                    health['available_providers'] += 1
            except Exception as e:
                provider_health['error'] = str(e)

            health['providers'].append(provider_health)

        return health


# Global secret manager instance
_secret_manager: Optional[SecretManager] = None


def get_secret_manager(environment: str = None, enable_caching: bool = True) -> SecretManager:
    """Get or create the global secret manager instance."""
    global _secret_manager

    if _secret_manager is None or (environment and _secret_manager.environment != environment):
        env = environment or os.environ.get('FLASK_ENV', 'development')
        _secret_manager = SecretManager(env, enable_caching)

    return _secret_manager


def get_secret(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Convenience function to get a secret."""
    return get_secret_manager().get_secret(key, default, required)