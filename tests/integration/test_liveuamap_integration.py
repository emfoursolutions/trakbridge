# ABOUTME: Integration tests for LiveUAMap plugin config extraction
# ABOUTME: Tests that regions JSON is properly parsed from form request data

import json

import pytest

from plugins.plugin_manager import get_plugin_manager
from services.stream_config_service import StreamConfigService


class TestLiveuamapConfigExtraction:
    """Test that regions JSON field is properly parsed from request data."""

    def setup_method(self):
        """Set up plugin manager and config service for each test."""
        self.plugin_manager = get_plugin_manager()
        self.config_service = StreamConfigService(self.plugin_manager)

    def test_regions_json_parsed_from_request(self):
        """Mock request data with plugin_regions='[0,3,66]', verify parsed as list [0, 3, 66]."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "[0,3,66]",
        }
        plugin_config = self.config_service.extract_plugin_config_from_request(data)
        assert plugin_config["regions"] == [0, 3, 66]

    def test_regions_empty_string_defaults_to_empty_list(self):
        """plugin_regions='' should default to []."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "",
        }
        plugin_config = self.config_service.extract_plugin_config_from_request(data)
        assert plugin_config["regions"] == []

    def test_regions_invalid_json_defaults_to_empty_list(self):
        """plugin_regions='not json' should default to []."""
        data = {
            "plugin_type": "liveuamap",
            "plugin_api_key": "test-key",
            "plugin_regions": "not json",
        }
        plugin_config = self.config_service.extract_plugin_config_from_request(data)
        assert plugin_config["regions"] == []
