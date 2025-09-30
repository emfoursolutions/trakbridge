"""
ABOUTME: Plugin integration tests for team member functionality
ABOUTME: Tests enhanced apply_callsign_mapping methods with team member data flow
"""

import pytest
from plugins.garmin_plugin import GarminPlugin
from plugins.traccar_plugin import TraccarPlugin
from plugins.spot_plugin import SpotPlugin


class TestPluginTeamMemberIntegration:
    """Test plugin integration with team member functionality"""

    def setup_method(self):
        """Set up test plugin instance"""
        config = {
            "url": "https://test.example.com/feed.kml",
            "username": "test",
            "password": "test"
        }
        self.plugin = GarminPlugin(config)

    def test_apply_callsign_mapping_adds_team_member_metadata(self):
        """Test that apply_callsign_mapping adds team member metadata to location additional_data"""
        # Sample location data
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "123456789012345"
                        }
                    }
                }
            }
        ]

        # Callsign mapping with team member configuration
        callsign_map = {
            "123456789012345": {
                "custom_callsign": "Alpha1",
                "team_member_enabled": True,
                "team_role": "Sniper",
                "team_color": "Green"
            }
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "Alpha1"

        # Verify team member metadata was added to additional_data
        additional_data = tracker_data[0]["additional_data"]
        assert additional_data["team_member_enabled"] is True
        assert additional_data["team_role"] == "Sniper"
        assert additional_data["team_color"] == "Green"

    def test_apply_callsign_mapping_regular_mapping_no_team_metadata(self):
        """Test that regular callsign mapping doesn't add team member metadata"""
        # Sample location data
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "123456789012345"
                        }
                    }
                }
            }
        ]

        # Regular callsign mapping (no team member data)
        callsign_map = {
            "123456789012345": {
                "custom_callsign": "RegularCallsign"
            }
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "RegularCallsign"

        # Verify no team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert "team_member_enabled" not in additional_data
        assert "team_role" not in additional_data
        assert "team_color" not in additional_data

    def test_apply_callsign_mapping_with_different_team_configurations(self):
        """Test apply_callsign_mapping with different team member configurations"""
        # Sample location data with multiple devices
        tracker_data = [
            {
                "name": "Device1",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "111111111111111"
                        }
                    }
                }
            },
            {
                "name": "Device2",
                "lat": 23.4567,
                "lon": -89.0123,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "222222222222222"
                        }
                    }
                }
            },
            {
                "name": "Device3",
                "lat": 34.5678,
                "lon": -90.1234,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "333333333333333"
                        }
                    }
                }
            }
        ]

        # Mixed callsign mapping with different team configurations
        callsign_map = {
            "111111111111111": {
                "custom_callsign": "TeamLead",
                "team_member_enabled": True,
                "team_role": "Team Lead",
                "team_color": "Blue"
            },
            "222222222222222": {
                "custom_callsign": "Medic",
                "team_member_enabled": True,
                "team_role": "Medic",
                "team_color": "Red"
            },
            "333333333333333": {
                "custom_callsign": "RegularTracker"
                # No team member configuration
            }
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify first device (Team Lead)
        assert tracker_data[0]["name"] == "TeamLead"
        assert tracker_data[0]["additional_data"]["team_member_enabled"] is True
        assert tracker_data[0]["additional_data"]["team_role"] == "Team Lead"
        assert tracker_data[0]["additional_data"]["team_color"] == "Blue"

        # Verify second device (Medic)
        assert tracker_data[1]["name"] == "Medic"
        assert tracker_data[1]["additional_data"]["team_member_enabled"] is True
        assert tracker_data[1]["additional_data"]["team_role"] == "Medic"
        assert tracker_data[1]["additional_data"]["team_color"] == "Red"

        # Verify third device (Regular)
        assert tracker_data[2]["name"] == "RegularTracker"
        assert "team_member_enabled" not in tracker_data[2]["additional_data"]
        assert "team_role" not in tracker_data[2]["additional_data"]
        assert "team_color" not in tracker_data[2]["additional_data"]

    def test_apply_callsign_mapping_backward_compatibility(self):
        """Test that existing plugin behavior is preserved for backward compatibility"""
        # Sample location data
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "123456789012345"
                        }
                    }
                }
            }
        ]

        # Old-style callsign mapping (string value instead of dict)
        callsign_map = {
            "123456789012345": "SimpleCallsign"
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "SimpleCallsign"

        # Verify no team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert "team_member_enabled" not in additional_data
        assert "team_role" not in additional_data
        assert "team_color" not in additional_data

    def test_apply_callsign_mapping_missing_identifier_value(self):
        """Test that plugin handles missing identifier values gracefully"""
        # Sample location data without IMEI
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {}
                    }
                }
            }
        ]

        # Callsign mapping with team member configuration
        callsign_map = {
            "123456789012345": {
                "custom_callsign": "Alpha1",
                "team_member_enabled": True,
                "team_role": "Sniper",
                "team_color": "Green"
            }
        }

        # Apply mapping - should not crash or modify data
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify original name is preserved
        assert tracker_data[0]["name"] == "TestDevice"

        # Verify no team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert "team_member_enabled" not in additional_data
        assert "team_role" not in additional_data
        assert "team_color" not in additional_data

    def test_apply_callsign_mapping_no_matching_mapping(self):
        """Test that plugin handles cases where no matching mapping exists"""
        # Sample location data
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "123456789012345"
                        }
                    }
                }
            }
        ]

        # Callsign mapping for different IMEI
        callsign_map = {
            "999999999999999": {
                "custom_callsign": "Alpha1",
                "team_member_enabled": True,
                "team_role": "Sniper",
                "team_color": "Green"
            }
        }

        # Apply mapping - should not modify data
        self.plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

        # Verify original name is preserved
        assert tracker_data[0]["name"] == "TestDevice"

        # Verify no team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert "team_member_enabled" not in additional_data
        assert "team_role" not in additional_data
        assert "team_color" not in additional_data


