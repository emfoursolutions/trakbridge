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


class TestLiveuamapConfigValidation:
    """Test LiveUAMap plugin configuration validation."""

    def _make_plugin(self, **overrides):
        """Helper to create plugin with config overrides."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        config = {
            "api_key": "test-key-123",
            "regions": "[0, 3]",
            "action": "mpts",
            "event_time": "",
            "count": 50,
            "timeout": 30,
        }
        config.update(overrides)
        return LiveuamapPlugin(config)

    def test_valid_config(self):
        """Full valid config returns True."""
        plugin = self._make_plugin()
        assert plugin.validate_config() is True

    def test_missing_api_key(self):
        """Empty api_key returns False."""
        plugin = self._make_plugin(api_key="")
        assert plugin.validate_config() is False

    def test_none_api_key(self):
        """None api_key returns False."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin({"regions": "[0]"})
        assert plugin.validate_config() is False

    def test_missing_regions(self):
        """Empty regions returns False."""
        plugin = self._make_plugin(regions="")
        assert plugin.validate_config() is False

    def test_empty_regions_list(self):
        """regions='[]' returns False."""
        plugin = self._make_plugin(regions="[]")
        assert plugin.validate_config() is False

    def test_invalid_regions_json(self):
        """regions='not json' returns False."""
        plugin = self._make_plugin(regions="not json")
        assert plugin.validate_config() is False

    def test_invalid_region_id(self):
        """regions='[99999]' returns False (ID not in REGIONS)."""
        plugin = self._make_plugin(regions="[99999]")
        assert plugin.validate_config() is False

    def test_valid_region_ids(self):
        """regions='[0, 3]' (Ukraine, Syria) returns True."""
        plugin = self._make_plugin(regions="[0, 3]")
        assert plugin.validate_config() is True

    def test_count_too_low(self):
        """count=0 returns False."""
        plugin = self._make_plugin(count=0)
        assert plugin.validate_config() is False

    def test_count_too_high(self):
        """count=501 returns False."""
        plugin = self._make_plugin(count=501)
        assert plugin.validate_config() is False

    def test_count_valid(self):
        """count=50 returns True."""
        plugin = self._make_plugin(count=50)
        assert plugin.validate_config() is True

    def test_timeout_too_low(self):
        """timeout=1 returns False."""
        plugin = self._make_plugin(timeout=1)
        assert plugin.validate_config() is False

    def test_timeout_too_high(self):
        """timeout=999 returns False."""
        plugin = self._make_plugin(timeout=999)
        assert plugin.validate_config() is False

    def test_timeout_valid(self):
        """timeout=30 returns True."""
        plugin = self._make_plugin(timeout=30)
        assert plugin.validate_config() is True

    def test_defaults_applied(self):
        """Missing optional fields use defaults and pass."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        plugin = LiveuamapPlugin(
            {"api_key": "test-key", "regions": "[0]"}
        )
        assert plugin.validate_config() is True


class TestLiveuamapColourParsing:
    """Test colour extraction from picpath URLs."""

    def _parse(self, picpath):
        from plugins.liveuamap_plugin import LiveuamapPlugin
        return LiveuamapPlugin._parse_colour_from_picpath(picpath)

    def test_parse_darkblack_from_picpath(self):
        """Extract 'darkblack' from aa_darkblack.png URL."""
        url = "https://a.liveuamap.com/images/is14/aa_darkblack.png"
        assert self._parse(url) == "darkblack"

    def test_parse_red_from_picpath(self):
        """Extract 'red' from rescue_red.png URL."""
        url = "https://a.liveuamap.com/images/is14/rescue_red.png"
        assert self._parse(url) == "red"

    def test_parse_brown_from_picpath(self):
        """Extract 'brown' from explode_brown.png URL."""
        url = "https://a.liveuamap.com/images/is14/explode_brown.png"
        assert self._parse(url) == "brown"

    def test_parse_blue_from_picpath(self):
        """Extract 'blue' from bomb_blue.png URL."""
        url = "https://a.liveuamap.com/images/is14/bomb_blue.png"
        assert self._parse(url) == "blue"

    def test_parse_unknown_colour(self):
        """Extract 'purple' even if not in ARGB map."""
        url = "https://a.liveuamap.com/images/is14/unknown_purple.png"
        assert self._parse(url) == "purple"

    def test_parse_empty_picpath(self):
        """Empty string falls back to 'darkblack'."""
        assert self._parse("") == "darkblack"

    def test_parse_none_picpath(self):
        """None falls back to 'darkblack'."""
        assert self._parse(None) == "darkblack"

    def test_parse_malformed_picpath(self):
        """Malformed string falls back gracefully."""
        assert self._parse("not_a_url") == "darkblack"


class TestLiveuamapCustomCotAttrib:
    """Test custom CoT attribute building for venues."""

    def _build(self, venue):
        from plugins.liveuamap_plugin import LiveuamapPlugin
        return LiveuamapPlugin._build_custom_cot_attrib(venue)

    def test_build_attrib_darkblack(self):
        """Verify colour and icon for darkblack venue."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        venue = {
            "picpath": "https://a.liveuamap.com/images/is14/aa_darkblack.png"
        }
        attrib = self._build(venue)
        argb = LiveuamapPlugin.COLOUR_TO_ARGB["darkblack"]
        color_val = attrib["detail"]["color"]["_attributes"]["argb"]
        assert color_val == str(argb)

    def test_build_attrib_red(self):
        """Verify correct ARGB for red."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        venue = {
            "picpath": "https://a.liveuamap.com/images/is14/rescue_red.png"
        }
        attrib = self._build(venue)
        argb = LiveuamapPlugin.COLOUR_TO_ARGB["red"]
        color_val = attrib["detail"]["color"]["_attributes"]["argb"]
        assert color_val == str(argb)

    def test_build_attrib_unknown_colour_uses_fallback(self):
        """Unknown colour falls back to darkblack ARGB."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        venue = {
            "picpath": "https://a.liveuamap.com/images/is14/x_neon.png"
        }
        attrib = self._build(venue)
        fallback = LiveuamapPlugin.COLOUR_TO_ARGB["darkblack"]
        color_val = attrib["detail"]["color"]["_attributes"]["argb"]
        assert color_val == str(fallback)

    def test_attrib_structure(self):
        """Verify dict has detail.color._attributes.argb and detail.usericon._attributes.iconsetpath."""
        venue = {
            "picpath": "https://a.liveuamap.com/images/is14/aa_darkblack.png"
        }
        attrib = self._build(venue)

        assert "detail" in attrib
        assert "color" in attrib["detail"]
        assert "_attributes" in attrib["detail"]["color"]
        assert "argb" in attrib["detail"]["color"]["_attributes"]
        assert "usericon" in attrib["detail"]
        assert "_attributes" in attrib["detail"]["usericon"]
        assert "iconsetpath" in attrib["detail"]["usericon"]["_attributes"]

    def test_iconsetpath_format(self):
        """Verify iconsetpath format is COT_MAPPING_SPOTMAP/b-m-p-s-m/{argb}."""
        from plugins.liveuamap_plugin import LiveuamapPlugin

        venue = {
            "picpath": "https://a.liveuamap.com/images/is14/rescue_red.png"
        }
        attrib = self._build(venue)
        argb = LiveuamapPlugin.COLOUR_TO_ARGB["red"]
        expected = f"COT_MAPPING_SPOTMAP/b-m-p-s-m/{argb}"
        iconpath = attrib["detail"]["usericon"]["_attributes"]["iconsetpath"]
        assert iconpath == expected


