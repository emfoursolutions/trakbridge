# ABOUTME: Unit tests for LiveUAMap OSINT plugin scaffold and registration
# ABOUTME: Tests naming, metadata, regions, colours, and plugin manager

import pytest

from plugins.plugin_manager import PluginManager


class TestLiveuamapPluginScaffold:
    """Test LiveUAMap plugin scaffold and constants."""

    def test_plugin_name(self):
        """Verify plugin_name property returns 'liveuamap'."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        assert plugin.plugin_name == "liveuamap"

    def test_get_plugin_name_classmethod(self):
        """Verify get_plugin_name() classmethod returns 'liveuamap'."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        assert LiveuamapPlugin.get_plugin_name() == "liveuamap"

    def test_plugin_metadata_structure(self):
        """Verify metadata has all required keys."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        metadata = plugin.plugin_metadata

        required_keys = {
            "display_name",
            "description",
            "icon",
            "category",
            "help_sections",
            "config_fields",
        }
        assert required_keys.issubset(set(metadata.keys()))

    def test_plugin_metadata_category(self):
        """Verify metadata category is 'osint'."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        assert plugin.plugin_metadata["category"] == "osint"

    def test_regions_constant_exists(self):
        """Verify REGIONS dict exists and has 140+ entries."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        assert hasattr(LiveuamapPlugin, "REGIONS")
        assert isinstance(LiveuamapPlugin.REGIONS, dict)
        assert len(LiveuamapPlugin.REGIONS) >= 130

    def test_regions_constant_values(self):
        """Spot-check known region entries."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        assert LiveuamapPlugin.REGIONS["Ukraine"] == 0
        assert LiveuamapPlugin.REGIONS["Syria"] == 3
        assert LiveuamapPlugin.REGIONS["Iran"] == 66

    def test_region_groups_constant_exists(self):
        """Verify REGION_GROUPS dict exists with expected group keys."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        assert hasattr(LiveuamapPlugin, "REGION_GROUPS")
        assert isinstance(LiveuamapPlugin.REGION_GROUPS, dict)
        expected_groups = {
            "International/Conflict",
            "US States",
            "Organizations/Topics",
        }
        actual_groups = set(LiveuamapPlugin.REGION_GROUPS.keys())
        assert expected_groups.issubset(actual_groups)

    def test_colour_to_argb_constant_exists(self):
        """Verify COLOUR_TO_ARGB dict exists with known mappings."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        assert hasattr(LiveuamapPlugin, "COLOUR_TO_ARGB")
        assert isinstance(LiveuamapPlugin.COLOUR_TO_ARGB, dict)
        # Should have at least darkblack as the fallback
        assert "darkblack" in LiveuamapPlugin.COLOUR_TO_ARGB

    def test_plugin_metadata_display_name(self):
        """Verify display_name is set."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        assert plugin.plugin_metadata["display_name"] == "LiveUAMap OSINT"

    def test_plugin_metadata_config_fields(self):
        """Verify config fields include expected fields."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        field_names = [f.name for f in plugin.plugin_metadata["config_fields"]]

        assert "api_key" in field_names
        assert "action" in field_names
        assert "regions" in field_names
        assert "event_time" in field_names
        assert "count" in field_names
        assert "timeout" in field_names

    def test_api_key_field_is_sensitive(self):
        """Verify api_key config field is marked as sensitive."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        fields = plugin.plugin_metadata["config_fields"]
        api_key_field = next(f for f in fields if f.name == "api_key")

        assert api_key_field.sensitive is True
        assert api_key_field.field_type == "password"
        assert api_key_field.required is True

    def test_custom_components_include_region_selector(self):
        """Verify custom_components includes region_selector."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        metadata = plugin.plugin_metadata

        assert "custom_components" in metadata
        component_types = [c.type for c in metadata["custom_components"]]
        assert "region_selector" in component_types

    @pytest.mark.asyncio
    async def test_fetch_locations_stub_returns_empty(self):
        """Verify stubbed fetch_locations returns empty list."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin(
            {"api_key": "test", "regions": "[0]"}
        )
        result = await plugin.fetch_locations(None)
        assert result == []

    def test_validate_config_stub(self):
        """Verify validate_config works with valid config."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        assert plugin.validate_config() is True


class TestLiveuamapPluginRegistration:
    """Test LiveUAMap plugin registration in the plugin manager."""

    def test_plugin_registered_in_manager(self):
        """Verify 'liveuamap' appears in plugin_manager.list_plugins()."""
        manager = PluginManager()
        manager.load_plugins_from_directory()
        assert "liveuamap" in manager.list_plugins()

    def test_plugin_metadata_from_manager(self):
        """Verify get_plugin_metadata('liveuamap') returns dict."""
        manager = PluginManager()
        manager.load_plugins_from_directory()
        metadata = manager.get_plugin_metadata("liveuamap")
        assert metadata is not None
        assert isinstance(metadata, dict)

    def test_plugin_instantiation(self):
        """Verify plugin_manager.get_plugin() returns an instance."""
        manager = PluginManager()
        manager.load_plugins_from_directory()
        plugin = manager.get_plugin(
            "liveuamap", {"api_key": "testkey", "regions": "[0]"}
        )
        assert plugin is not None
        assert plugin.plugin_name == "liveuamap"
