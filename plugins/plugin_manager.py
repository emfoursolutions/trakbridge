"""
File: plugins/plugin_manager.py

Description:
    Manages discovery, loading, registration, and lifecycle of GPS tracking plugins.
    Supports plugin configuration, validation, metadata extraction, connection testing,
    runtime health checks, and dynamic reloading. Integrates with the stream model for
    system-wide plugin orchestration.

Author: {{AUTHOR}}
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import importlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import pkgutil
from typing import (
    Dict,
    Type,
    Optional,
    List,
    Any,
    Union,
    TYPE_CHECKING,
)

# Third-party imports
# (none for this file)

# Local application imports
if TYPE_CHECKING:
    from plugins.base_plugin import BaseGPSPlugin

# Module-level logger
logger = logging.getLogger(__name__)


class PluginManager:
    """Enhanced manager for GPS tracking plugins with metadata support"""

    def __init__(self):
        self.plugins: Dict[str, Type["BaseGPSPlugin"]] = {}

    def register_plugin(self, plugin_class: Type["BaseGPSPlugin"]):
        """Register a plugin class"""

        plugin_name = None

        # Try to get plugin name from class method first
        if hasattr(plugin_class, "get_plugin_name"):
            try:
                plugin_name = plugin_class.get_plugin_name()
            except (AttributeError, TypeError) as e:
                logger.warning(f"Failed to get plugin name from class method: {e}")

        # Fall back to creating a temporary instance
        if not plugin_name:
            try:
                temp_instance = plugin_class({})
                plugin_name = temp_instance.plugin_name
            except (TypeError, ValueError) as e:
                logger.error(
                    f"Failed to create temporary instance for {plugin_class.__name__}: {e}"
                )
                return
            except Exception as e:
                logger.error(
                    f"Failed to get plugin name for {plugin_class.__name__}: {e}"
                )
                return

        self.plugins[plugin_name] = plugin_class
        logger.info(f"Registered plugin: {plugin_name}")

    @staticmethod
    def _validate_and_normalize_config(config: Union[Dict, str, None]) -> Dict:
        """
        Validate and normalize configuration input

        Args:
            config: Configuration input (can be dict, string, or None)

        Returns:
            Normalized dictionary configuration
        """
        if config is None:
            return {}

        if isinstance(config, str):
            # Handle string configuration - could be JSON, config name, or empty
            if not config or config.strip() == "":
                return {}

            # Try to parse as JSON
            try:
                return json.loads(config)
            except (json.JSONDecodeError, ValueError):
                # If not JSON, treat as a configuration name or identifier
                logger.warning(
                    f"String config '{config}' could not be parsed as JSON, using empty config"
                )
                return {}

        if isinstance(config, dict):
            return config.copy()

        # For any other type, log warning and return empty dict
        logger.warning(f"Unexpected config type {type(config)}, using empty config")
        return {}

    def get_plugin(
        self, plugin_name: str, config: Union[Dict, str, None] = None
    ) -> Optional["BaseGPSPlugin"]:
        """
        Create an instance of a plugin with the given configuration

        Args:
            plugin_name: Name of the plugin to instantiate
            config: Configuration (can be dict, string, or None)

        Returns:
            Plugin instance or None if creation fails
        """
        if plugin_name not in self.plugins:
            logger.error(f"Plugin not found: {plugin_name}")
            return None

        # Normalize configuration input
        normalized_config = self._validate_and_normalize_config(config)

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(normalized_config)
            if not plugin_instance.validate_config():
                logger.error(f"Plugin {plugin_name} configuration validation failed")
                return None
            return plugin_instance
        except Exception as e:
            logger.error(f"Failed to create plugin instance for '{plugin_name}': {e}")
            logger.debug(f"Config type: {type(config)}, Config value: {config}")
            return None

    def list_plugins(self) -> List[str]:
        """List all registered plugin names"""
        return list(self.plugins.keys())

    def get_plugin_metadata(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific plugin"""
        if plugin_name not in self.plugins:
            return None

        plugin_class = self.plugins[plugin_name]
        try:
            # Create temporary instance to get metadata
            temp_instance = plugin_class({})
            return temp_instance.plugin_metadata
        except Exception as e:
            logger.error(f"Failed to get metadata for plugin {plugin_name}: {e}")
            return None

    def get_all_plugin_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Get metadata for all registered plugins"""
        metadata = {}
        for plugin_name in self.plugins:
            plugin_metadata = self.get_plugin_metadata(plugin_name)
            if plugin_metadata:
                metadata[plugin_name] = plugin_metadata
        return metadata

    def get_plugin_config_schema(
        self, plugin_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get configuration schema for a specific plugin"""
        if plugin_name not in self.plugins:
            return None

        plugin_class = self.plugins[plugin_name]
        try:
            temp_instance = plugin_class({})
            config_fields = temp_instance.get_config_fields()
            return [field.to_dict() for field in config_fields]
        except Exception as e:
            logger.error(f"Failed to get config schema for plugin {plugin_name}: {e}")
            return None

    def validate_plugin_config(
        self, plugin_name: str, config: Union[Dict[str, Any], str, None]
    ) -> Dict[str, Any]:
        """
        Validate configuration for a specific plugin

        Args:
            plugin_name: Name of the plugin
            config: Configuration to validate (dict, string, or None)

        Returns:
            Dictionary with validation results:
            - valid: bool
            - errors: List[str]
            - warnings: List[str]
        """
        if plugin_name not in self.plugins:
            return {
                "valid": False,
                "errors": [f"Plugin '{plugin_name}' not found"],
                "warnings": [],
            }

        # Normalize configuration
        normalized_config = self._validate_and_normalize_config(config)

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(normalized_config)
            is_valid = plugin_instance.validate_config()

            warnings = []
            if isinstance(config, str) and config.strip():
                warnings.append("String configuration was converted to dictionary")

            return {
                "valid": is_valid,
                "errors": [] if is_valid else ["Configuration validation failed"],
                "warnings": warnings,
            }
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": [],
            }

    async def test_plugin_connection(
        self, plugin_name: str, config: Union[Dict[str, Any], str, None]
    ) -> Dict[str, Any]:
        """
        Test connection for a specific plugin configuration

        Args:
            plugin_name: Name of the plugin
            config: Configuration to test (dict, string, or None)

        Returns:
            Dictionary with connection test results from plugin's test_connection method
        """
        if plugin_name not in self.plugins:
            return {
                "success": False,
                "error": f"Plugin '{plugin_name}' not found",
                "message": "Plugin not found",
            }

        # Normalize configuration
        normalized_config = self._validate_and_normalize_config(config)

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(normalized_config)

            # Validate config first
            if not plugin_instance.validate_config():
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "message": "Invalid configuration",
                }

            # Test connection
            return await plugin_instance.test_connection()

        except Exception as e:
            logger.error(f"Connection test failed for plugin {plugin_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test error",
            }

    def get_plugins_by_category(self, category: str) -> List[str]:
        """Get plugins filtered by category"""
        matching_plugins = []
        for plugin_name in self.plugins:
            metadata = self.get_plugin_metadata(plugin_name)
            if metadata and metadata.get("category") == category:
                matching_plugins.append(plugin_name)
        return matching_plugins

    def get_plugin_categories(self) -> List[str]:
        """Get all available plugin categories"""
        categories = set()
        for plugin_name in self.plugins:
            metadata = self.get_plugin_metadata(plugin_name)
            if metadata and metadata.get("category"):
                categories.add(metadata["category"])
        return sorted(list(categories))

    def load_plugins_from_directory(self, directory: str = "plugins"):
        """
        Automatically load plugins from a directory
        """

        from plugins.base_plugin import BaseGPSPlugin

        try:
            # Get absolute path of the plugins directory
            plugins_path = os.path.abspath(directory)

            if not os.path.exists(plugins_path):
                logger.warning(f"Plugins directory not found: {plugins_path}")
                return

            # Add plugins directory to Python path if not already there
            if plugins_path not in sys.path:
                sys.path.insert(0, plugins_path)

            # Import the plugins package
            plugins_package = importlib.import_module(directory)

            # Iterate through all modules in the plugins package
            for importer, modname, ispkg in pkgutil.iter_modules(
                plugins_package.__path__, plugins_package.__name__ + "."
            ):
                # Skip the base_plugin module
                if modname.endswith(".base_plugin"):
                    continue

                try:
                    # Import the module
                    module = importlib.import_module(modname)

                    # Look for classes that inherit from BaseGPSPlugin
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        # Check if it's a subclass of BaseGPSPlugin but not BaseGPSPlugin itself
                        if issubclass(obj, BaseGPSPlugin) and obj is not BaseGPSPlugin:
                            self.register_plugin(obj)

                except Exception as e:
                    logger.error(f"Failed to load plugin module {modname}: {e}")

        except Exception as e:
            logger.error(f"Failed to load plugins from directory {directory}: {e}")

    def auto_discover_and_load_plugins(self, directory: str = "plugins"):
        """
        Alternative method that discovers Python files and loads them
        """

        from plugins.base_plugin import BaseGPSPlugin

        try:
            plugins_path = os.path.abspath(directory)

            if not os.path.exists(plugins_path):
                logger.warning(f"Plugins directory not found: {plugins_path}")
                return

            # Get all Python files in the directory
            for filename in os.listdir(plugins_path):
                if (
                    filename.endswith(".py")
                    and not filename.startswith("__")
                    and filename != "base_plugin.py"
                ):
                    module_name = filename[:-3]  # Remove .py extension

                    try:
                        # Import the module
                        spec = importlib.util.spec_from_file_location(
                            module_name, os.path.join(plugins_path, filename)
                        )
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # Look for plugin classes
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if (
                                issubclass(obj, BaseGPSPlugin)
                                and obj is not BaseGPSPlugin
                            ):
                                self.register_plugin(obj)

                    except Exception as e:
                        logger.error(f"Failed to load plugin file {filename}: {e}")

        except Exception as e:
            logger.error(f"Failed to discover plugins in directory {directory}: {e}")

    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a specific plugin (useful for development)"""
        from plugins.base_plugin import BaseGPSPlugin

        if plugin_name not in self.plugins:
            logger.error(f"Cannot reload plugin '{plugin_name}': not found")
            return False

        try:
            plugin_class = self.plugins[plugin_name]
            module = inspect.getmodule(plugin_class)

            if module:
                importlib.reload(module)
                # Re-register the plugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseGPSPlugin) and obj is not BaseGPSPlugin:
                        # Check if this is the plugin we want to reload
                        try:
                            temp_instance = obj({})
                            if temp_instance.plugin_name == plugin_name:
                                self.plugins[plugin_name] = obj
                                logger.info(
                                    f"Successfully reloaded plugin: {plugin_name}"
                                )
                                return True
                        except Exception:
                            continue

        except Exception as e:
            logger.error(f"Failed to reload plugin {plugin_name}: {e}")
            return False

        return False

    def get_plugin_summary(self) -> Dict[str, Any]:
        """Get a summary of all loaded plugins"""
        summary = {
            "total_plugins": len(self.plugins),
            "plugins": {},
            "categories": self.get_plugin_categories(),
        }

        for plugin_name in self.plugins:
            metadata = self.get_plugin_metadata(plugin_name)
            if metadata:
                summary["plugins"][plugin_name] = {
                    "display_name": metadata.get("display_name", plugin_name),
                    "description": metadata.get("description", "No description"),
                    "category": metadata.get("category", "uncategorized"),
                    "config_fields_count": len(metadata.get("config_fields", [])),
                }

        return summary

    def safe_get_plugin(
        self,
        plugin_name: str,
        config: Union[Dict, str, None] = None,
        default_config: Optional[Dict] = None,
    ) -> Optional["BaseGPSPlugin"]:
        """
        Safely get a plugin with fallback configuration

        Args:
            plugin_name: Name of the plugin
            config: Primary configuration
            default_config: Fallback configuration if primary fails

        Returns:
            Plugin instance or None
        """
        # Try with primary config
        plugin = self.get_plugin(plugin_name, config)
        if plugin is not None:
            return plugin

        # Try with default config if provided
        if default_config is not None:
            logger.info(f"Falling back to default config for plugin {plugin_name}")
            return self.get_plugin(plugin_name, default_config)

        return None

    async def check_all_plugins_health(self):
        health_status = {}

        # Get existing stream configurations from the database
        from models.stream import Stream
        from database import db

        # Get all streams grouped by plugin type
        streams_by_plugin = {}
        try:
            streams = db.session.query(Stream).all()
            for stream in streams:
                plugin_type = stream.plugin_type
                if plugin_type not in streams_by_plugin:
                    streams_by_plugin[plugin_type] = []
                streams_by_plugin[plugin_type].append(stream)
        except Exception as e:
            logger.error(f"Could not fetch streams for health check: {e}")
            streams_by_plugin = {}

        for name, plugin_class in self.plugins.items():
            try:
                if name in streams_by_plugin and streams_by_plugin[name]:
                    # Test with actual stream configuration
                    stream = streams_by_plugin[name][0]  # Use first stream's config
                    config = (
                        stream.get_plugin_config()
                    )  # Use the method, not the attribute
                    plugin_instance = plugin_class(config)
                    health = await plugin_instance.health_check()

                    # Add stream count info to health details
                    stream_count = len(streams_by_plugin[name])
                    if isinstance(health, dict) and "details" in health:
                        if isinstance(health["details"], dict):
                            health["details"]["configured_streams"] = stream_count
                        else:
                            health["details"] = (
                                f"{health['details']} ({stream_count} stream(s) configured)"
                            )
                    else:
                        health["details"] = (
                            f"{health.get('details', 'Health check completed')} "
                            f"({stream_count} stream(s) configured)"
                        )

                else:
                    # No configured streams for this plugin
                    plugin_instance = plugin_class({})
                    health = {
                        "status": "unconfigured",
                        "details": "No streams configured for this plugin",
                    }

            except Exception as e:
                logger.error(
                    f"[PluginManager] Health check failed for plugin '{name}': {e}",
                    exc_info=True,
                )
                health = {"status": "unhealthy", "details": str(e)}
            health_status[name] = health
        return health_status


# Global plugin manager instance
plugin_manager = PluginManager()

# Auto-load plugins on import
plugin_manager.load_plugins_from_directory()


def get_plugin_manager():
    """Get the plugin manager instance - check Flask app context first, then fall back to global"""
    try:
        from flask import current_app, has_app_context

        if has_app_context() and hasattr(current_app, "plugin_manager"):
            return current_app.plugin_manager
    except (ImportError, RuntimeError):
        # Flask not available or no app context
        pass

    # Fallback to global instance for CLI/standalone use
    return plugin_manager
