"""
ABOUTME: Unified configuration service providing consolidated loading path for all configuration operations
ABOUTME: Centralizes all configuration access patterns with caching, validation, and hot-reload capabilities

File: services/unified_config_service.py

Description:
    Unified configuration service that consolidates all configuration loading
    into a single path. This service provides consistent configuration access
    across all components with built-in caching, validation, and hot-reload
    support.

Key features:
    - Single consolidated path for all configuration loading operations
    - Integration with ConfigCacheService for performance optimization
    - Automatic validation using existing validation framework
    - Hot-reload capabilities with change detection
    - Plugin configuration management with caching
    - Stream configuration lifecycle management
    - Authentication configuration loading with fallback
    - Database configuration with environment variable override
    - Comprehensive error handling and logging

Author: Emfour Solutions
Created: 2025-09-27
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from services.config_cache_service import get_config_cache_service
from utils.config_manager import ConfigManager
from plugins.plugin_manager import PluginManager
from config.authentication_loader import load_authentication_config
from config.base import Config
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


class UnifiedConfigService:
    """
    Centralized configuration service implementing single loading path.

    This service consolidates all configuration access patterns from Phase 3
    of the RC6 specification, providing consistent configuration management
    across the entire application.
    """

    def __init__(self):
        self._config_cache = get_config_cache_service()
        self._config_manager = ConfigManager()
        self._plugin_manager = PluginManager()
        self._cache_enabled = True

    async def load_stream_configuration(
        self, stream_id: int, use_cache: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Unified path for loading stream configuration.

        Args:
            stream_id: ID of the stream
            use_cache: Whether to use cached configuration

        Returns:
            Stream configuration dictionary or None if not found
        """
        cache_key = f"stream_config:{stream_id}"

        if use_cache and self._cache_enabled:
            # Try cache first
            cached_config = await self._config_cache.get_configuration(cache_key)
            if cached_config:
                logger.debug(f"Loaded stream {stream_id} config from cache")
                return cached_config

        # Load from database if not cached
        try:
            from services.database_manager import DatabaseManager
            from app import create_app

            app = create_app()
            db_manager = DatabaseManager(app_context_factory=app.app_context)
            stream = db_manager.get_stream_with_relationships(stream_id)

            if not stream:
                logger.warning(f"Stream {stream_id} not found in database")
                return None

            # Create configuration dictionary
            config_data = {
                "id": stream.id,
                "name": stream.name,
                "plugin_type": stream.plugin_type,
                "plugin_config": stream.plugin_config,
                "cot_type": stream.cot_type,
                "poll_interval": stream.poll_interval,
                "is_active": stream.is_active,
                "tak_server": stream.tak_server.id if stream.tak_server else None,
                "tak_servers": (
                    [server.id for server in stream.tak_servers]
                    if stream.tak_servers
                    else []
                ),
                "last_poll": stream.last_poll.isoformat() if stream.last_poll else None,
                "last_error": stream.last_error,
                "total_messages_sent": getattr(stream, "total_messages_sent", 0),
                "loaded_at": datetime.utcnow().isoformat(),
            }

            # Cache the configuration if caching is enabled
            if self._cache_enabled:
                await self._config_cache.preload_configuration(cache_key, config_data)

            logger.debug(f"Loaded stream {stream_id} config from database")
            return config_data

        except Exception as e:
            logger.error(f"Error loading stream {stream_id} configuration: {e}")
            return None

    async def validate_plugin_configuration(
        self, plugin_name: str, config: Dict[str, Any], use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Unified path for plugin configuration validation.

        Args:
            plugin_name: Name of the plugin
            config: Configuration to validate
            use_cache: Whether to use cached validation results

        Returns:
            Validation result dictionary
        """
        if use_cache and self._cache_enabled:
            # Check for cached validation result
            cached_result = await self._config_cache.get_cached_validation(
                f"plugin_validation:{plugin_name}", config
            )
            if cached_result:
                logger.debug(f"Plugin {plugin_name} validation result from cache")
                return cached_result

        # Perform validation using plugin manager
        try:
            validation_result = self._plugin_manager.validate_plugin_config(
                plugin_name, config
            )

            # Add metadata
            validation_result["validated_at"] = datetime.utcnow().isoformat()
            validation_result["plugin_name"] = plugin_name

            # Cache the result if caching is enabled
            if self._cache_enabled and validation_result.get("valid", False):
                await self._config_cache.cache_validation_result(
                    f"plugin_validation:{plugin_name}",
                    config,
                    validation_result,
                    ttl=3600,  # Cache for 1 hour
                )

            logger.debug(f"Plugin {plugin_name} validation completed")
            return validation_result

        except Exception as e:
            logger.error(f"Error validating plugin {plugin_name} configuration: {e}")
            return {
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
                "validated_at": datetime.utcnow().isoformat(),
                "plugin_name": plugin_name,
            }

    async def load_application_configuration(
        self, config_name: str, use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Unified path for loading application configuration files.

        Args:
            config_name: Name of the configuration file (e.g., "plugins.yaml")
            use_cache: Whether to use cached configuration

        Returns:
            Configuration dictionary
        """
        cache_key = f"app_config:{config_name}"

        if use_cache and self._cache_enabled:
            # Try cache first
            cached_config = await self._config_cache.get_configuration(cache_key)
            if cached_config:
                logger.debug(f"Loaded {config_name} from cache")
                return cached_config

        # Load from file system
        try:
            config_data = self._config_manager.load_config_safe(config_name)

            # Add metadata
            config_data["_metadata"] = {
                "config_name": config_name,
                "loaded_at": datetime.utcnow().isoformat(),
                "source": "filesystem",
            }

            # Cache the configuration if caching is enabled
            if self._cache_enabled:
                await self._config_cache.preload_configuration(cache_key, config_data)

            logger.debug(f"Loaded {config_name} from filesystem")
            return config_data

        except Exception as e:
            logger.error(f"Error loading application configuration {config_name}: {e}")
            # Return empty configuration with error metadata
            return {
                "_metadata": {
                    "config_name": config_name,
                    "loaded_at": datetime.utcnow().isoformat(),
                    "source": "error",
                    "error": str(e),
                },
                "_error": True,
            }

    async def load_authentication_configuration(
        self, use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Unified path for loading authentication configuration.

        Args:
            use_cache: Whether to use cached configuration

        Returns:
            Authentication configuration dictionary
        """
        cache_key = "auth_config"

        if use_cache and self._cache_enabled:
            # Try cache first
            cached_config = await self._config_cache.get_configuration(cache_key)
            if cached_config:
                logger.debug("Loaded authentication config from cache")
                return cached_config

        # Load authentication configuration
        try:
            auth_config = load_authentication_config()

            # Add metadata
            auth_config["_metadata"] = {
                "loaded_at": datetime.utcnow().isoformat(),
                "source": "authentication_loader",
            }

            # Cache the configuration if caching is enabled
            if self._cache_enabled:
                await self._config_cache.preload_configuration(cache_key, auth_config)

            logger.debug("Loaded authentication config from loader")
            return auth_config

        except Exception as e:
            logger.error(f"Error loading authentication configuration: {e}")
            # Return minimal fallback configuration
            return {
                "authentication": {
                    "provider_priority": ["local"],
                    "providers": {"local": {"enabled": True}},
                },
                "_metadata": {
                    "loaded_at": datetime.utcnow().isoformat(),
                    "source": "fallback",
                    "error": str(e),
                },
                "_error": True,
            }

    async def reload_configuration(
        self, config_type: str, identifier: Union[str, int] = None
    ) -> bool:
        """
        Unified path for reloading any configuration with hot-reload support.

        Args:
            config_type: Type of configuration ('stream', 'plugin', 'app', 'auth')
            identifier: Stream ID, config name, or other identifier

        Returns:
            True if reload was successful, False otherwise
        """
        try:
            if config_type == "stream" and identifier:
                # Reload stream configuration
                cache_key = f"stream_config:{identifier}"

                # Invalidate cache
                await self._config_cache.update_configuration(cache_key, {})

                # Reload fresh configuration
                new_config = await self.load_stream_configuration(
                    int(identifier), use_cache=False
                )

                if new_config:
                    logger.info(
                        f"Successfully reloaded stream {identifier} configuration"
                    )
                    return True

            elif config_type == "app" and identifier:
                # Reload application configuration
                cache_key = f"app_config:{identifier}"

                # Invalidate cache
                await self._config_cache.update_configuration(cache_key, {})

                # Reload fresh configuration
                new_config = await self.load_application_configuration(
                    identifier, use_cache=False
                )

                if not new_config.get("_error", False):
                    logger.info(f"Successfully reloaded app configuration {identifier}")
                    return True

            elif config_type == "auth":
                # Reload authentication configuration
                cache_key = "auth_config"

                # Invalidate cache
                await self._config_cache.update_configuration(cache_key, {})

                # Reload fresh configuration
                new_config = await self.load_authentication_configuration(
                    use_cache=False
                )

                if not new_config.get("_error", False):
                    logger.info("Successfully reloaded authentication configuration")
                    return True

            logger.warning(
                f"Unsupported config reload: type={config_type}, identifier={identifier}"
            )
            return False

        except Exception as e:
            logger.error(
                f"Error reloading configuration {config_type}:{identifier}: {e}"
            )
            return False

    async def get_configuration_status(self) -> Dict[str, Any]:
        """
        Get comprehensive status of all cached configurations.

        Returns:
            Dictionary with configuration status and cache statistics
        """
        try:
            cache_stats = await self._config_cache.get_cache_stats()

            return {
                "cache_enabled": self._cache_enabled,
                "cache_stats": cache_stats,
                "service_status": "active",
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error getting configuration status: {e}")
            return {
                "cache_enabled": self._cache_enabled,
                "service_status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def enable_caching(self):
        """Enable configuration caching"""
        self._cache_enabled = True
        logger.info("Configuration caching enabled")

    def disable_caching(self):
        """Disable configuration caching"""
        self._cache_enabled = False
        logger.info("Configuration caching disabled")

    async def clear_all_caches(self):
        """Clear all configuration caches"""
        await self._config_cache.clear_all_caches()
        logger.info("All configuration caches cleared")


# Global instance
_unified_config_service: Optional[UnifiedConfigService] = None


def get_unified_config_service() -> UnifiedConfigService:
    """Get the singleton unified configuration service"""
    global _unified_config_service
    if _unified_config_service is None:
        _unified_config_service = UnifiedConfigService()
    return _unified_config_service


def reset_unified_config_service():
    """Reset the global unified configuration service (for testing)"""
    global _unified_config_service
    _unified_config_service = None
