# =============================================================================
# plugins/plugin_manager.py - Enhanced Plugin Management with API Support
# =============================================================================

from typing import Dict, Type, Optional, List, Any
from plugins.base_plugin import BaseGPSPlugin
import importlib
import logging
import os
import inspect
import pkgutil
import asyncio
import aiohttp


class PluginManager:
    """Enhanced manager for GPS tracking plugins with metadata support"""

    def __init__(self):
        self.plugins: Dict[str, Type[BaseGPSPlugin]] = {}
        self.logger = logging.getLogger('PluginManager')

    def register_plugin(self, plugin_class: Type[BaseGPSPlugin]):
        """Register a plugin class"""
        plugin_name = None

        # Try to get plugin name from class method first
        if hasattr(plugin_class, 'get_plugin_name'):
            try:
                plugin_name = plugin_class.get_plugin_name()
            except Exception as e:
                self.logger.warning(f"Failed to get plugin name from class method: {e}")

        # Fall back to creating a temporary instance
        if not plugin_name:
            try:
                temp_instance = plugin_class({})
                plugin_name = temp_instance.plugin_name
            except Exception as e:
                self.logger.error(f"Failed to get plugin name for {plugin_class.__name__}: {e}")
                return

        self.plugins[plugin_name] = plugin_class
        self.logger.info(f"Registered plugin: {plugin_name}")

    def get_plugin(self, plugin_name: str, config: Dict) -> Optional[BaseGPSPlugin]:
        """Create an instance of a plugin with the given configuration"""
        if plugin_name not in self.plugins:
            self.logger.error(f"Plugin not found: {plugin_name}")
            return None

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(config)
            if not plugin_instance.validate_config():
                return None
            return plugin_instance
        except Exception as e:
            self.logger.error(f"Failed to create plugin instance: {e}")
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
            self.logger.error(f"Failed to get metadata for plugin {plugin_name}: {e}")
            return None

    def get_all_plugin_metadata(self) -> Dict[str, Dict[str, Any]]:
        """Get metadata for all registered plugins"""
        metadata = {}
        for plugin_name in self.plugins:
            plugin_metadata = self.get_plugin_metadata(plugin_name)
            if plugin_metadata:
                metadata[plugin_name] = plugin_metadata
        return metadata

    def get_plugin_config_schema(self, plugin_name: str) -> Optional[List[Dict[str, Any]]]:
        """Get configuration schema for a specific plugin"""
        if plugin_name not in self.plugins:
            return None

        plugin_class = self.plugins[plugin_name]
        try:
            temp_instance = plugin_class({})
            config_fields = temp_instance.get_config_fields()
            return [field.to_dict() for field in config_fields]
        except Exception as e:
            self.logger.error(f"Failed to get config schema for plugin {plugin_name}: {e}")
            return None

    def validate_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate configuration for a specific plugin

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
                "warnings": []
            }

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(config)
            is_valid = plugin_instance.validate_config()

            return {
                "valid": is_valid,
                "errors": [] if is_valid else ["Configuration validation failed"],
                "warnings": []
            }
        except Exception as e:
            return {
                "valid": False,
                "errors": [f"Validation error: {str(e)}"],
                "warnings": []
            }

    async def test_plugin_connection(self, plugin_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Test connection for a specific plugin configuration

        Returns:
            Dictionary with connection test results from plugin's test_connection method
        """
        if plugin_name not in self.plugins:
            return {
                "success": False,
                "error": f"Plugin '{plugin_name}' not found",
                "message": "Plugin not found"
            }

        plugin_class = self.plugins[plugin_name]
        try:
            plugin_instance = plugin_class(config)

            # Validate config first
            if not plugin_instance.validate_config():
                return {
                    "success": False,
                    "error": "Configuration validation failed",
                    "message": "Invalid configuration"
                }

            # Test connection
            return await plugin_instance.test_connection()

        except Exception as e:
            self.logger.error(f"Connection test failed for plugin {plugin_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test error"
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

    def load_plugins_from_directory(self, directory: str = 'plugins'):
        """
        Automatically load plugins from a directory
        """
        try:
            # Get absolute path of the plugins directory
            plugins_path = os.path.abspath(directory)

            if not os.path.exists(plugins_path):
                self.logger.warning(f"Plugins directory not found: {plugins_path}")
                return

            # Add plugins directory to Python path if not already there
            if plugins_path not in os.sys.path:
                os.sys.path.insert(0, plugins_path)

            # Import the plugins package
            plugins_package = importlib.import_module(directory)

            # Iterate through all modules in the plugins package
            for importer, modname, ispkg in pkgutil.iter_modules(plugins_package.__path__,
                                                                 plugins_package.__name__ + "."):
                # Skip the base_plugin module
                if modname.endswith('.base_plugin'):
                    continue

                try:
                    # Import the module
                    module = importlib.import_module(modname)

                    # Look for classes that inherit from BaseGPSPlugin
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        # Check if it's a subclass of BaseGPSPlugin but not BaseGPSPlugin itself
                        if (issubclass(obj, BaseGPSPlugin) and
                                obj is not BaseGPSPlugin):
                            self.register_plugin(obj)

                except Exception as e:
                    self.logger.error(f"Failed to load plugin module {modname}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to load plugins from directory {directory}: {e}")

    def auto_discover_and_load_plugins(self, directory: str = 'plugins'):
        """
        Alternative method that discovers Python files and loads them
        """
        try:
            plugins_path = os.path.abspath(directory)

            if not os.path.exists(plugins_path):
                self.logger.warning(f"Plugins directory not found: {plugins_path}")
                return

            # Get all Python files in the directory
            for filename in os.listdir(plugins_path):
                if filename.endswith('.py') and not filename.startswith('__') and filename != 'base_plugin.py':
                    module_name = filename[:-3]  # Remove .py extension

                    try:
                        # Import the module
                        spec = importlib.util.spec_from_file_location(
                            module_name,
                            os.path.join(plugins_path, filename)
                        )
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # Look for plugin classes
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if (issubclass(obj, BaseGPSPlugin) and
                                    obj is not BaseGPSPlugin):
                                self.register_plugin(obj)

                    except Exception as e:
                        self.logger.error(f"Failed to load plugin file {filename}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to discover plugins in directory {directory}: {e}")

    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a specific plugin (useful for development)"""
        if plugin_name not in self.plugins:
            self.logger.error(f"Cannot reload plugin '{plugin_name}': not found")
            return False

        try:
            plugin_class = self.plugins[plugin_name]
            module = inspect.getmodule(plugin_class)

            if module:
                importlib.reload(module)
                # Re-register the plugin
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BaseGPSPlugin) and
                            obj is not BaseGPSPlugin):
                        # Check if this is the plugin we want to reload
                        try:
                            temp_instance = obj({})
                            if temp_instance.plugin_name == plugin_name:
                                self.plugins[plugin_name] = obj
                                self.logger.info(f"Successfully reloaded plugin: {plugin_name}")
                                return True
                        except Exception:
                            continue

        except Exception as e:
            self.logger.error(f"Failed to reload plugin {plugin_name}: {e}")
            return False

        return False

    def get_plugin_summary(self) -> Dict[str, Any]:
        """Get a summary of all loaded plugins"""
        summary = {
            "total_plugins": len(self.plugins),
            "plugins": {},
            "categories": self.get_plugin_categories()
        }

        for plugin_name in self.plugins:
            metadata = self.get_plugin_metadata(plugin_name)
            if metadata:
                summary["plugins"][plugin_name] = {
                    "display_name": metadata.get("display_name", plugin_name),
                    "description": metadata.get("description", "No description"),
                    "category": metadata.get("category", "uncategorized"),
                    "config_fields_count": len(metadata.get("config_fields", []))
                }

        return summary


# Global plugin manager instance
plugin_manager = PluginManager()

# Auto-load plugins on import
plugin_manager.load_plugins_from_directory()