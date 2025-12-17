# ABOUTME: Unit tests for IRC handler message filtering and template formatting
# ABOUTME: Tests CoT pattern matching, template variable extraction, and message rule matching

import pytest
from unittest.mock import MagicMock
from plugins.irc_handler import IRCHandler
from defusedxml import ElementTree as DefusedET


class TestIRCHandlerFiltering:
    """Test IRC handler filtering and template logic"""

    def setup_method(self):
        """Set up test fixtures"""
        self.base_config = {
            "server": "irc.test.com",
            "port": 6667,
            "use_ssl": "false",
            "nickname": "TestBot",
            "channel": "#test",
            "uid_filter": "",
            "message_rules": [],
        }

    def test_matches_cot_pattern_exact(self):
        """Test exact CoT pattern matching"""
        handler = IRCHandler(self.base_config)

        assert handler._matches_cot_pattern("b-t-f", "b-t-f") is True
        assert handler._matches_cot_pattern("b-t-f", "b-a-o") is False
        assert handler._matches_cot_pattern("b-t-f-chat", "b-t-f") is False

    def test_matches_cot_pattern_wildcard(self):
        """Test wildcard CoT pattern matching"""
        handler = IRCHandler(self.base_config)

        assert handler._matches_cot_pattern("b-t-f", "b-t-*") is True
        assert handler._matches_cot_pattern("b-t-f-chat", "b-t-*") is True
        assert handler._matches_cot_pattern("b-a-o", "b-t-*") is False
        assert handler._matches_cot_pattern("b-a-o-can", "b-a-*") is True
        assert handler._matches_cot_pattern("a-f-G-E-V", "a-*") is True

    def test_extract_template_variables_basic(self):
        """Test basic template variable extraction"""
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-UID" type="b-t-f" time="2024-01-01T12:00:00Z" start="2024-01-01T12:00:00Z" stale="2024-01-01T12:05:00Z">
            <point lat="40.7128" lon="-74.0060" hae="10.0" ce="9999999.0" le="9999999.0" />
            <detail>
                <contact callsign="TestUser"/>
                <remarks>Hello World</remarks>
            </detail>
        </event>"""

        root = DefusedET.fromstring(cot_xml)
        handler = IRCHandler(self.base_config)
        variables = handler._extract_template_variables(root)

        assert variables["type"] == "b-t-f"
        assert variables["uid"] == "TEST-UID"
        assert variables["callsign"] == "TestUser"
        assert variables["lat"] == "40.7128"
        assert variables["lon"] == "-74.0060"
        assert variables["hae"] == "10.0"
        assert variables["remarks"] == "Hello World"
        assert variables["time"] == "2024-01-01T12:00:00Z"
        assert variables["stale"] == "2024-01-01T12:05:00Z"

    def test_extract_template_variables_missing_fields(self):
        """Test template variable extraction with missing fields"""
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-UID" type="b-a-o">
            <point lat="40.7128" lon="-74.0060" />
        </event>"""

        root = DefusedET.fromstring(cot_xml)
        handler = IRCHandler(self.base_config)
        variables = handler._extract_template_variables(root)

        assert variables["type"] == "b-a-o"
        assert variables["uid"] == "TEST-UID"
        assert variables["callsign"] == "Unknown"
        assert variables["remarks"] == ""
        assert variables["time"] == ""
        assert variables["stale"] == ""

    def test_format_message_basic(self):
        """Test basic message formatting"""
        handler = IRCHandler(self.base_config)
        variables = {
            "type": "b-t-f",
            "callsign": "TestUser",
            "remarks": "Hello World",
            "lat": "40.7128",
            "lon": "-74.0060",
        }

        template = "[CHAT] {callsign}: {remarks}"
        result = handler._format_message(template, variables)
        assert result == "[CHAT] TestUser: Hello World"

        template = "[ALERT] {callsign} at {lat},{lon}"
        result = handler._format_message(template, variables)
        assert result == "[ALERT] TestUser at 40.7128,-74.0060"

    def test_format_message_missing_variable(self):
        """Test message formatting with missing variable"""
        handler = IRCHandler(self.base_config)
        variables = {"callsign": "TestUser"}

        template = "[CHAT] {callsign}: {remarks}"
        result = handler._format_message(template, variables)
        assert "[ERROR: missing variable" in result
        assert "'remarks'" in result

    def test_should_handle_no_rules(self):
        """Test that no messages are handled when no rules configured"""
        handler = IRCHandler(self.base_config)

        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is False
        assert template == ""

    def test_should_handle_matching_rule(self):
        """Test message handling with matching rule"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is True
        assert template == "[CHAT] {callsign}: {remarks}"

    def test_should_handle_wildcard_rule(self):
        """Test message handling with wildcard rule"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-a-*",
                "format_template": "[ALERT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        should_handle, template = handler._should_handle("b-a-o-can", "TEST-UID")
        assert should_handle is True
        assert template == "[ALERT] {callsign}"

        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is False

    def test_should_handle_disabled_rule(self):
        """Test that disabled rules are skipped"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": False,
            }
        ]
        handler = IRCHandler(config)

        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is False

    def test_should_handle_first_match_wins(self):
        """Test that first matching rule wins"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-*",
                "format_template": "Template 1",
                "enabled": True,
            },
            {
                "id": "rule-2",
                "cot_type_pattern": "b-t-f",
                "format_template": "Template 2",
                "enabled": True,
            },
        ]
        handler = IRCHandler(config)

        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is True
        assert template == "Template 1"  # First rule matches

    def test_should_handle_uid_filter(self):
        """Test UID filtering"""
        config = self.base_config.copy()
        config["uid_filter"] = "^ANDROID-.*"
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # Matching UID
        should_handle, template = handler._should_handle("b-t-f", "ANDROID-123")
        assert should_handle is True

        # Non-matching UID
        should_handle, template = handler._should_handle("b-t-f", "IOS-456")
        assert should_handle is False

    def test_should_handle_multiple_rules(self):
        """Test with multiple rules"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            },
            {
                "id": "rule-2",
                "cot_type_pattern": "b-a-*",
                "format_template": "[ALERT] {callsign} at {lat},{lon}",
                "enabled": True,
            },
            {
                "id": "rule-3",
                "cot_type_pattern": "a-f-*",
                "format_template": "[FRIENDLY] {callsign}",
                "enabled": True,
            },
        ]
        handler = IRCHandler(config)

        # Test each rule
        should_handle, template = handler._should_handle("b-t-f", "TEST-UID")
        assert should_handle is True
        assert template == "[CHAT] {callsign}: {remarks}"

        should_handle, template = handler._should_handle("b-a-o", "TEST-UID")
        assert should_handle is True
        assert template == "[ALERT] {callsign} at {lat},{lon}"

        should_handle, template = handler._should_handle("a-f-G-E-V", "TEST-UID")
        assert should_handle is True
        assert template == "[FRIENDLY] {callsign}"

        # Non-matching type
        should_handle, template = handler._should_handle("x-unknown", "TEST-UID")
        assert should_handle is False

    def test_extract_template_variables_extended(self):
        """Test extraction of extended template variables (group, battery, device, track, etc.)"""
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="ANDROID-c0570d19f0ab169c" type="a-f-G-U-C" how="h-g-i-g-o" time="2025-12-17T15:10:13Z" start="2025-12-17T15:10:12Z" stale="2025-12-17T15:16:27Z" access="Undefined">
            <point lat="0.0" lon="0.0" hae="9999999.0" ce="9999999.0" le="9999999.0"/>
            <detail>
                <__group name="Blue" role="Team Member"/>
                <status battery="16"/>
                <takv device="SAMSUNG SM-G990E" platform="ATAK-CIV" os="36" version="5.4.0.16 (55e727de)[playstore].1750199949-CIV"/>
                <track speed="0.0" course="18.9555897703694"/>
                <contact xmppUsername="ops_npoulter@xmpp.plexus-isr.com" endpoint="*:-1:stcp" callsign="Emfour"/>
                <uid Droid="Emfour"/>
            </detail>
        </event>"""

        root = DefusedET.fromstring(cot_xml)
        handler = IRCHandler(self.base_config)
        variables = handler._extract_template_variables(root)

        # Basic fields
        assert variables["type"] == "a-f-G-U-C"
        assert variables["uid"] == "ANDROID-c0570d19f0ab169c"
        assert variables["callsign"] == "Emfour"

        # Extended fields
        assert variables["group_name"] == "Blue"
        assert variables["group_role"] == "Team Member"
        assert variables["battery"] == "16"
        assert variables["device"] == "SAMSUNG SM-G990E"
        assert variables["platform"] == "ATAK-CIV"
        assert variables["os"] == "36"
        assert variables["version"] == "5.4.0.16 (55e727de)[playstore].1750199949-CIV"
        assert variables["speed"] == "0.0"
        assert variables["course"] == "18.9555897703694"
        assert variables["xmpp_username"] == "ops_npoulter@xmpp.plexus-isr.com"

    def test_is_within_geofence_inside(self):
        """Test geofence check for coordinates inside bounds"""
        handler = IRCHandler(self.base_config)
        bounds = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}

        # Inside bounds
        assert handler._is_within_geofence("40.7", "-74.0", bounds) is True
        assert handler._is_within_geofence("40.75", "-73.95", bounds) is True
        assert handler._is_within_geofence("40.65", "-74.05", bounds) is True

        # On the boundary (should be inside)
        assert handler._is_within_geofence("40.8", "-74.0", bounds) is True
        assert handler._is_within_geofence("40.6", "-73.9", bounds) is True

    def test_is_within_geofence_outside(self):
        """Test geofence check for coordinates outside bounds"""
        handler = IRCHandler(self.base_config)
        bounds = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}

        # Outside bounds
        assert handler._is_within_geofence("40.9", "-74.0", bounds) is False  # North
        assert handler._is_within_geofence("40.5", "-74.0", bounds) is False  # South
        assert handler._is_within_geofence("40.7", "-73.8", bounds) is False  # East
        assert handler._is_within_geofence("40.7", "-74.2", bounds) is False  # West

    def test_is_within_geofence_invalid_coords(self):
        """Test geofence check with invalid coordinates (fail open)"""
        handler = IRCHandler(self.base_config)
        bounds = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}

        # Invalid coordinates should fail open (return True)
        assert handler._is_within_geofence("invalid", "-74.0", bounds) is True
        assert handler._is_within_geofence("40.7", "invalid", bounds) is True
        assert handler._is_within_geofence("", "", bounds) is True

    def test_is_within_geofence_invalid_bounds(self):
        """Test geofence check with invalid bounds (fail open)"""
        handler = IRCHandler(self.base_config)

        # Invalid bounds should fail open (return True)
        assert handler._is_within_geofence("40.7", "-74.0", {}) is True
        assert handler._is_within_geofence("40.7", "-74.0", {"north": "invalid"}) is True

    def test_should_handle_global_geofence_disabled(self):
        """Test that geofence filtering is skipped when disabled"""
        config = self.base_config.copy()
        config["global_geofence_enabled"] = "false"
        config["global_geofence_bounds"] = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # Should pass even though outside geofence (geofence disabled)
        should_handle, template = handler._should_handle("b-t-f", "TEST-UID", "50.0", "-100.0")
        assert should_handle is True

    def test_should_handle_global_geofence_inside(self):
        """Test that messages inside geofence are handled"""
        config = self.base_config.copy()
        config["global_geofence_enabled"] = "true"
        config["global_geofence_bounds"] = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # Inside geofence
        should_handle, template = handler._should_handle("b-t-f", "TEST-UID", "40.7", "-74.0")
        assert should_handle is True
        assert template == "[CHAT] {callsign}"

    def test_should_handle_global_geofence_outside(self):
        """Test that messages outside geofence are filtered"""
        config = self.base_config.copy()
        config["global_geofence_enabled"] = "true"
        config["global_geofence_bounds"] = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # Outside geofence
        should_handle, template = handler._should_handle("b-t-f", "TEST-UID", "50.0", "-100.0")
        assert should_handle is False
        assert template == ""

    def test_should_handle_global_geofence_no_coordinates(self):
        """Test that messages without coordinates pass geofence check (fail open)"""
        config = self.base_config.copy()
        config["global_geofence_enabled"] = "true"
        config["global_geofence_bounds"] = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # No coordinates - should pass (fail open)
        should_handle, template = handler._should_handle("b-t-f", "TEST-UID", "", "")
        assert should_handle is True

    def test_should_handle_global_geofence_combined_filters(self):
        """Test global geofence combined with UID filter and message rules"""
        config = self.base_config.copy()
        config["uid_filter"] = "^ANDROID-.*"
        config["global_geofence_enabled"] = "true"
        config["global_geofence_bounds"] = {"north": 40.8, "south": 40.6, "east": -73.9, "west": -74.1}
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]
        handler = IRCHandler(config)

        # All filters pass
        should_handle, template = handler._should_handle("b-t-f", "ANDROID-123", "40.7", "-74.0")
        assert should_handle is True

        # UID filter fails
        should_handle, template = handler._should_handle("b-t-f", "IOS-456", "40.7", "-74.0")
        assert should_handle is False

        # Geofence filter fails
        should_handle, template = handler._should_handle("b-t-f", "ANDROID-123", "50.0", "-100.0")
        assert should_handle is False

        # Message rule fails
        should_handle, template = handler._should_handle("b-a-o", "ANDROID-123", "40.7", "-74.0")
        assert should_handle is False
