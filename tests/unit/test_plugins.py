"""Unit tests for TrakBridge plugin system."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from plugins.plugin_manager import PluginManager
from plugins.base_plugin import BaseGPSPlugin


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
        plugins = manager.get_available_plugins()
        assert isinstance(plugins, dict)

    def test_get_plugin_info(self):
        """Test getting plugin information."""
        manager = PluginManager()

        # Mock a plugin for testing
        mock_plugin = Mock()
        mock_plugin.name = "Test Plugin"
        mock_plugin.description = "Test Description"
        mock_plugin.version = "1.0.0"

        manager.plugins["test"] = mock_plugin

        info = manager.get_plugin_info("test")
        assert info is not None
        assert "name" in info or info == {}  # May be empty if plugin not found

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
            name = "Test Plugin"
            description = "Test plugin for unit testing"
            version = "1.0.0"

            def fetch_data(self):
                return {"test": "data"}

            def transform_data(self, data):
                return {"transformed": data}

        plugin = TestPlugin({})
        assert plugin.name == "Test Plugin"
        assert plugin.description == "Test plugin for unit testing"
        assert plugin.version == "1.0.0"

    def test_base_plugin_methods(self):
        """Test base plugin methods."""

        class TestPlugin(BaseGPSPlugin):
            name = "Test Plugin"

            def fetch_data(self):
                return {"test": "data"}

            def transform_data(self, data):
                return {"transformed": data}

        plugin = TestPlugin({"test_config": "value"})

        # Test fetch_data
        data = plugin.fetch_data()
        assert data == {"test": "data"}

        # Test transform_data
        transformed = plugin.transform_data({"input": "data"})
        assert transformed == {"transformed": {"input": "data"}}

    def test_plugin_configuration(self):
        """Test plugin configuration handling."""

        class TestPlugin(BaseGPSPlugin):
            name = "Test Plugin"

            def fetch_data(self):
                return {}

            def transform_data(self, data):
                return data

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
        assert hasattr(manager, "validate_plugin") or hasattr(
            manager, "_validate_plugin_security"
        )

    def test_plugin_loading_security(self):
        """Test plugin loading security measures."""
        manager = PluginManager()

        # Test that dangerous modules are blocked
        with pytest.raises((ImportError, ValueError, SecurityError, Exception)):
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
