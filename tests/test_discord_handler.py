# ABOUTME: Comprehensive unit tests for Discord handler plugin
# ABOUTME: Tests color-coded embeds and rich field formatting

import pytest
from plugins.discord_handler import DiscordHandler


class TestDiscordHandlerColorMapping:
    """Test Phase 5: Color-coded embeds"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_emergency_alert_color(self):
        """Emergency alerts should be RED"""
        assert (
            self.handler._get_embed_color_for_cot_type("b-a-o-tl")
            == 15548997
        )
        assert self.handler._get_embed_color_for_cot_type("b-a-g") == 15548997

    def test_friendly_position_color(self):
        """Friendly positions should be GREEN"""
        assert (
            self.handler._get_embed_color_for_cot_type("a-f-G-E-V")
            == 5763719
        )
        assert self.handler._get_embed_color_for_cot_type("a-f-A") == 5763719

    def test_hostile_contact_color(self):
        """Hostile contacts should be RED"""
        assert self.handler._get_embed_color_for_cot_type("a-h-G") == 15548997
        assert self.handler._get_embed_color_for_cot_type("a-h-A") == 15548997

    def test_neutral_contact_color(self):
        """Neutral contacts should be YELLOW"""
        assert self.handler._get_embed_color_for_cot_type("a-n-G") == 16705372

    def test_unknown_contact_color(self):
        """Unknown contacts should be GREY"""
        assert self.handler._get_embed_color_for_cot_type("a-u-G") == 10070709

    def test_chat_message_color(self):
        """Chat messages should be BLURPLE"""
        assert self.handler._get_embed_color_for_cot_type("b-t-f") == 5793266

    def test_default_color(self):
        """Unknown types should default to WHITE"""
        assert self.handler._get_embed_color_for_cot_type("x-y-z") == 16777215


class TestDiscordHandlerEmbedTitles:
    """Test Phase 6: Embed title generation"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_emergency_title(self):
        result = self.handler._get_embed_title("b-a-o-tl", {})
        assert result == "🚨 Emergency Alert"

    def test_chat_title(self):
        result = self.handler._get_embed_title("b-t-f", {})
        assert result == "💬 Chat Message"

    def test_friendly_title(self):
        result = self.handler._get_embed_title("a-f-G-E-V", {})
        assert result == "🟢 Friendly Position"

    def test_hostile_title(self):
        result = self.handler._get_embed_title("a-h-G", {})
        assert result == "🔴 Hostile Contact"

    def test_default_title(self):
        result = self.handler._get_embed_title("x-y-z", {})
        assert result == "📡 TAK Update"


