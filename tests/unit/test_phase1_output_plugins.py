"""
ABOUTME: Unit tests for Phase 1 - Bidirectional TAK Communication Foundation
ABOUTME: Tests BaseOutputPlugin, enable_rx field, and plugin manager updates
"""

import pytest
from unittest.mock import Mock, patch
from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from plugins.plugin_manager import PluginManager


class MockOutputPlugin(BaseOutputPlugin):
    """Mock output plugin for testing"""

    @property
    def plugin_name(self) -> str:
        return "mock_output"

    @property
    def plugin_metadata(self) -> dict:
        return {
            "display_name": "Mock Output Plugin",
            "description": "Test plugin for output",
            "icon": "fa-test",
            "category": "forwarding",
            "config_fields": [
                PluginConfigField(
                    name="webhook_url",
                    label="Webhook URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    help_text="Webhook endpoint",
                ),
                PluginConfigField(
                    name="message_filter",
                    label="Message Filter",
                    field_type="text",
                    required=False,
                    help_text="Filter pattern",
                ),
            ],
        }

    async def handle_cot_message(
        self, cot_xml: bytes, tak_server_id: int
    ) -> None:
        """Mock implementation"""
        pass


class TestBaseOutputPlugin:
    """Test BaseOutputPlugin base class"""

    def test_output_plugin_initialization(self):
        """Test that output plugin can be instantiated with config"""
        config = {
            "webhook_url": "https://example.com/webhook",
            "message_filter": "b-t-f",
        }
        plugin = MockOutputPlugin(config)

        assert plugin.config == config
        assert plugin.stream is None
        assert plugin.plugin_name == "mock_output"

    def test_output_plugin_metadata(self):
        """Test that plugin metadata is correctly structured"""
        plugin = MockOutputPlugin({})
        metadata = plugin.plugin_metadata

        assert metadata["display_name"] == "Mock Output Plugin"
        assert metadata["category"] == "forwarding"
        assert metadata["icon"] == "fa-test"
        assert len(metadata["config_fields"]) == 2

    def test_output_plugin_config_fields_extraction(self):
        """Test extraction of configuration fields from metadata"""
        plugin = MockOutputPlugin({})
        config_fields = plugin.get_config_fields()

        assert len(config_fields) == 2
        assert config_fields[0].name == "webhook_url"
        assert config_fields[0].required is True
        assert config_fields[0].sensitive is True
        assert config_fields[1].name == "message_filter"
        assert config_fields[1].required is False

    def test_output_plugin_sensitive_fields(self):
        """Test identification of sensitive fields"""
        plugin = MockOutputPlugin({})
        sensitive_fields = plugin.get_sensitive_fields()

        assert "webhook_url" in sensitive_fields
        assert "message_filter" not in sensitive_fields

    @patch("services.encryption_service.EncryptionService")
    def test_output_plugin_config_decryption(self, mock_encryption_service):
        """Test decryption of sensitive configuration fields"""
        mock_encryption = Mock()
        mock_encryption.decrypt_value.return_value = "decrypted_value"
        mock_encryption_service.return_value = mock_encryption

        config = {
            "webhook_url": "encrypted_url",
            "message_filter": "plain_text",
        }
        plugin = MockOutputPlugin(config)
        decrypted_config = plugin.get_decrypted_config()

        assert decrypted_config["webhook_url"] == "decrypted_value"
        assert decrypted_config["message_filter"] == "plain_text"
        mock_encryption.decrypt_value.assert_called_once()

    def test_output_plugin_validation_required_fields(self):
        """Test validation catches missing required fields"""
        # Missing webhook_url (required field)
        plugin = MockOutputPlugin({"message_filter": "test"})

        is_valid = plugin.validate_config()
        assert is_valid is False

    def test_output_plugin_validation_url_fields(self):
        """Test validation of URL fields"""
        # Invalid URL
        plugin = MockOutputPlugin({"webhook_url": "not_a_url"})

        is_valid = plugin.validate_config()
        assert is_valid is False

        # Valid URL
        plugin = MockOutputPlugin({"webhook_url": "https://example.com"})
        is_valid = plugin.validate_config()
        assert is_valid is True

    def test_output_plugin_handle_cot_abstract(self):
        """Test that handle_cot_message must be implemented"""
        # This is tested by MockOutputPlugin implementation
        plugin = MockOutputPlugin({})
        assert hasattr(plugin, "handle_cot_message")
        assert callable(plugin.handle_cot_message)


class TestTakServerEnableRx:
    """Test enable_rx field in TakServer model"""

    def test_tak_server_has_enable_rx_field(self):
        """Test that TakServer model has enable_rx field"""
        from models.tak_server import TakServer

        # Check that the column exists in the model
        assert hasattr(TakServer, "enable_rx")

    @patch("models.tak_server.db")
    def test_tak_server_enable_rx_default_value(self, mock_db):
        """Test that enable_rx defaults to True"""
        from models.tak_server import TakServer

        # The default should be True (backward compatible)
        column = TakServer.enable_rx
        assert column.default.arg is True

    @patch("models.tak_server.db")
    def test_tak_server_to_dict_includes_enable_rx(self, mock_db):
        """Test that to_dict() includes enable_rx field"""
        from models.tak_server import TakServer

        # Create a mock server instance
        server = TakServer()
        server.id = 1
        server.name = "Test Server"
        server.host = "localhost"
        server.port = 8089
        server.protocol = "tls"
        server.verify_ssl = True
        server.enable_rx = True
        server.cert_p12 = None
        server.cert_p12_filename = None
        server.created_at = Mock()
        server.created_at.isoformat = Mock(return_value="2025-01-01T00:00:00")
        server.updated_at = Mock()
        server.updated_at.isoformat = Mock(return_value="2025-01-01T00:00:00")

        result = server.to_dict()

        assert "enable_rx" in result
        assert result["enable_rx"] is True


