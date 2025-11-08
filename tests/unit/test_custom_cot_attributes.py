"""
ABOUTME: Unit tests for custom CoT XML attributes feature
ABOUTME: Tests plugin ability to add custom elements and attributes to CoT XML
"""

import pytest
from lxml import etree
from services.cot_service_integration import QueuedCOTService


class TestCustomCotAttributes:
    """Test custom CoT attribute application"""

    @pytest.mark.asyncio
    async def test_custom_detail_element_with_text(self):
        """Test adding custom element with text content to detail"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-001",
                "custom_cot_attrib": {
                    "detail": {
                        "__milsym": {"_text": "SFGPUCI-------"}
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")
        milsym = detail.find("__milsym")

        assert milsym is not None
        assert milsym.text == "SFGPUCI-------"

    @pytest.mark.asyncio
    async def test_custom_detail_element_with_subelement(self):
        """Test adding custom element with subelement"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-002",
                "custom_cot_attrib": {
                    "detail": {
                        "usericon": {
                            "iconsetpath": "34ae1613-9645-4222-a9d2-e5f243dea2865/Military/a-u-G.png"
                        }
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")
        usericon = detail.find("usericon")
        iconsetpath = usericon.find("iconsetpath")

        assert usericon is not None
        assert iconsetpath is not None
        assert iconsetpath.text == "34ae1613-9645-4222-a9d2-e5f243dea2865/Military/a-u-G.png"

    @pytest.mark.asyncio
    async def test_custom_event_attributes(self):
        """Test adding custom attributes to event element"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-003",
                "custom_cot_attrib": {
                    "event": {
                        "_attributes": {
                            "access": "Unclassified",
                            "qos": "1-r-c"
                        }
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])

        assert root.get("access") == "Unclassified"
        assert root.get("qos") == "1-r-c"

    @pytest.mark.asyncio
    async def test_multiple_custom_elements(self):
        """Test adding multiple custom elements"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-004",
                "custom_cot_attrib": {
                    "detail": {
                        "__milsym": {"_text": "SFGPUCI-------"},
                        "usericon": {
                            "iconsetpath": "path/to/icon.png"
                        },
                        "custom_data": {"_text": "Custom value"}
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        assert detail.find("__milsym") is not None
        assert detail.find("__milsym").text == "SFGPUCI-------"
        assert detail.find("usericon") is not None
        assert detail.find("usericon").find("iconsetpath") is not None
        assert detail.find("custom_data") is not None
        assert detail.find("custom_data").text == "Custom value"

    @pytest.mark.asyncio
    async def test_custom_element_with_xml_attributes(self):
        """Test custom element with XML attributes"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-005",
                "custom_cot_attrib": {
                    "detail": {
                        "link": {
                            "_attributes": {
                                "uid": "SERVER-001",
                                "production_time": "2025-11-08T10:00:00Z",
                                "type": "a-f-G-E-S",
                                "parent_callsign": "HQ",
                                "relation": "p-p"
                            }
                        }
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")
        link = detail.find("link")

        assert link is not None
        assert link.get("uid") == "SERVER-001"
        assert link.get("production_time") == "2025-11-08T10:00:00Z"
        assert link.get("type") == "a-f-G-E-S"
        assert link.get("parent_callsign") == "HQ"
        assert link.get("relation") == "p-p"

    @pytest.mark.asyncio
    async def test_protected_elements_rejected(self):
        """Test that protected elements cannot be overridden"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-006",
                "custom_cot_attrib": {
                    "detail": {
                        "contact": {"_text": "Should be rejected"},  # Protected
                        "__group": {"_text": "Should be rejected"},  # Protected
                        "custom_element": {"_text": "Should work"}  # Not protected
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        # Protected elements should only exist once (from original generation)
        contact_elements = detail.findall("contact")
        group_elements = detail.findall("__group")

        # Should have at most 1 of each (from original, not from custom)
        assert len(contact_elements) <= 1
        assert len(group_elements) <= 1

        # Custom element should be added
        assert detail.find("custom_element") is not None
        assert detail.find("custom_element").text == "Should work"

    @pytest.mark.asyncio
    async def test_invalid_xml_names_rejected(self):
        """Test that invalid XML element names are rejected"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-007",
                "custom_cot_attrib": {
                    "detail": {
                        "valid_element": {"_text": "Valid"},
                        "123invalid": {"_text": "Should be rejected"},  # Starts with number
                        "invalid element": {"_text": "Should be rejected"},  # Contains space
                        "valid-element-2": {"_text": "Valid"}  # Hyphens OK
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        # Valid elements should be added
        assert detail.find("valid_element") is not None
        assert detail.find("valid-element-2") is not None

        # Invalid elements should not be added
        assert detail.find("123invalid") is None
        assert detail.find("invalid element") is None

    @pytest.mark.asyncio
    async def test_custom_attributes_with_team_member(self):
        """Test custom attributes work with team member CoT"""
        locations = [
            {
                "name": "Team Member",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEAM-001",
                "additional_data": {
                    "team_member_enabled": True,
                    "team_role": "Team Lead",
                    "team_color": "Yellow"
                },
                "custom_cot_attrib": {
                    "detail": {
                        "custom_team_data": {"_text": "Special team info"}
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G-U-C", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        # Verify team member elements exist
        assert detail.find("contact") is not None
        assert detail.find("__group") is not None

        # Verify custom element was added
        assert detail.find("custom_team_data") is not None
        assert detail.find("custom_team_data").text == "Special team info"

    @pytest.mark.asyncio
    async def test_simple_string_value_becomes_text(self):
        """Test that simple string values become element text content"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-008",
                "custom_cot_attrib": {
                    "detail": {
                        "simple_element": "Simple text value"
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")
        simple_elem = detail.find("simple_element")

        assert simple_elem is not None
        assert simple_elem.text == "Simple text value"

    @pytest.mark.asyncio
    async def test_no_custom_attributes_doesnt_break(self):
        """Test that CoT generation works normally without custom attributes"""
        locations = [
            {
                "name": "Test Device",
                "lat": 38.8977,
                "lon": -77.0365,
                "uid": "TEST-009",
                # No custom_cot_attrib
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "a-f-G", 300, "stream"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])

        # Standard elements should exist
        assert root.get("uid") == "TEST-009"
        assert root.find("point") is not None
        assert root.find("detail") is not None
