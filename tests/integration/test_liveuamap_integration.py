# ABOUTME: Integration and E2E tests for LiveUAMap plugin
# ABOUTME: Tests config extraction, serialization, fetch, CoT XML

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from lxml import etree

from plugins.liveuamap_plugin import LiveuamapPlugin
from plugins.plugin_manager import get_plugin_manager
from services.cot_service_integration import QueuedCOTService
from services.stream_config_service import StreamConfigService


# ---------------------------------------------------------------------------
# Phase 6: Config extraction tests
# ---------------------------------------------------------------------------


class TestLiveuamapConfigExtraction:
    """Test that regions JSON field is properly parsed from request data."""

    def setup_method(self):
        """Set up plugin manager and config service for each test."""
        self.plugin_manager = get_plugin_manager()
        self.config_service = StreamConfigService(self.plugin_manager)

    def test_regions_json_parsed_from_request(self):
        """Verify plugin_regions='[0,3,66]' is parsed."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "[0,3,66]",
        }
        plugin_config = (
            self.config_service
            .extract_plugin_config_from_request(data)
        )
        assert plugin_config["regions"] == [0, 3, 66]

    def test_regions_empty_string_defaults_to_empty_list(self):
        """plugin_regions='' should default to []."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "",
        }
        plugin_config = (
            self.config_service
            .extract_plugin_config_from_request(data)
        )
        assert plugin_config["regions"] == []

    def test_regions_invalid_json_defaults_to_empty_list(self):
        """plugin_regions='not json' should default to []."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "not json",
        }
        plugin_config = (
            self.config_service
            .extract_plugin_config_from_request(data)
        )
        assert plugin_config["regions"] == []


# ---------------------------------------------------------------------------
# Phase 8.1: Integration tests
# ---------------------------------------------------------------------------

# Sample venue matching real API response structure
SAMPLE_VENUE = {
    "id": 12345,
    "name": "Explosion reported in Dnipro",
    "lat": 48.4647,
    "lng": 35.0462,
    "timestamp": 1709553600,
    "location": "Dnipro, Dnipropetrovsk Oblast",
    "picpath": "https://a.liveuamap.com/images/is14/explode_red.png",
    "category_id": 1,
    "source_url": "https://example.com/source",
    "link": "/en/2024/1-explosion-dnipro",
    "svimg": "https://a.liveuamap.com/images/svimg/12345.jpg",
}


class TestLiveuamapMetadataSerialization:
    """Test that all config fields and metadata serialize to JSON correctly."""

    def test_plugin_metadata_serialization(self):
        """All config fields serialize to JSON via to_dict()."""
        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        metadata = plugin.plugin_metadata

        for field in metadata["config_fields"]:
            field_dict = field.to_dict()
            # Must be JSON-serializable
            serialized = json.dumps(field_dict)
            assert serialized
            # Round-trip must preserve values
            deserialized = json.loads(serialized)
            assert deserialized["name"] == field.name
            assert deserialized["type"] == field.field_type

    def test_custom_component_serialization(self):
        """Region selector component serializes correctly."""
        plugin = LiveuamapPlugin({"api_key": "test", "regions": "[0]"})
        metadata = plugin.plugin_metadata
        components = metadata.get("custom_components", [])

        assert len(components) >= 1
        component = components[0]
        comp_dict = component.to_dict()

        # Must be JSON-serializable
        serialized = json.dumps(comp_dict)
        assert serialized

        deserialized = json.loads(serialized)
        assert deserialized["type"] == "grouped_multi_select"
        assert deserialized["field_name"] == "regions"
        assert deserialized["title"] == "Select Regions"
        assert "items" in deserialized["config"]
        assert "groups" in deserialized["config"]

        # items should contain all REGIONS
        items_count = len(deserialized["config"]["items"])
        assert items_count == len(LiveuamapPlugin.REGIONS)


class TestLiveuamapFullFetchIntegration:
    """End-to-end fetch_locations() with mocked HTTP."""

    def _make_plugin(self, config_overrides=None):
        config = {
            "api_key": "test-key-123",
            "regions": "[0, 3]",
            "count": "10",
            "timeout": "30",
            "action": "mpts",
            "event_time": "",
        }
        if config_overrides:
            config.update(config_overrides)
        return LiveuamapPlugin(config)

    def _mock_response(self, json_data=None, status=200):
        """Create a mock aiohttp response."""
        resp = AsyncMock()
        resp.status = status
        resp.json = AsyncMock(
            return_value=json_data
            if json_data is not None
            else {"success": True, "venues": []}
        )
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_full_fetch_with_mocked_http(self):
        """Full fetch with mocked aiohttp, verify structure."""
        plugin = self._make_plugin(config_overrides={"regions": "[0]"})

        mock_resp = self._mock_response(
            json_data={"success": True, "venues": [SAMPLE_VENUE]}
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        locations = await plugin.fetch_locations(mock_session)

        assert len(locations) == 1
        loc = locations[0]

        # Standard location fields
        assert loc["uid"] == "liveuamap-12345"
        assert loc["lat"] == 48.4647
        assert loc["lon"] == 35.0462
        assert loc["cot_type"] == "b-m-p-s-m"
        assert "Dnipro" in loc["name"]
        assert "LiveUAMap" in loc["description"]

        # Additional data fields
        ad = loc["additional_data"]
        assert ad["source"] == "liveuamap"
        assert ad["event_id"] == 12345
        assert ad["region"] == "Ukraine"

    @pytest.mark.asyncio
    async def test_custom_cot_attrib_in_location_output(self):
        """Verify custom_cot_attrib flows through."""
        plugin = self._make_plugin(config_overrides={"regions": "[0]"})

        mock_resp = self._mock_response(
            json_data={"success": True, "venues": [SAMPLE_VENUE]}
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        locations = await plugin.fetch_locations(mock_session)

        assert len(locations) == 1
        loc = locations[0]

        # custom_cot_attrib must be present
        assert "custom_cot_attrib" in loc
        attrib = loc["custom_cot_attrib"]

        # Structure check
        assert "detail" in attrib
        assert "color" in attrib["detail"]
        assert "usericon" in attrib["detail"]

        # Colour should be "red" from explode_red.png
        color_argb = attrib["detail"]["color"]["_attributes"]["argb"]
        expected_red_argb = str(LiveuamapPlugin.COLOUR_TO_ARGB["red"])
        assert color_argb == expected_red_argb

        # Icon set path should contain the ARGB value
        usericon = attrib["detail"]["usericon"]
        icon_attrs = usericon["_attributes"]
        iconsetpath = icon_attrs["iconsetpath"]
        assert expected_red_argb in iconsetpath
        assert iconsetpath.startswith("COT_MAPPING_SPOTMAP/b-m-p-s-m/")

    @pytest.mark.asyncio
    async def test_multi_region_aggregation(self):
        """Multiple regions aggregate venues from all regions into one list."""
        plugin = self._make_plugin(config_overrides={"regions": "[0, 3]"})

        venue_ukraine = {**SAMPLE_VENUE, "id": 111, "name": "Ukraine event"}
        venue_syria = {
            **SAMPLE_VENUE,
            "id": 222,
            "name": "Syria event",
            "lat": 33.5138,
            "lng": 36.2765,
        }

        resp1 = self._mock_response(
            json_data={"success": True, "venues": [venue_ukraine]}
        )
        resp2 = self._mock_response(
            json_data={"success": True, "venues": [venue_syria]}
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=[resp1, resp2])

        locations = await plugin.fetch_locations(mock_session)

        assert len(locations) == 2
        uids = {loc["uid"] for loc in locations}
        assert "liveuamap-111" in uids
        assert "liveuamap-222" in uids

    @pytest.mark.asyncio
    async def test_error_responses_pass_through(self):
        """API failures return error dicts, not crash."""
        plugin = self._make_plugin(config_overrides={"regions": "[0]"})

        mock_resp = self._mock_response(json_data={}, status=401)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        locations = await plugin.fetch_locations(mock_session)

        assert len(locations) == 1
        assert "_error" in locations[0]
        assert locations[0]["_error"] == "401"


# ---------------------------------------------------------------------------
# Phase 8.2: E2E tests — CoT XML output verification
# ---------------------------------------------------------------------------


class TestLiveuamapCotXmlOutput:
    """Verify CoT XML includes color and usericon elements."""

    @pytest.mark.asyncio
    async def test_cot_xml_contains_color_element(self):
        """Generated CoT XML has <color argb="..."/> in detail."""
        red_argb = str(LiveuamapPlugin.COLOUR_TO_ARGB["red"])
        locations = [
            {
                "name": "Test Event",
                "lat": 48.4647,
                "lon": 35.0462,
                "uid": "liveuamap-99999",
                "cot_type": "b-m-p-s-m",
                "timestamp": "2026-03-04T12:00:00Z",
                "description": "[LiveUAMap] Test Event",
                "custom_cot_attrib": {
                    "detail": {
                        "color": {"_attributes": {"argb": red_argb}},
                        "usericon": {
                            "_attributes": {
                                "iconsetpath": (
                                    "COT_MAPPING_SPOTMAP"
                                    f"/b-m-p-s-m/{red_argb}"
                                )
                            }
                        },
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "b-m-p-s-m", 300, "per_point"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        # Verify <color argb="..."/> element
        color_elem = detail.find("color")
        assert color_elem is not None
        assert color_elem.get("argb") == red_argb

    @pytest.mark.asyncio
    async def test_cot_xml_contains_usericon_element(self):
        """Generated CoT XML has <usericon iconsetpath="..."/> in detail."""
        black_argb = str(LiveuamapPlugin.COLOUR_TO_ARGB["darkblack"])
        iconsetpath = f"COT_MAPPING_SPOTMAP/b-m-p-s-m/{black_argb}"
        locations = [
            {
                "name": "Test Marker",
                "lat": 33.5138,
                "lon": 36.2765,
                "uid": "liveuamap-88888",
                "cot_type": "b-m-p-s-m",
                "description": "[LiveUAMap] Test Marker",
                "custom_cot_attrib": {
                    "detail": {
                        "color": {"_attributes": {"argb": black_argb}},
                        "usericon": {
                            "_attributes": {"iconsetpath": iconsetpath}
                        },
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "b-m-p-s-m", 300, "per_point"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")

        usericon_elem = detail.find("usericon")
        assert usericon_elem is not None
        assert usericon_elem.get("iconsetpath") == iconsetpath

    @pytest.mark.asyncio
    async def test_cot_xml_event_type_is_spot_marker(self):
        """CoT event type attribute is b-m-p-s-m for liveuamap venues."""
        locations = [
            {
                "name": "Spot Marker",
                "lat": 48.4647,
                "lon": 35.0462,
                "uid": "liveuamap-77777",
                "cot_type": "b-m-p-s-m",
                "description": "[LiveUAMap] Spot Marker",
                "custom_cot_attrib": {
                    "detail": {
                        "color": {"_attributes": {"argb": "-16777216"}},
                        "usericon": {
                            "_attributes": {
                                "iconsetpath": (
                                    "COT_MAPPING_SPOTMAP"
                                    "/b-m-p-s-m/-16777216"
                                )
                            }
                        },
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "b-m-p-s-m", 300, "per_point"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        assert root.get("type") == "b-m-p-s-m"

    @pytest.mark.asyncio
    async def test_cot_xml_remarks_contains_description(self):
        """CoT XML remarks element contains the location description."""
        locations = [
            {
                "name": "Description Test",
                "lat": 48.4647,
                "lon": 35.0462,
                "uid": "liveuamap-66666",
                "cot_type": "b-m-p-s-m",
                "description": (
                    "[LiveUAMap] Explosion reported"
                    " — Dnipro, Dnipropetrovsk Oblast"
                ),
                "custom_cot_attrib": {
                    "detail": {
                        "color": {"_attributes": {"argb": "-65536"}},
                        "usericon": {
                            "_attributes": {
                                "iconsetpath": (
                                    "COT_MAPPING_SPOTMAP"
                                    "/b-m-p-s-m/-65536"
                                )
                            }
                        },
                    }
                },
            }
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "b-m-p-s-m", 300, "per_point"
        )

        assert len(events) == 1
        root = etree.fromstring(events[0])
        detail = root.find("detail")
        remarks = detail.find("remarks")

        assert remarks is not None
        assert "LiveUAMap" in remarks.text
        assert "Dnipro" in remarks.text

    @pytest.mark.asyncio
    async def test_cot_xml_error_locations_skipped(self):
        """Error dict locations from plugin are skipped in CoT generation."""
        locations = [
            {
                "name": "Good Event",
                "lat": 48.4647,
                "lon": 35.0462,
                "uid": "liveuamap-55555",
                "cot_type": "b-m-p-s-m",
                "description": "[LiveUAMap] Good Event",
                "custom_cot_attrib": {
                    "detail": {
                        "color": {"_attributes": {"argb": "-65536"}},
                        "usericon": {
                            "_attributes": {
                                "iconsetpath": (
                                    "COT_MAPPING_SPOTMAP"
                                    "/b-m-p-s-m/-65536"
                                )
                            }
                        },
                    }
                },
            },
            {
                "_error": "429",
                "_error_message": "Rate limit exceeded",
            },
        ]

        events = await QueuedCOTService._create_pytak_events(
            locations, "b-m-p-s-m", 300, "per_point"
        )

        # Only the valid location should produce an event
        assert len(events) == 1
        root = etree.fromstring(events[0])
        assert root.get("uid") == "liveuamap-55555"


class TestLiveuamapStreamIntegration:
    """E2E tests for stream creation and region persistence."""

    def test_stream_creation_with_liveuamap(self, app, db_session):
        """Create stream with liveuamap, verify DB record."""
        from models.stream import Stream

        with app.app_context():
            plugin_config = json.dumps({
                "api_key": "test-key",
                "regions": "[0, 3, 66]",
                "count": "50",
                "timeout": "30",
                "action": "mpts",
                "event_time": "",
            })

            stream = Stream(
                name="LiveUAMap Integration Test",
                plugin_type="liveuamap",
                cot_type="b-m-p-s-m",
                cot_type_mode="per_point",
            )
            stream.plugin_config = plugin_config
            db_session.add(stream)
            db_session.commit()

            # Verify stream was saved
            saved = db_session.get(Stream, stream.id)
            assert saved is not None
            assert saved.plugin_type == "liveuamap"
            assert saved.cot_type == "b-m-p-s-m"

            # Verify config round-trip
            config = json.loads(saved.plugin_config)
            assert config["api_key"] == "test-key"
            regions = json.loads(config["regions"])
            assert regions == [0, 3, 66]

    def test_stream_edit_preserves_regions(self, app, db_session):
        """Edit stream, verify regions persisted after update."""
        from models.stream import Stream

        with app.app_context():
            original_config = json.dumps({
                "api_key": "test-key",
                "regions": "[0, 3]",
                "count": "50",
                "timeout": "30",
            })

            stream = Stream(
                name="LiveUAMap Edit Test",
                plugin_type="liveuamap",
            )
            stream.plugin_config = original_config
            db_session.add(stream)
            db_session.commit()

            # Edit: change regions
            updated_config = json.dumps({
                "api_key": "test-key",
                "regions": "[0, 3, 66, 4]",
                "count": "100",
                "timeout": "30",
            })
            stream.plugin_config = updated_config
            db_session.commit()

            # Verify updated config
            saved = db_session.get(Stream, stream.id)
            config = json.loads(saved.plugin_config)
            regions = json.loads(config["regions"])
            assert regions == [0, 3, 66, 4]
            assert config["count"] == "100"
