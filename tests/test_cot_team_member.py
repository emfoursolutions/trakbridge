"""
ABOUTME: Team member COT generation tests for Phase 3 implementation
ABOUTME: Tests enhanced COT XML generation with team member format compliance
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from lxml import etree
from services.cot_service_integration import QueuedCOTService


class TestTeamMemberCOTGeneration:
    """Test team member COT XML generation functionality"""

    @pytest.mark.asyncio
    async def test_team_member_cot_xml_structure(self):
        """Test that team member COT XML matches specification exactly"""
        # Team member location with metadata in additional_data
        locations = [
            {
                "uid": "ANDROID-c0570d19f0ab169c",
                "name": "Emfour",
                "lat": 27.9637327,
                "lon": 43.571495,
                "altitude": 608.938,
                "accuracy": 9999999,
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Sniper",
                    "team_color": "Green"
                }
            }
        ]

        # Call _create_pytak_events with team member data
        cot_type = "a-f-G-E-V-C"  # Default type, should be overridden
        stale_time = 300

        events = await QueuedCOTService._create_pytak_events(
            locations, cot_type, stale_time
        )

        # Should return one event
        assert len(events) == 1

        # Parse the XML
        event_xml = events[0]
        root = etree.fromstring(event_xml)

        # Verify event element attributes
        assert root.tag == "event"
        assert root.get("version") == "2.0"
        assert root.get("uid") == "ANDROID-c0570d19f0ab169c"
        assert root.get("type") == "a-f-G-U-C"  # Team member CoT type
        assert root.get("how") == "h-e"  # Team member how attribute

        # Verify point element
        point = root.find("point")
        assert point is not None
        assert point.get("lat") == "27.96373270"
        assert point.get("lon") == "43.57149500"
        assert point.get("hae") == "608.94"

        # Verify detail element exists
        detail = root.find("detail")
        assert detail is not None

        # Verify takv element (platform info)
        takv = detail.find("takv")
        assert takv is not None
        assert takv.get("platform") == "TrakBridge"

        # Verify contact element for team members
        contact = detail.find("contact")
        assert contact is not None
        assert contact.get("endpoint") == "*:-1:stcp"
        assert contact.get("callsign") == "Emfour"
        # Team member contact should NOT have xmppUsername
        assert contact.get("xmppUsername") is None

        # Verify uid element for team members
        uid = detail.find("uid")
        assert uid is not None
        assert uid.get("Droid") == "Emfour"

        # Verify __group element for team members
        group = detail.find("__group")
        assert group is not None
        assert group.get("role") == "Sniper"
        assert group.get("name") == "Green"

        # Verify precisionlocation element
        precision = detail.find("precisionlocation")
        assert precision is not None
        assert precision.get("altsrc") == "DTED0"
        assert precision.get("geopointsrc") == "USER"

        # Verify status element (battery)
        status = detail.find("status")
        assert status is not None
        assert status.get("battery") == "49"

        # Verify track element if present
        track = detail.find("track")
        if track is not None:
            assert track.get("speed") == "0.0"

    @pytest.mark.asyncio
    async def test_standard_cot_unchanged_without_team_member(self):
        """Test that standard COT generation is unchanged when no team member data"""
        # Standard location without team member metadata
        locations = [
            {
                "uid": "standard-tracker-123",
                "name": "StandardTracker",
                "lat": 25.1234567,
                "lon": -80.9876543,
                "altitude": 100.0,
                "accuracy": 10.0
            }
        ]

        cot_type = "a-f-G-E-V-C"
        stale_time = 300

        events = await QueuedCOTService._create_pytak_events(
            locations, cot_type, stale_time
        )

        assert len(events) == 1

        # Parse the XML
        event_xml = events[0]
        root = etree.fromstring(event_xml)

        # Should use original COT type, not team member type
        assert root.get("type") == "a-f-G-E-V-C"
        assert root.get("how") == "h-g-i-g-o"  # Standard how attribute

        # Detail should exist but without team member elements
        detail = root.find("detail")
        assert detail is not None

        # Should have contact but without team member specific attributes
        contact = detail.find("contact")
        assert contact is not None
        assert contact.get("callsign") == "StandardTracker"
        # Standard contact should not have the team member endpoint
        assert contact.get("endpoint") != "*:-1:stcp"

        # Should NOT have team member specific elements
        assert detail.find("uid") is None  # No uid Droid element
        assert detail.find("__group") is None  # No group element

    @pytest.mark.asyncio
    async def test_team_member_different_roles_and_colors(self):
        """Test team member COT generation with different roles and colors"""
        test_cases = [
            {"role": "Team Lead", "color": "Red"},
            {"role": "Medic", "color": "Blue"},
            {"role": "RTO", "color": "Yellow"},
            {"role": "K9", "color": "Purple"}
        ]

        for i, case in enumerate(test_cases):
            locations = [
                {
                    "uid": f"team-member-{i}",
                    "name": f"Member{i}",
                    "lat": 30.0 + i,
                    "lon": -90.0 + i,
                    "additional_data": {
                        "team_member_enabled": True,
                        "team_role": case["role"],
                        "team_color": case["color"]
                    }
                }
            ]

            events = await QueuedCOTService._create_pytak_events(
                locations, "a-f-G-E-V-C", 300
            )

            root = etree.fromstring(events[0])

            # Verify team member type
            assert root.get("type") == "a-f-G-U-C"

            # Verify role and color in __group element
            detail = root.find("detail")
            group = detail.find("__group")
            assert group.get("role") == case["role"]
            assert group.get("name") == case["color"]

    @pytest.mark.asyncio
    async def test_mixed_team_member_and_standard_trackers(self):
        """Test processing mixed list of team members and standard trackers"""
        locations = [
            {
                "uid": "team-member-1",
                "name": "TeamMember1",
                "lat": 30.0,
                "lon": -90.0,
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Sniper",
                    "team_color": "Green"
                }
            },
            {
                "uid": "standard-tracker-1",
                "name": "StandardTracker",
                "lat": 31.0,
                "lon": -91.0
            },
            {
                "uid": "team-member-2",
                "name": "TeamMember2",
                "lat": 32.0,
                "lon": -92.0,
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Medic",
                    "team_color": "Red"
                }
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-E-V-C", 300
        )

        assert len(events) == 3

        # Parse and verify each event
        roots = [etree.fromstring(event) for event in events]

        # First event: team member
        assert roots[0].get("type") == "a-f-G-U-C"
        assert roots[0].find("detail").find("__group").get("role") == "Sniper"

        # Second event: standard tracker
        assert roots[1].get("type") == "a-f-G-E-V-C"
        assert roots[1].find("detail").find("__group") is None

        # Third event: team member
        assert roots[2].get("type") == "a-f-G-U-C"
        assert roots[2].find("detail").find("__group").get("role") == "Medic"

    @pytest.mark.asyncio
    async def test_team_member_malformed_data_handling(self):
        """Test error handling for malformed team member data"""
        # Test with team_member_enabled but missing role/color
        locations = [
            {
                "uid": "malformed-team-member",
                "name": "MalformedMember",
                "lat": 30.0,
                "lon": -90.0,
                "additional_data": {
                    "team_member_enabled": True,
                    # Missing team_role and team_color
                }
            }
        ]

        # Should not raise an exception, should handle gracefully
        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-E-V-C", 300
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])

        # Should still generate team member type
        assert root.get("type") == "a-f-G-U-C"

        # Group element should handle missing data gracefully
        detail = root.find("detail")
        group = detail.find("__group")
        assert group is not None
        # Should use empty or default values for missing data
        assert group.get("role") in [None, ""]
        assert group.get("name") in [None, ""]

    @pytest.mark.asyncio
    async def test_team_member_disabled_fallback(self):
        """Test that team_member_enabled=False falls back to standard COT"""
        locations = [
            {
                "uid": "disabled-team-member",
                "name": "DisabledMember",
                "lat": 30.0,
                "lon": -90.0,
                "additional_data": {
                    "team_member_enabled": False,
                    "team_role": "Sniper",
                    "team_color": "Green"
                }
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-E-V-C", 300
        )

        root = etree.fromstring(events[0])

        # Should use standard COT type, not team member
        assert root.get("type") == "a-f-G-E-V-C"

        # Should not have team member elements
        detail = root.find("detail")
        assert detail.find("__group") is None
        assert detail.find("uid") is None