class TestPluginManagerOutputSupport:
    """Test PluginManager support for output plugins"""

    def test_plugin_manager_registers_output_plugin(self):
        """Test that plugin manager can register output plugins"""
        manager = PluginManager()
        manager.register_plugin(MockOutputPlugin)

        assert "mock_output" in manager.plugins
        assert manager.plugins["mock_output"] == MockOutputPlugin

    def test_plugin_manager_get_output_plugin(self):
        """Test that plugin manager can instantiate output plugins"""
        manager = PluginManager()
        manager.register_plugin(MockOutputPlugin)

        config = {"webhook_url": "https://example.com"}
        plugin = manager.get_plugin("mock_output", config)

        assert plugin is not None
        assert isinstance(plugin, MockOutputPlugin)
        assert plugin.config == config

    def test_plugin_manager_get_output_plugin_metadata(self):
        """Test retrieval of output plugin metadata"""
        manager = PluginManager()
        manager.register_plugin(MockOutputPlugin)

        metadata = manager.get_plugin_metadata("mock_output")

        assert metadata is not None
        assert metadata["category"] == "forwarding"
        assert metadata["display_name"] == "Mock Output Plugin"

    def test_plugin_manager_validates_output_plugin_config(self):
        """Test configuration validation for output plugins"""
        manager = PluginManager()
        manager.register_plugin(MockOutputPlugin)

        # Invalid config (missing required field)
        result = manager.validate_plugin_config(
            "mock_output", {"message_filter": "test"}
        )
        assert result["valid"] is False

        # Valid config
        result = manager.validate_plugin_config(
            "mock_output", {"webhook_url": "https://example.com"}
        )
        assert result["valid"] is True

    def test_plugin_manager_lists_both_plugin_types(self):
        """Test that plugin manager lists both GPS and output plugins"""
        from plugins.traccar_plugin import TraccarPlugin

        manager = PluginManager()
        manager.register_plugin(TraccarPlugin)
        manager.register_plugin(MockOutputPlugin)

        plugins = manager.list_plugins()

        assert "traccar" in plugins
        assert "mock_output" in plugins

    def test_plugin_manager_get_categories_includes_output(self):
        """Test that get_plugin_categories includes forwarding category"""
        manager = PluginManager()
        manager.register_plugin(MockOutputPlugin)

        categories = manager.get_plugin_categories()

        assert "forwarding" in categories


class TestBackwardCompatibility:
    """Test that Phase 1 changes are backward compatible"""

    def test_gps_plugins_still_work(self):
        """Test that existing GPS plugins are unaffected"""
        from plugins.traccar_plugin import TraccarPlugin

        # GPS plugin should still instantiate normally
        config = {
            "url": "http://localhost:8082",
            "username": "admin",
            "password": "admin",
        }
        plugin = TraccarPlugin(config)

        assert plugin.plugin_name == "traccar"
        assert hasattr(plugin, "fetch_locations")
        # Should NOT have handle_cot_message
        assert not hasattr(plugin, "handle_cot_message")

    def test_plugin_manager_backward_compatible(self):
        """Test that plugin manager works with existing GPS plugins"""
        from plugins.traccar_plugin import TraccarPlugin

        manager = PluginManager()
        manager.register_plugin(TraccarPlugin)

        # Traccar plugin requires server_url not url
        config = {
            "server_url": "http://localhost:8082",
            "username": "admin",
            "password": "admin",
        }
        plugin = manager.get_plugin("traccar", config)

        assert plugin is not None
        assert isinstance(plugin, TraccarPlugin)

    def test_existing_streams_unaffected(self):
        """Test that existing Stream model works unchanged"""
        # Import Stream model
        from models.stream import Stream

        # Verify Stream model has expected fields (no changes needed)
        assert hasattr(Stream, "plugin_type")
        assert hasattr(Stream, "tak_server_id")
        assert hasattr(Stream, "plugin_config")
        assert hasattr(Stream, "is_active")


class TestMigration:
    """Test database migration for enable_rx field"""

    def test_migration_file_exists(self):
        """Test that migration file was created"""
        import os

        migration_path = "migrations/versions/add_enable_rx_to_tak_servers.py"
        assert os.path.exists(migration_path)

    def test_migration_has_upgrade_function(self):
        """Test that migration has upgrade function"""
        import importlib.util
        import os

        migration_path = (
            "/Users/nick/Documents/Repositories/projects/trakbridge/"
            "migrations/versions/add_enable_rx_to_tak_servers.py"
        )

        if os.path.exists(migration_path):
            spec = importlib.util.spec_from_file_location(
                "migration", migration_path
            )
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            assert hasattr(migration, "upgrade")
            assert hasattr(migration, "downgrade")
            assert callable(migration.upgrade)
            assert callable(migration.downgrade)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
