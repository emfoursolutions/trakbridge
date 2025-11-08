"""
ABOUTME: Unit tests for dynamic battery state implementation
ABOUTME: Tests battery mapping in plugins and COT XML generation
"""

import pytest
from lxml import etree
from plugins.spot_plugin import SpotPlugin
from services.cot_service_integration import QueuedCOTService


class TestSpotBatteryMapping:
    """Test SPOT plugin battery state mapping"""

    def test_battery_mapping_good(self):
        """Test SPOT battery 'GOOD' maps to 100"""
        result = SpotPlugin._map_battery_state("GOOD")
        assert result == 100

    def test_battery_mapping_low(self):
        """Test SPOT battery 'LOW' maps to 20"""
        result = SpotPlugin._map_battery_state("LOW")
        assert result == 20

    def test_battery_mapping_case_insensitive(self):
        """Test battery mapping is case-insensitive"""
        assert SpotPlugin._map_battery_state("good") == 100
        assert SpotPlugin._map_battery_state("Good") == 100
        assert SpotPlugin._map_battery_state("GOOD") == 100
        assert SpotPlugin._map_battery_state("low") == 20
        assert SpotPlugin._map_battery_state("Low") == 20
        assert SpotPlugin._map_battery_state("LOW") == 20

    def test_battery_mapping_unknown_state(self):
        """Test unknown battery states default to 100"""
        assert SpotPlugin._map_battery_state("UNKNOWN") == 100
        assert SpotPlugin._map_battery_state("MEDIUM") == 100
        assert SpotPlugin._map_battery_state("") == 100

    def test_battery_mapping_none(self):
        """Test None battery state defaults to 100"""
        assert SpotPlugin._map_battery_state(None) == 100


class TestCOTBatteryGeneration:
    """Test COT XML generation with battery values"""

    @pytest.mark.asyncio
    async def test_cot_default_battery_100(self):
        """Test COT XML uses default battery value of 100 when no battery data"""
        locations = [
            {
                "name": "Test Tracker",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-001",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Lead",
                    "team_color": "Yellow",
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        status = root.find(".//status")
        assert status is not None
        assert status.get("battery") == "100"

    @pytest.mark.asyncio
    async def test_cot_battery_from_plugin_good(self):
        """Test COT XML uses battery value from plugin (GOOD=100)"""
        locations = [
            {
                "name": "SPOT Tracker",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "SPOT-001",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Member",
                    "team_color": "Blue",
                    "battery_state": 100,  # Already mapped by plugin
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        status = root.find(".//status")
        assert status is not None
        assert status.get("battery") == "100"

    @pytest.mark.asyncio
    async def test_cot_battery_from_plugin_low(self):
        """Test COT XML uses battery value from plugin (LOW=20)"""
        locations = [
            {
                "name": "SPOT Tracker Low Battery",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "SPOT-002",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Member",
                    "team_color": "Red",
                    "battery_state": 20,  # Already mapped by plugin
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        status = root.find(".//status")
        assert status is not None
        assert status.get("battery") == "20"

    @pytest.mark.asyncio
    async def test_cot_battery_invalid_value_defaults_to_100(self):
        """Test COT XML defaults to 100 for invalid battery values"""
        locations = [
            {
                "name": "Test Tracker Invalid Battery",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-003",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Member",
                    "team_color": "Green",
                    "battery_state": "not_a_number",  # Invalid value
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        status = root.find(".//status")
        assert status is not None
        assert status.get("battery") == "100"  # Should default to 100

    @pytest.mark.asyncio
    async def test_cot_battery_mixed_trackers(self):
        """Test COT XML with mixed battery values"""
        locations = [
            {
                "name": "Tracker With Battery",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-004",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Lead",
                    "team_color": "Yellow",
                    "battery_state": 75,
                },
            },
            {
                "name": "Tracker Without Battery",
                "lat": 38.8978,
                "lon": -77.0366,
                "uid": "TEST-005",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Member",
                    "team_color": "Blue",
                },
            },
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 2

        # First tracker should have battery from plugin
        root1 = etree.fromstring(events[0])
        status1 = root1.find(".//status")
        assert status1 is not None
        assert status1.get("battery") == "75"

        # Second tracker should default to 100
        root2 = etree.fromstring(events[1])
        status2 = root2.find(".//status")
        assert status2 is not None
        assert status2.get("battery") == "100"