class TestBasePluginTeamMemberIntegration:
    """Test base plugin apply_callsign_mappings wrapper with team member data"""

    def setup_method(self):
        """Set up test plugin instance"""
        config = {
            "url": "https://test.example.com/feed.kml",
            "username": "test",
            "password": "test"
        }
        self.plugin = GarminPlugin(config)

    def test_apply_callsign_mappings_wrapper_with_team_member_data(self):
        """Test that apply_callsign_mappings wrapper preserves team member functionality"""
        # Sample location data
        tracker_data = [
            {
                "name": "TestDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_placemark": {
                        "extended_data": {
                            "IMEI": "123456789012345"
                        }
                    }
                }
            }
        ]

        # Callsign mapping with team member configuration
        callsign_map = {
            "123456789012345": {
                "custom_callsign": "Alpha1",
                "team_member_enabled": True,
                "team_role": "Sniper",
                "team_color": "Green"
            }
        }

        # Apply mapping using wrapper method
        result = self.plugin.apply_callsign_mappings(tracker_data, "imei", callsign_map)

        # Verify mapping was applied
        assert result is True

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "Alpha1"

        # Verify team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert additional_data["team_member_enabled"] is True
        assert additional_data["team_role"] == "Sniper"
        assert additional_data["team_color"] == "Green"


class TestTraccarPluginTeamMemberIntegration:
    """Test Traccar plugin integration with team member functionality"""

    def setup_method(self):
        """Set up test plugin instance"""
        config = {
            "server_url": "https://test.traccar.example.com",
            "username": "test",
            "password": "test"
        }
        self.plugin = TraccarPlugin(config)

    def test_traccar_apply_callsign_mapping_adds_team_member_metadata(self):
        """Test that Traccar plugin applies team member metadata correctly"""
        # Sample Traccar location data
        tracker_data = [
            {
                "name": "TestTraccarDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "device_info": {
                        "uniqueId": "traccar123456"
                    }
                }
            }
        ]

        # Callsign mapping with team member configuration
        callsign_map = {
            "traccar123456": {
                "custom_callsign": "TraccarTeam1",
                "team_member_enabled": True,
                "team_role": "Team Lead",
                "team_color": "Blue"
            }
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "unique_id", callsign_map)

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "TraccarTeam1"

        # Verify team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert additional_data["team_member_enabled"] is True
        assert additional_data["team_role"] == "Team Lead"
        assert additional_data["team_color"] == "Blue"


class TestSpotPluginTeamMemberIntegration:
    """Test SPOT plugin integration with team member functionality"""

    def setup_method(self):
        """Set up test plugin instance"""
        config = {
            "feed_id": "test_feed",
            "feed_password": "test_password"
        }
        self.plugin = SpotPlugin(config)

    def test_spot_apply_callsign_mapping_adds_team_member_metadata(self):
        """Test that SPOT plugin applies team member metadata correctly"""
        # Sample SPOT location data
        tracker_data = [
            {
                "name": "TestSpotDevice",
                "lat": 12.3456,
                "lon": -78.9012,
                "additional_data": {
                    "raw_message": {
                        "id": "spot123456"
                    }
                }
            }
        ]

        # Callsign mapping with team member configuration
        callsign_map = {
            "spot123456": {
                "custom_callsign": "SpotTeam1",
                "team_member_enabled": True,
                "team_role": "Forward Observer",
                "team_color": "Yellow"
            }
        }

        # Apply mapping
        self.plugin.apply_callsign_mapping(tracker_data, "device_id", callsign_map)

        # Verify callsign was applied
        assert tracker_data[0]["name"] == "SpotTeam1"

        # Verify team member metadata was added
        additional_data = tracker_data[0]["additional_data"]
        assert additional_data["team_member_enabled"] is True
        assert additional_data["team_role"] == "Forward Observer"
        assert additional_data["team_color"] == "Yellow"