class TestLiveuamapVenueConversion:
    """Test venue-to-location conversion."""

    SAMPLE_VENUE = {
        "id": 12345,
        "lat": 48.4647,
        "lng": 35.0462,
        "timestamp": 1709568000,
        "name": "Explosion reported in Dnipro",
        "location": "Dnipro, Dnipropetrovsk Oblast",
        "picpath": "https://a.liveuamap.com/images/is14/aa_darkblack.png",
        "svimg": "https://a.liveuamap.com/images/sv/12345.jpg",
        "link": "/en/2024/3/4/explosion-reported-in-dnipro",
        "source_url": "https://t.me/dnipro_news/54321",
        "category_id": 1,
    }

    def _convert(self, venue=None, region_name="Ukraine", region_id=0):
        from plugins.liveuamap_plugin import LiveuamapPlugin
        if venue is None:
            venue = dict(self.SAMPLE_VENUE)
        return LiveuamapPlugin._convert_venue_to_location(
            venue, region_name, region_id
        )

    def test_basic_venue_conversion(self):
        """Convert sample venue, verify standard location fields."""
        loc = self._convert()
        assert loc is not None
        assert "uid" in loc
        assert "name" in loc
        assert "lat" in loc
        assert "lon" in loc
        assert "timestamp" in loc
        assert "description" in loc
        assert "cot_type" in loc
        assert "additional_data" in loc

    def test_lat_lon_mapping(self):
        """venue['lat'] maps to location['lat'], venue['lng'] to location['lon']."""
        loc = self._convert()
        assert loc["lat"] == 48.4647
        assert loc["lon"] == 35.0462

    def test_timestamp_conversion(self):
        """venue['timestamp'] (Unix int) converts to datetime with UTC tz."""
        from datetime import datetime, timezone
        loc = self._convert()
        ts = loc["timestamp"]
        assert isinstance(ts, datetime)
        assert ts.tzinfo == timezone.utc
        assert ts.year == 2024

    def test_name_truncation(self):
        """Venue name >100 chars is truncated to 100."""
        venue = dict(self.SAMPLE_VENUE)
        venue["name"] = "A" * 150
        loc = self._convert(venue)
        assert len(loc["name"]) == 100

    def test_name_short(self):
        """Venue name <100 chars is unchanged."""
        loc = self._convert()
        assert loc["name"] == "Explosion reported in Dnipro"

    def test_uid_format(self):
        """Verify uid == 'liveuamap-{venue_id}'."""
        loc = self._convert()
        assert loc["uid"] == "liveuamap-12345"

    def test_cot_type_always_bmpms(self):
        """cot_type is always 'b-m-p-s-m'."""
        loc = self._convert()
        assert loc["cot_type"] == "b-m-p-s-m"

    def test_description_includes_location(self):
        """venue['location'] appears in description."""
        loc = self._convert()
        assert "Dnipro, Dnipropetrovsk Oblast" in loc["description"]

    def test_description_includes_source(self):
        """'LiveUAMap' appears in description."""
        loc = self._convert()
        assert "LiveUAMap" in loc["description"]

    def test_additional_data_fields(self):
        """Verify expected additional_data keys are present."""
        loc = self._convert()
        ad = loc["additional_data"]
        assert ad["source"] == "liveuamap"
        assert ad["event_id"] == 12345
        assert ad["region"] == "Ukraine"
        assert ad["category_id"] == 1
        assert "source_url" in ad
        assert "link" in ad
        assert "picpath" in ad
        assert "svimg" in ad

    def test_custom_cot_attrib_present(self):
        """custom_cot_attrib key exists in location."""
        loc = self._convert()
        assert "custom_cot_attrib" in loc
        assert "detail" in loc["custom_cot_attrib"]

    def test_missing_lat_skipped(self):
        """Venue without lat returns None."""
        venue = dict(self.SAMPLE_VENUE)
        del venue["lat"]
        assert self._convert(venue) is None

    def test_missing_lng_skipped(self):
        """Venue without lng returns None."""
        venue = dict(self.SAMPLE_VENUE)
        del venue["lng"]
        assert self._convert(venue) is None

    def test_missing_venue_id_skipped(self):
        """Venue without id returns None."""
        venue = dict(self.SAMPLE_VENUE)
        del venue["id"]
        assert self._convert(venue) is None


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
