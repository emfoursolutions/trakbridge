"""
ABOUTME: Unit tests for GenericXMLInboundPlugin covering XPath field mapping,
ABOUTME: batch XML payloads, XXE prevention, invalid XML, and auth modes.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from plugins.generic_xml_inbound_plugin import GenericXMLInboundPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(overrides=None):
    """Create a GenericXMLInboundPlugin with sensible test defaults."""
    config = {
        "items_xpath": "//device",
        "lat_xpath": "lat",
        "lon_xpath": "lon",
        "uid_xpath": "id",
        "callsign_xpath": "name",
        "auth_mode": "api_key",
        "api_key": "test-key-xml",
    }
    if overrides:
        config.update(overrides)
    return GenericXMLInboundPlugin(config)


def _transform(plugin, xml_str, content_type="application/xml"):
    """Shorthand for calling transform_payload with mocked decryption."""
    config = plugin.config.copy()
    raw = xml_str.encode("utf-8") if isinstance(xml_str, str) else xml_str
    with patch.object(plugin, "get_decrypted_config", return_value=config):
        return plugin.transform_payload(raw, content_type, {})


# ---------------------------------------------------------------------------
# Plugin identity & metadata
# ---------------------------------------------------------------------------


class TestXMLPluginIdentity:
    """Verify plugin name, metadata, and category."""

    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "generic_xml_inbound"

    def test_class_level_plugin_name(self):
        assert GenericXMLInboundPlugin.get_plugin_name() == "generic_xml_inbound"

    def test_category_is_inbound(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "inbound"

    def test_accepted_content_types(self):
        plugin = _make_plugin()
        types = plugin.get_accepted_content_types()
        assert "application/xml" in types
        assert "text/xml" in types

    def test_has_required_config_fields(self):
        plugin = _make_plugin()
        field_names = [f.name for f in plugin.get_config_fields()]
        for required in ("lat_xpath", "lon_xpath", "uid_xpath", "callsign_xpath"):
            assert required in field_names

    def test_api_key_is_sensitive(self):
        plugin = _make_plugin()
        sensitive = plugin.get_sensitive_fields()
        assert "api_key" in sensitive


# ---------------------------------------------------------------------------
# Single-element payloads
# ---------------------------------------------------------------------------


class TestSingleElement:
    """Transform XML with a single device element."""

    def test_basic_xml(self):
        plugin = _make_plugin()
        xml = """
        <root>
            <device>
                <id>dev-1</id>
                <name>Alpha</name>
                <lat>38.9</lat>
                <lon>-77.0</lon>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert len(result) == 1
        loc = result[0]
        assert loc["uid"] == "dev-1"
        assert loc["name"] == "Alpha"
        assert loc["lat"] == 38.9
        assert loc["lon"] == -77.0

    def test_numeric_strings_coerced(self):
        plugin = _make_plugin()
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>38.9</lat><lon>-77.0</lon>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert isinstance(result[0]["lat"], float)
        assert isinstance(result[0]["lon"], float)


# ---------------------------------------------------------------------------
# Multiple elements
# ---------------------------------------------------------------------------