class TestDiscordHandlerRichEmbeds:
    """Test Phase 6: Rich embed building"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_build_embed_with_all_fields(self):
        """Test embed with all possible fields"""
        variables = {
            "type": "a-f-G-E-V",
            "callsign": "Bravo-6",
            "mgrs": "38TQM 12345 67890",
            "battery": "75",
            "group_name": "Team Alpha",
            "group_role": "Leader",
            "remarks": "En route to checkpoint",
            "device": "ATAK",
            "platform": "Android",
        }

        embed = self.handler._build_rich_embed("a-f-G-E-V", variables)

        assert embed["title"] == "🟢 Friendly Position"
        assert embed["description"] == "**Bravo-6**"
        assert embed["color"] == 5763719
        assert len(embed["fields"]) == 5
        assert "timestamp" in embed

    def test_build_embed_location_field(self):
        """Location field should show MGRS coordinates"""
        variables = {"callsign": "Test", "mgrs": "38TQM 12345 67890"}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        location_field = next(
            f for f in embed["fields"] if f["name"] == "📍 Location"
        )
        assert location_field["value"] == "38TQM 12345 67890"
        assert location_field["inline"] is True

    def test_build_embed_battery_field(self):
        """Battery field should show percentage"""
        variables = {"callsign": "Test", "battery": "85"}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        battery_field = next(
            f for f in embed["fields"] if f["name"] == "🔋 Battery"
        )
        assert battery_field["value"] == "85%"
        assert battery_field["inline"] is True

    def test_build_embed_group_field_with_role(self):
        """Group field should combine name and role"""
        variables = {
            "callsign": "Test",
            "group_name": "Team Alpha",
            "group_role": "Leader",
        }
        embed = self.handler._build_rich_embed("a-f-G", variables)

        group_field = next(
            f for f in embed["fields"] if f["name"] == "👥 Group"
        )
        assert group_field["value"] == "Team Alpha (Leader)"
        assert group_field["inline"] is True

    def test_build_embed_group_field_without_role(self):
        """Group field should work without role"""
        variables = {"callsign": "Test", "group_name": "Team Alpha"}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        group_field = next(
            f for f in embed["fields"] if f["name"] == "👥 Group"
        )
        assert group_field["value"] == "Team Alpha"

    def test_build_embed_remarks_field_not_inline(self):
        """Remarks field should not be inline for long text"""
        variables = {"callsign": "Test", "remarks": "This is a test message"}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        remarks_field = next(
            f for f in embed["fields"] if f["name"] == "💬 Message"
        )
        assert remarks_field["value"] == "This is a test message"
        assert remarks_field["inline"] is False

    def test_build_embed_device_field_with_platform(self):
        """Device field should combine device and platform"""
        variables = {
            "callsign": "Test",
            "device": "ATAK",
            "platform": "Android",
        }
        embed = self.handler._build_rich_embed("a-f-G", variables)

        device_field = next(
            f for f in embed["fields"] if f["name"] == "📱 Device"
        )
        assert device_field["value"] == "ATAK (Android)"
        assert device_field["inline"] is True

    def test_build_embed_missing_fields_skipped(self):
        """Missing optional fields should be skipped"""
        variables = {"callsign": "Test"}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        # Should have no fields since all are optional
        assert len(embed["fields"]) == 0


class TestDiscordHandlerFilteringLogic:
    """Test message filtering and pattern matching"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_exact_cot_pattern_match(self):
        """Exact CoT type patterns should match"""
        assert self.handler._matches_cot_pattern("b-t-f", "b-t-f")
        assert not self.handler._matches_cot_pattern("b-t-f", "a-f-G")

    def test_wildcard_cot_pattern_match(self):
        """Wildcard patterns should match prefix"""
        assert self.handler._matches_cot_pattern("a-f-G-E-V", "a-f-*")
        assert self.handler._matches_cot_pattern("a-f-A", "a-f-*")
        assert not self.handler._matches_cot_pattern("a-h-G", "a-f-*")

    def test_geofence_within_bounds(self):
        """Coordinates within geofence should pass"""
        bounds = {"north": 40, "south": 38, "east": -76, "west": -78}
        assert self.handler._is_within_geofence("39", "-77", bounds)

    def test_geofence_outside_bounds(self):
        """Coordinates outside geofence should fail"""
        bounds = {"north": 40, "south": 38, "east": -76, "west": -78}
        assert not self.handler._is_within_geofence("41", "-77", bounds)
        assert not self.handler._is_within_geofence("39", "-79", bounds)

    def test_geofence_invalid_coords_fail_open(self):
        """Invalid coordinates should fail open (allow)"""
        bounds = {"north": 40, "south": 38, "east": -76, "west": -78}
        assert self.handler._is_within_geofence("invalid", "-77", bounds)


class TestDiscordHandlerTemplateFormatting:
    """Test template variable formatting"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_format_message_with_valid_variables(self):
        """Template formatting with all variables present"""
        template = "[{group_name}] {callsign}: Battery {battery}%"
        variables = {
            "group_name": "Team Alpha",
            "callsign": "Bravo-6",
            "battery": "75",
        }
        result = self.handler._format_message(template, variables)
        assert result == "[Team Alpha] Bravo-6: Battery 75%"

    def test_format_message_with_missing_variable(self):
        """Missing variable should show error in output"""
        template = "{callsign} at {missing_var}"
        variables = {"callsign": "Bravo-6"}
        result = self.handler._format_message(template, variables)
        assert "ERROR" in result
        assert "missing" in result.lower()


class TestDiscordHandlerEdgeCases:
    """Test edge cases and error handling"""

    def setup_method(self):
        self.handler = DiscordHandler({})

    def test_embed_with_empty_callsign(self):
        """Embed should handle missing callsign gracefully"""
        variables = {"callsign": "Unknown"}
        embed = self.handler._build_rich_embed("a-f-G", variables)
        assert embed["description"] == "**Unknown**"

    def test_very_long_remarks(self):
        """Very long remarks should be included in embed"""
        long_text = "A" * 500
        variables = {"callsign": "Test", "remarks": long_text}
        embed = self.handler._build_rich_embed("a-f-G", variables)

        remarks_field = next(
            f for f in embed["fields"] if f["name"] == "💬 Message"
        )
        assert remarks_field["value"] == long_text

    def test_plugin_name_property(self):
        """Plugin name should be discord_handler"""
        assert self.handler.plugin_name == "discord_handler"

    def test_plugin_metadata_structure(self):
        """Plugin metadata should have required fields"""
        metadata = self.handler.plugin_metadata
        assert metadata["display_name"] == "Discord CoT Handler"
        assert metadata["category"] == "output"
        assert metadata["icon"] == "fa-discord"
        assert "config_fields" in metadata
        assert "custom_components" in metadata
        assert "help_sections" in metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
