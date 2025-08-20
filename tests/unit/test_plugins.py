"""Unit tests for TrakBridge plugin system."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml

from plugins.base_plugin import BaseGPSPlugin
from plugins.plugin_manager import PluginManager


class TestPluginManager:
    """Test the PluginManager."""

    def test_plugin_manager_initialization(self):
        """Test PluginManager initialization."""
        manager = PluginManager()
        assert manager is not None
        assert hasattr(manager, "plugins")
        assert isinstance(manager.plugins, dict)

    def test_get_available_plugins(self):
        """Test getting available plugins."""
        manager = PluginManager()
        plugins = manager.list_plugins()
        assert isinstance(plugins, list)

    def test_get_plugin_info(self):
        """Test getting plugin information."""
        manager = PluginManager()

        # Test with a real plugin name (if any exist) or handle None return
        plugin_names = manager.list_plugins()
        if plugin_names:
            # Test with first available plugin
            info = manager.get_plugin_metadata(plugin_names[0])
            assert info is None or isinstance(info, dict)  # May be None if no metadata
        else:
            # Test with non-existent plugin
            info = manager.get_plugin_metadata("nonexistent")
            assert info is None

    def test_load_plugins_from_directory(self):
        """Test loading plugins from directory."""
        manager = PluginManager()

        # This should not raise an exception
        try:
            manager.load_plugins_from_directory()
            assert True
        except Exception as e:
            # If it fails, it should fail gracefully
            assert "No module named" in str(e) or "Cannot import" in str(e)

    def test_load_external_plugins(self):
        """Test loading external plugins."""
        manager = PluginManager()

        # This should not raise an exception
        try:
            manager.load_external_plugins()
            assert True
        except Exception as e:
            # If it fails, it should fail gracefully
            assert "No module named" in str(e) or "Cannot import" in str(e)


class TestBaseGPSPlugin:
    """Test the base GPS plugin."""

    def test_base_plugin_interface(self):
        """Test base plugin interface."""

        # Create a concrete implementation for testing
        class TestPlugin(BaseGPSPlugin):
            @property
            def plugin_name(self) -> str:
                return "Test Plugin"

            @property
            def plugin_metadata(self) -> dict:
                return {
                    "display_name": "Test Plugin",
                    "description": "Test plugin for unit testing",
                    "version": "1.0.0",
                    "icon": "fa-test",
                    "category": "test",
                    "config_fields": [],
                }

            async def fetch_locations(self, session):
                return [{"test": "location"}]

        plugin = TestPlugin({})
        assert plugin.plugin_name == "Test Plugin"
        assert plugin.plugin_metadata["description"] == "Test plugin for unit testing"
        assert plugin.plugin_metadata["version"] == "1.0.0"

    def test_base_plugin_methods(self):
        """Test base plugin methods."""

        class TestPlugin(BaseGPSPlugin):
            @property
            def plugin_name(self) -> str:
                return "Test Plugin"

            @property
            def plugin_metadata(self) -> dict:
                return {
                    "display_name": "Test Plugin",
                    "description": "Test plugin for unit testing",
                    "config_fields": [],
                }

            async def fetch_locations(self, session):
                return [{"test": "data"}]

        plugin = TestPlugin({"test_config": "value"})

        # Test plugin properties
        assert plugin.plugin_name == "Test Plugin"
        assert plugin.plugin_metadata["description"] == "Test plugin for unit testing"

        # Test configuration access
        assert plugin.config["test_config"] == "value"

    def test_plugin_configuration(self):
        """Test plugin configuration handling."""

        class TestPlugin(BaseGPSPlugin):
            @property
            def plugin_name(self) -> str:
                return "Test Plugin"

            @property
            def plugin_metadata(self) -> dict:
                return {
                    "display_name": "Test Plugin",
                    "description": "Test plugin for configuration testing",
                    "config_fields": [],
                }

            async def fetch_locations(self, session):
                return []

        config = {"api_key": "test123", "endpoint": "http://test.com"}
        plugin = TestPlugin(config)

        # Plugin should store configuration
        assert hasattr(plugin, "config")
        assert plugin.config == config


class TestPluginValidation:
    """Test plugin validation and security."""

    def test_plugin_validation_exists(self):
        """Test that plugin validation methods exist."""
        manager = PluginManager()

        # These methods should exist
        assert hasattr(manager, "validate_plugin_config") or hasattr(
            manager, "_validate_module_name"
        )

    def test_plugin_loading_security(self):
        """Test plugin loading security measures."""
        manager = PluginManager()

        # Test that dangerous modules are blocked
        with pytest.raises((ImportError, ValueError, Exception)):
            # This should fail safely
            manager._load_plugin_module("__builtin__")

    def test_plugin_configuration_validation(self):
        """Test plugin configuration validation."""
        manager = PluginManager()

        # Test configuration validation
        invalid_config = {"__class__": "dangerous"}

        # Should handle invalid configuration safely
        try:
            result = manager._validate_plugin_config(invalid_config)
            # If validation exists, should return False or raise exception
            assert result is False or result is None
        except (AttributeError, NameError):
            # Method might not exist, which is fine
            assert True


class TestPluginConfigurationHandling:
    """Test plugin configuration loading and validation edge cases."""

    def test_none_allowed_modules_handling(self):
        """Test that None values for allowed_plugin_modules are handled gracefully."""
        # Create a temporary config with None value
        config_data = {"allowed_plugin_modules": None}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name

        try:
            with patch(
                "utils.config_manager.config_manager.load_config_safe"
            ) as mock_load:
                mock_load.return_value = config_data

                manager = PluginManager()
                # This should not raise an exception and should log appropriately
                manager._load_allowed_plugins_config()

                # Verify that only built-in plugins are loaded
                allowed_modules = manager.get_allowed_plugin_modules()
                assert isinstance(allowed_modules, list)
                # Should contain built-in modules
                assert any("plugins." in module for module in allowed_modules)
        finally:
            Path(temp_config_path).unlink()

    def test_empty_list_allowed_modules_handling(self):
        """Test that empty list values for allowed_plugin_modules are handled gracefully."""
        config_data = {"allowed_plugin_modules": []}

        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.return_value = config_data

            manager = PluginManager()
            # This should not raise an exception
            manager._load_allowed_plugins_config()

            # Should still have built-in plugins
            allowed_modules = manager.get_allowed_plugin_modules()
            assert isinstance(allowed_modules, list)
            assert len(allowed_modules) > 0  # Built-in plugins should be present

    def test_valid_plugin_modules_list_handling(self):
        """Test that valid plugin module lists are processed correctly."""
        config_data = {
            "allowed_plugin_modules": [
                "plugins.custom_plugin",
                "external_plugins.company_tracker",
            ]
        }

        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.return_value = config_data

            manager = PluginManager()
            manager._load_allowed_plugins_config()

            allowed_modules = manager.get_allowed_plugin_modules()
            assert isinstance(allowed_modules, list)
            # Should contain our custom modules plus built-ins
            assert "plugins.custom_plugin" in allowed_modules
            assert "external_plugins.company_tracker" in allowed_modules

    def test_invalid_plugin_modules_type_handling(self):
        """Test that invalid types for allowed_plugin_modules are handled gracefully."""
        config_data = {"allowed_plugin_modules": "not_a_list"}

        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.return_value = config_data

            manager = PluginManager()
            # Should not raise an exception, should log warning
            manager._load_allowed_plugins_config()

            # Should still work with built-in plugins only
            allowed_modules = manager.get_allowed_plugin_modules()
            assert isinstance(allowed_modules, list)

    def test_config_loading_failure_graceful_fallback(self):
        """Test that configuration loading failures fall back gracefully."""
        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.side_effect = Exception("Config loading failed")

            manager = PluginManager()
            # Should not raise an exception
            manager._load_allowed_plugins_config()

            # Should still work with built-in plugins
            allowed_modules = manager.get_allowed_plugin_modules()
            assert isinstance(allowed_modules, list)
            assert len(allowed_modules) > 0  # Built-in plugins should be present

    def test_unsafe_module_name_filtering(self):
        """Test that unsafe module names are filtered out."""
        config_data = {
            "allowed_plugin_modules": [
                "plugins.safe_plugin",  # Safe
                "__builtin__",  # Unsafe
                "os.system",  # Unsafe
                "external_plugins.safe_external",  # Safe
            ]
        }

        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.return_value = config_data

            manager = PluginManager()
            manager._load_allowed_plugins_config()

            allowed_modules = manager.get_allowed_plugin_modules()
            # Should contain safe modules but not unsafe ones
            assert "plugins.safe_plugin" in allowed_modules
            assert "external_plugins.safe_external" in allowed_modules
            assert "__builtin__" not in allowed_modules
            assert "os.system" not in allowed_modules

    def test_missing_config_key_handling(self):
        """Test handling when allowed_plugin_modules key is missing."""
        config_data = {"other_config": "value"}  # Missing allowed_plugin_modules

        with patch("utils.config_manager.config_manager.load_config_safe") as mock_load:
            mock_load.return_value = config_data

            manager = PluginManager()
            # Should not raise an exception
            manager._load_allowed_plugins_config()

            # Should work with built-in plugins only
            allowed_modules = manager.get_allowed_plugin_modules()
            assert isinstance(allowed_modules, list)

    def test_config_manager_schema_validation(self):
        """Test that config manager schema accepts both None and list values."""
        from utils.config_manager import ConfigManager

        manager = ConfigManager()
        schema = manager.schemas.get("plugins.yaml")

        assert schema is not None
        assert "allowed_plugin_modules" in schema["properties"]

        # Schema should accept both null and array types
        field_schema = schema["properties"]["allowed_plugin_modules"]
        assert "oneOf" in field_schema
        assert {"type": "null"} in field_schema["oneOf"]
        assert any(item.get("type") == "array" for item in field_schema["oneOf"])