class TestMultipleElements:
    """Transform XML with multiple device elements."""

    def test_multiple_devices(self):
        plugin = _make_plugin()
        xml = """
        <root>
            <device>
                <id>dev-1</id><name>Alpha</name>
                <lat>38.9</lat><lon>-77.0</lon>
            </device>
            <device>
                <id>dev-2</id><name>Bravo</name>
                <lat>39.0</lat><lon>-76.5</lon>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert len(result) == 2
        assert result[0]["uid"] == "dev-1"
        assert result[1]["uid"] == "dev-2"

    def test_no_matching_elements_raises(self):
        plugin = _make_plugin()
        xml = "<root><other>nothing</other></root>"
        with pytest.raises(ValueError, match="[Nn]o.*location"):
            _transform(plugin, xml)


# ---------------------------------------------------------------------------
# XPath variations
# ---------------------------------------------------------------------------


class TestXPathMapping:
    """Verify XPath-based field extraction."""

    def test_attribute_xpath(self):
        """Extract values from XML attributes."""
        plugin = _make_plugin({
            "items_xpath": "//point",
            "lat_xpath": "@latitude",
            "lon_xpath": "@longitude",
            "uid_xpath": "@id",
            "callsign_xpath": "@name",
        })
        xml = '<root><point id="p1" name="Alpha" latitude="38.9" longitude="-77.0"/></root>'
        result = _transform(plugin, xml)
        assert len(result) == 1
        assert result[0]["uid"] == "p1"
        assert result[0]["lat"] == 38.9

    def test_nested_child_xpath(self):
        """Extract values from nested child elements."""
        plugin = _make_plugin({
            "items_xpath": "//tracker",
            "lat_xpath": "position/lat",
            "lon_xpath": "position/lon",
            "uid_xpath": "info/serial",
            "callsign_xpath": "info/label",
        })
        xml = """
        <data>
            <tracker>
                <info><serial>SN-001</serial><label>Truck A</label></info>
                <position><lat>51.5074</lat><lon>-0.1278</lon></position>
            </tracker>
        </data>
        """
        result = _transform(plugin, xml)
        assert result[0]["uid"] == "SN-001"
        assert result[0]["name"] == "Truck A"
        assert result[0]["lat"] == 51.5074

    def test_missing_required_xpath_raises(self):
        """Missing lat element raises ValueError."""
        plugin = _make_plugin({"lat_xpath": "latitude"})
        xml = """
        <root>
            <device><id>d1</id><name>A</name><lon>-77.0</lon></device>
        </root>
        """
        with pytest.raises(ValueError, match="lat"):
            _transform(plugin, xml)


# ---------------------------------------------------------------------------
# Optional fields (timestamp, speed, course)
# ---------------------------------------------------------------------------


class TestXMLOptionalFields:
    """Verify optional field extraction from XML."""

    def test_speed_extracted(self):
        plugin = _make_plugin({"speed_xpath": "speed"})
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
                <speed>5.5</speed>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert result[0]["speed"] == 5.5

    def test_course_extracted(self):
        plugin = _make_plugin({"course_xpath": "heading"})
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
                <heading>180.0</heading>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert result[0]["course"] == 180.0

    def test_timestamp_extracted(self):
        plugin = _make_plugin({"timestamp_xpath": "ts"})
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
                <ts>2026-04-11T12:00:00Z</ts>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert result[0].get("timestamp") is not None

    def test_missing_optional_fields_absent(self):
        plugin = _make_plugin({"speed_xpath": "speed"})
        xml = """
        <root>
            <device><id>d1</id><name>A</name><lat>1.0</lat><lon>2.0</lon></device>
        </root>
        """
        result = _transform(plugin, xml)
        assert "speed" not in result[0]


# ---------------------------------------------------------------------------
# XXE prevention (defusedxml)
# ---------------------------------------------------------------------------


class TestXXEPrevention:
    """Verify that XXE attacks are blocked by defusedxml."""

    def test_xxe_entity_expansion_blocked(self):
        """External entity injection must be rejected."""
        plugin = _make_plugin()
        xxe_xml = """<?xml version="1.0"?>
        <!DOCTYPE foo [
            <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <root>
            <device>
                <id>&xxe;</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
            </device>
        </root>
        """
        with pytest.raises(ValueError, match="[Xx][Mm][Ll]|[Ee]ntit|[Ff]orbidden|[Dd]efused"):
            _transform(plugin, xxe_xml)

    def test_billion_laughs_blocked(self):
        """Billion-laughs DoS attack must be rejected."""
        plugin = _make_plugin()
        bomb_xml = """<?xml version="1.0"?>
        <!DOCTYPE lolz [
            <!ENTITY lol "lol">
            <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
            <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
        ]>
        <root>
            <device>
                <id>&lol3;</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
            </device>
        </root>
        """
        with pytest.raises(ValueError):
            _transform(plugin, bomb_xml)


# ---------------------------------------------------------------------------
# Invalid / malformed XML
# ---------------------------------------------------------------------------


class TestInvalidXML:
    """Error handling for bad XML input."""

    def test_non_xml_bytes_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError, match="[Xx][Mm][Ll]|[Pp]arse"):
            _transform(plugin, b"this is not xml")

    def test_non_numeric_lat_raises(self):
        plugin = _make_plugin()
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>abc</lat><lon>2.0</lon>
            </device>
        </root>
        """
        with pytest.raises(ValueError, match="lat"):
            _transform(plugin, xml)

    def test_empty_xml_raises(self):
        plugin = _make_plugin()
        with pytest.raises(ValueError):
            _transform(plugin, b"")


# ---------------------------------------------------------------------------
# Auth modes (inherited)
# ---------------------------------------------------------------------------


class TestXMLAuthModes:
    """Auth behaviour inherited from BaseInboundPlugin."""

    def test_api_key_auth_passes(self):
        plugin = _make_plugin()
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "test-key-xml", "auth_mode": "api_key"
        }):
            ok, err = plugin.validate_inbound_request({"Authorization": "Bearer test-key-xml"})
            assert ok is True

    def test_api_key_auth_rejects(self):
        plugin = _make_plugin()
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "test-key-xml", "auth_mode": "api_key"
        }):
            ok, err = plugin.validate_inbound_request({"Authorization": "Bearer wrong"})
            assert ok is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestXMLEdgeCases:
    """Boundary and edge-case scenarios."""

    def test_large_batch(self):
        """50 device elements should process successfully."""
        plugin = _make_plugin()
        devices = "\n".join(
            f'<device><id>d{i}</id><name>D{i}</name><lat>{float(i)}</lat><lon>{float(-i)}</lon></device>'
            for i in range(50)
        )
        xml = f"<root>{devices}</root>"
        result = _transform(plugin, xml)
        assert len(result) == 50

    def test_text_xml_content_type_accepted(self):
        """text/xml should be accepted alongside application/xml."""
        plugin = _make_plugin()
        xml = "<root><device><id>d1</id><name>A</name><lat>1.0</lat><lon>2.0</lon></device></root>"
        result = _transform(plugin, xml, content_type="text/xml")
        assert len(result) == 1

    def test_extra_elements_ignored(self):
        """Unknown elements in the XML should not cause errors."""
        plugin = _make_plugin()
        xml = """
        <root>
            <device>
                <id>d1</id><name>A</name>
                <lat>1.0</lat><lon>2.0</lon>
                <battery>85</battery><signal>strong</signal>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert len(result) == 1
        assert result[0]["uid"] == "d1"

    def test_xml_with_namespace(self):
        """Elements with XML namespaces should be accessible via wildcard XPath."""
        plugin = _make_plugin({
            "items_xpath": "//{http://example.com}device",
            "lat_xpath": "{http://example.com}lat",
            "lon_xpath": "{http://example.com}lon",
            "uid_xpath": "{http://example.com}id",
            "callsign_xpath": "{http://example.com}name",
        })
        xml = """
        <root xmlns="http://example.com">
            <device>
                <id>ns-1</id><name>NS</name>
                <lat>10.0</lat><lon>20.0</lon>
            </device>
        </root>
        """
        result = _transform(plugin, xml)
        assert len(result) == 1
        assert result[0]["uid"] == "ns-1"
