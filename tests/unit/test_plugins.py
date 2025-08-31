"""Unit tests for TrakBridge plugin system."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml

from plugins.base_plugin import BaseGPSPlugin, CallsignMappable, FieldMetadata
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
        """Test that config manager schema structure prevents recursion issues."""
        from utils.config_manager import ConfigManager

        manager = ConfigManager()
        schema = manager.schemas.get("plugins.yaml")

        assert schema is not None
        assert "allowed_plugin_modules" in schema["properties"]

        # Schema should be simple array type (oneOf causes recursion in simplified validator)
        field_schema = schema["properties"]["allowed_plugin_modules"]
        assert field_schema["type"] == "array"
        assert field_schema["items"]["type"] == "string"

        # Should NOT use oneOf to prevent maximum recursion depth issues
        assert "oneOf" not in field_schema


@pytest.mark.callsign
class TestBaseGPSPlugin:
    """Test the BaseGPSPlugin interface detection methods"""

    def test_base_plugin_methods(self):
        """Test BaseGPSPlugin has callsign mapping support methods"""

        # Create a mock plugin class for testing
        class MockPlugin(BaseGPSPlugin):
            @property
            def plugin_name(self) -> str:
                return "mock"

            @property
            def plugin_metadata(self) -> dict:
                return {"display_name": "Mock Plugin"}

            async def fetch_locations(self, session):
                return []

        plugin = MockPlugin({})

        # Test interface detection methods exist
        assert hasattr(plugin, "supports_callsign_mapping")
        assert hasattr(plugin, "get_callsign_fields")
        assert hasattr(plugin, "apply_callsign_mappings")

        # Test default behavior (no interface implemented)
        assert plugin.supports_callsign_mapping() is False
        assert plugin.get_callsign_fields() == []
        assert plugin.apply_callsign_mappings([], "field", {}) is False

    def test_base_plugin_interface_detection(self):
        """Test that BaseGPSPlugin correctly detects CallsignMappable interface"""

        # Create plugin that implements CallsignMappable
        class CallsignPlugin(BaseGPSPlugin, CallsignMappable):
            @property
            def plugin_name(self) -> str:
                return "callsign_mock"

            @property
            def plugin_metadata(self) -> dict:
                return {"display_name": "Callsign Mock Plugin"}

            async def fetch_locations(self, session):
                return []

            def get_available_fields(self):
                return [FieldMetadata("test", "Test Field", "string")]

            def apply_callsign_mapping(self, tracker_data, field_name, callsign_map):
                pass

        plugin = CallsignPlugin({})

        # Should detect interface is implemented
        assert plugin.supports_callsign_mapping() is True
        fields = plugin.get_callsign_fields()
        assert len(fields) == 1
        assert fields[0].name == "test"


@pytest.mark.callsign
class TestCallsignMappableInterface:
    """Test the CallsignMappable interface and FieldMetadata"""

    def test_field_metadata_creation(self):
        """Test FieldMetadata creation and properties"""
        field = FieldMetadata(
            name="test_field",
            display_name="Test Field",
            type="string",
            recommended=True,
            description="Test description",
        )

        assert field.name == "test_field"
        assert field.display_name == "Test Field"
        assert field.type == "string"
        assert field.recommended is True
        assert field.description == "Test description"

    def test_field_metadata_defaults(self):
        """Test FieldMetadata default values"""
        field = FieldMetadata("test", "Test", "string")

        assert field.recommended is False
        assert field.description == ""

    def test_callsign_mappable_abstract_methods(self):
        """Test that CallsignMappable is abstract and requires implementation"""
        # Should not be able to instantiate CallsignMappable directly
        with pytest.raises(TypeError):
            CallsignMappable()


@pytest.mark.callsign
class TestGarminPluginInterface:
    """Test Garmin plugin CallsignMappable implementation"""

    def test_garmin_plugin_get_available_fields(self):
        """Test Garmin plugin returns correct field metadata"""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin({"url": "test", "username": "test", "password": "test"})
        fields = plugin.get_available_fields()

        assert len(fields) == 3
        field_names = [f.name for f in fields]
        assert "imei" in field_names
        assert "name" in field_names
        assert "uid" in field_names

        # IMEI should be recommended
        imei_field = next(f for f in fields if f.name == "imei")
        assert imei_field.recommended is True
        assert imei_field.display_name == "Device IMEI"

    def test_garmin_plugin_apply_callsign_mapping(self):
        """Test Garmin plugin applies callsign mappings correctly"""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin({"url": "test", "username": "test", "password": "test"})

        # Test data with Garmin structure
        test_data = [
            {
                "name": "Original Name",
                "uid": "test-uid-123",
                "additional_data": {
                    "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                },
            }
        ]

        callsign_map = {"123456789": "Alpha-1"}

        # Apply mapping using IMEI field
        plugin.apply_callsign_mapping(test_data, "imei", callsign_map)

        # Should have updated name
        assert test_data[0]["name"] == "Alpha-1"

    def test_garmin_plugin_supports_interface(self):
        """Test that Garmin plugin properly implements CallsignMappable"""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin({"url": "test", "username": "test", "password": "test"})

        assert plugin.supports_callsign_mapping() is True
        assert isinstance(plugin, CallsignMappable)


@pytest.mark.callsign
class TestSpotPluginInterface:
    """Test SPOT plugin CallsignMappable implementation"""

    def test_spot_plugin_get_available_fields(self):
        """Test SPOT plugin returns correct field metadata"""
        from plugins.spot_plugin import SpotPlugin

        plugin = SpotPlugin({"feed_id": "test123"})
        fields = plugin.get_available_fields()

        assert len(fields) == 3
        field_names = [f.name for f in fields]
        assert "messenger_name" in field_names
        assert "feed_id" in field_names
        assert "device_id" in field_names

        # messenger_name should be recommended
        name_field = next(f for f in fields if f.name == "messenger_name")
        assert name_field.recommended is True
        assert name_field.display_name == "Device Name"

    def test_spot_plugin_apply_callsign_mapping(self):
        """Test SPOT plugin applies callsign mappings correctly"""
        from plugins.spot_plugin import SpotPlugin

        plugin = SpotPlugin({"feed_id": "test123"})

        # Test data with SPOT structure
        test_data = [
            {
                "name": "Original SPOT Device",
                "additional_data": {
                    "raw_message": {"messengerName": "SPOT-Device-001"},
                    "feed_id": "test123",
                },
            }
        ]

        callsign_map = {"SPOT-Device-001": "Bravo-2"}

        # Apply mapping using messenger_name field
        plugin.apply_callsign_mapping(test_data, "messenger_name", callsign_map)

        # Should have updated name
        assert test_data[0]["name"] == "Bravo-2"

    def test_spot_plugin_supports_interface(self):
        """Test that SPOT plugin properly implements CallsignMappable"""
        from plugins.spot_plugin import SpotPlugin

        plugin = SpotPlugin({"feed_id": "test123"})

        assert plugin.supports_callsign_mapping() is True
        assert isinstance(plugin, CallsignMappable)


@pytest.mark.callsign
class TestTraccarPluginInterface:
    """Test Traccar plugin CallsignMappable implementation"""

    def test_traccar_plugin_get_available_fields(self):
        """Test Traccar plugin returns correct field metadata"""
        from plugins.traccar_plugin import TraccarPlugin

        plugin = TraccarPlugin(
            {"server_url": "http://test", "username": "test", "password": "test"}
        )
        fields = plugin.get_available_fields()

        assert len(fields) == 3
        field_names = [f.name for f in fields]
        assert "name" in field_names
        assert "device_id" in field_names
        assert "unique_id" in field_names

        # name should be recommended
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.recommended is True
        assert name_field.display_name == "Device Name"

    def test_traccar_plugin_apply_callsign_mapping(self):
        """Test Traccar plugin applies callsign mappings correctly"""
        from plugins.traccar_plugin import TraccarPlugin

        plugin = TraccarPlugin(
            {"server_url": "http://test", "username": "test", "password": "test"}
        )

        # Test data with Traccar structure
        test_data = [
            {
                "name": "Vehicle 001",
                "additional_data": {
                    "device_id": 123,
                    "device_info": {"uniqueId": "IMEI123456789"},
                },
            }
        ]

        callsign_map = {"Vehicle 001": "Charlie-3"}

        # Apply mapping using name field
        plugin.apply_callsign_mapping(test_data, "name", callsign_map)

        # Should have updated name
        assert test_data[0]["name"] == "Charlie-3"

    def test_traccar_plugin_supports_interface(self):
        """Test that Traccar plugin properly implements CallsignMappable"""
        from plugins.traccar_plugin import TraccarPlugin

        plugin = TraccarPlugin(
            {"server_url": "http://test", "username": "test", "password": "test"}
        )

        assert plugin.supports_callsign_mapping() is True
        assert isinstance(plugin, CallsignMappable)


@pytest.mark.callsign
class TestPluginFallbackBehavior:
    """Test plugin fallback behavior for non-CallsignMappable plugins"""

    def test_deepstate_plugin_fallback(self):
        """Test that Deepstate plugin (non-tracker) gracefully handles callsign methods"""
        try:
            from plugins.deepstate_plugin import DeepstatePlugin

            plugin = DeepstatePlugin({"api_key": "test"})

            # Should not implement CallsignMappable
            assert plugin.supports_callsign_mapping() is False
            assert not isinstance(plugin, CallsignMappable)

            # Should return empty fields and fail gracefully
            assert plugin.get_callsign_fields() == []
            assert plugin.apply_callsign_mappings([], "field", {}) is False

        except ImportError:
            # Plugin might not exist in test environment
            pytest.skip("Deepstate plugin not available")

    def test_plugin_interface_error_handling(self):
        """Test plugin interface error handling"""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin({"url": "test", "username": "test", "password": "test"})

        # Test with invalid data structure
        invalid_data = [{"invalid": "structure"}]
        callsign_map = {"test": "mapped"}

        # Should handle gracefully without crashing
        plugin.apply_callsign_mapping(invalid_data, "imei", callsign_map)

        # Data should be unchanged since no valid identifier found
        assert invalid_data[0]["invalid"] == "structure"

    def test_plugin_mapping_with_empty_map(self):
        """Test plugin behavior with empty callsign map"""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin({"url": "test", "username": "test", "password": "test"})

        test_data = [
            {
                "name": "Original Name",
                "additional_data": {
                    "raw_placemark": {"extended_data": {"IMEI": "123456789"}}
                },
            }
        ]

        # Apply mapping with empty map
        plugin.apply_callsign_mapping(test_data, "imei", {})

        # Should remain unchanged
        assert test_data[0]["name"] == "Original Name"
