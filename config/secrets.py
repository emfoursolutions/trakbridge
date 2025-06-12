# =============================================================================
# config/secrets.py - Secure Secret Management
# =============================================================================

import os
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


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


class EnvironmentSecretProvider(SecretProvider):
    """Retrieve secrets from environment variables."""

    @property
    def name(self) -> str:
        return "Environment Variables"

    def is_available(self) -> bool:
        return True

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = os.environ.get(key, default)
        if value:
            logger.debug(f"Retrieved secret '{key}' from environment variables")
        return value


class DockerSecretProvider(SecretProvider):
    """Retrieve secrets from Docker Secrets (mounted files)."""

    SECRETS_PATH = Path("/run/secrets")

    @property
    def name(self) -> str:
        return "Docker Secrets"

    def is_available(self) -> bool:
        return self.SECRETS_PATH.exists() and self.SECRETS_PATH.is_dir()

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        # Convert environment variable format to secret file name
        # DB_PASSWORD -> db_password
        secret_file = self.SECRETS_PATH / key.lower()

        if secret_file.exists():
            try:
                value = secret_file.read_text().strip()
                logger.debug(f"Retrieved secret '{key}' from Docker Secrets")
                return value
            except Exception as e:
                logger.warning(f"Failed to read Docker secret '{key}': {e}")

        return default


class DotEnvSecretProvider(SecretProvider):
    """Retrieve secrets from .env files (development only)."""

    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file or ".env"
        self._secrets: Dict[str, str] = {}
        self._load_env_file()

    @property
    def name(self) -> str:
        return f"DotEnv File ({self.env_file})"

    def is_available(self) -> bool:
        return Path(self.env_file).exists()

    def _load_env_file(self):
        """Load environment variables from .env file."""
        env_path = Path(self.env_file)
        if not env_path.exists():
            return

        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        self._secrets[key] = value
            logger.debug(f"Loaded {len(self._secrets)} secrets from {self.env_file}")
        except Exception as e:
            logger.warning(f"Failed to load .env file '{self.env_file}': {e}")

    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = self._secrets.get(key, default)
        if value and key in self._secrets:
            logger.debug(f"Retrieved secret '{key}' from .env file")
        return value


class ExternalSecretProvider(SecretProvider):
    """
    Base class for external secret managers (Vault, AWS Secrets Manager, etc.).
    Extend this class to implement specific providers.
    """

    @property
    def name(self) -> str:
        return "External Secret Manager"

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

    def __init__(self, environment: str = "development"):
        self.environment = environment
        self.providers: list[SecretProvider] = []
        self._setup_providers()

    def _setup_providers(self):
        """Setup secret providers based on environment and availability."""

        # Always try Docker Secrets first (most secure)
        docker_provider = DockerSecretProvider()
        if docker_provider.is_available():
            self.providers.append(docker_provider)
            logger.info("Docker Secrets provider available")

        # Environment variables (standard for containers)
        self.providers.append(EnvironmentSecretProvider())
        logger.info("Environment Variables provider available")

        # .env files only in development
        if self.environment == "development":
            env_file = f".env.{self.environment}"
            dotenv_provider = DotEnvSecretProvider(env_file)
            if dotenv_provider.is_available():
                self.providers.append(dotenv_provider)
                logger.info(f"DotEnv provider available ({env_file})")

            # Fallback to standard .env
            fallback_provider = DotEnvSecretProvider(".env")
            if fallback_provider.is_available():
                self.providers.append(fallback_provider)
                logger.info("DotEnv provider available (.env)")

    def get_secret(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """
        Retrieve a secret from available providers in priority order.

        Args:
            key: Secret key to retrieve
            default: Default value if secret not found
            required: Raise exception if secret not found and no default

        Returns:
            Secret value or default

        Raises:
            ValueError: If required secret is not found
        """
        for provider in self.providers:
            try:
                value = provider.get_secret(key, None)
                if value is not None:
                    return value
            except Exception as e:
                logger.warning(f"Provider '{provider.name}' failed for key '{key}': {e}")
                continue

        if required and default is None:
            available_providers = [p.name for p in self.providers]
            raise ValueError(
                f"Required secret '{key}' not found in any provider. "
                f"Available providers: {', '.join(available_providers)}"
            )

        return default

    def get_database_secrets(self) -> Dict[str, Optional[str]]:
        """Retrieve all database-related secrets."""
        secrets = {
            'DB_PASSWORD': self.get_secret('DB_PASSWORD'),
            'DB_USER': self.get_secret('DB_USER'),
            'DB_HOST': self.get_secret('DB_HOST'),
            'DB_PORT': self.get_secret('DB_PORT'),
            'DB_NAME': self.get_secret('DB_NAME'),
        }
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
            'available_providers': 0
        }

        for provider in self.providers:
            provider_health = {
                'name': provider.name,
                'available': False,
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


def get_secret_manager(environment: str = None) -> SecretManager:
    """Get or create the global secret manager instance."""
    global _secret_manager

    if _secret_manager is None or (environment and _secret_manager.environment != environment):
        env = environment or os.environ.get('FLASK_ENV', 'development')
        _secret_manager = SecretManager(env)

    return _secret_manager


def get_secret(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Convenience function to get a secret."""
    return get_secret_manager().get_secret(key, default, required)