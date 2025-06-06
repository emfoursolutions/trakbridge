# =============================================================================
# plugins/plugin_manager.py - Plugin Management
# =============================================================================

from typing import Dict, Type, Optional, List
from plugins.base_plugin import BaseGPSPlugin
import importlib
import logging
import os
import inspect
import pkgutil


class PluginManager:
    """Manages GPS tracking plugins"""

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
        """List all registered plugins"""
        return list(self.plugins.keys())

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
                            # Try class method first, then instance method
                            if hasattr(obj, 'get_plugin_name'):
                                try:
                                    plugin_name = obj.get_plugin_name()
                                    self.register_plugin(obj)
                                    continue
                                except Exception:
                                    pass

                            # Fall back to instance method
                            try:
                                temp_instance = obj({})
                                if hasattr(temp_instance, 'plugin_name'):
                                    self.register_plugin(obj)
                            except Exception as e:
                                self.logger.warning(f"Skipping invalid plugin class {name}: {e}")

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
                                # Try class method first, then instance method
                                if hasattr(obj, 'get_plugin_name'):
                                    try:
                                        plugin_name = obj.get_plugin_name()
                                        self.register_plugin(obj)
                                        continue
                                    except Exception:
                                        pass

                                # Fall back to instance method
                                try:
                                    temp_instance = obj({})
                                    if hasattr(temp_instance, 'plugin_name'):
                                        self.register_plugin(obj)
                                except Exception as e:
                                    self.logger.warning(f"Skipping invalid plugin class {name}: {e}")

                    except Exception as e:
                        self.logger.error(f"Failed to load plugin file {filename}: {e}")

        except Exception as e:
            self.logger.error(f"Failed to discover plugins in directory {directory}: {e}")


# Global plugin manager instance
plugin_manager = PluginManager()

# Auto-load plugins on import
plugin_manager.load_plugins_from_directory()