"""
ABOUTME: Unit tests for BaseInboundPlugin abstract base class covering instantiation,
ABOUTME: transform_payload, validate_inbound_request, config encryption, and metadata.
"""

from unittest.mock import patch, MagicMock

import pytest

from plugins.base_plugin import BaseInboundPlugin, PluginConfigField, PluginConfigMixin


class ConcreteInboundPlugin(BaseInboundPlugin):
    """Concrete implementation of BaseInboundPlugin for testing."""

    @property
    def plugin_name(self) -> str:
        return "test_inbound"

    @property
    def plugin_metadata(self):
        return {
            "display_name": "Test Inbound Plugin",
            "description": "A test inbound plugin",
            "icon": "fas fa-arrow-circle-down",
            "category": "inbound",
            "accepted_content_types": ["application/json"],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=False,
                    sensitive=True,
                ),
                PluginConfigField(
                    name="auth_mode",
                    label="Auth Mode",
                    field_type="select",
                    required=False,
                    default_value="api_key",
                    options=[
                        {"value": "api_key", "label": "API Key"},
                        {"value": "none", "label": "None"},
                    ],
                ),
                PluginConfigField(
                    name="lat_field",
                    label="Latitude Field",
                    field_type="text",
                    required=True,
                    default_value="lat",
                ),
            ],
        }

    def transform_payload(self, raw_body, content_type, headers):
        import json

        data = json.loads(raw_body)
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "uid": item.get("id", "unknown"),
                "name": item.get("name", "Unknown"),
                "lat": float(item.get("lat", 0)),
                "lon": float(item.get("lon", 0)),
            }
            for item in data
        ]


class TestBaseInboundPluginInstantiation:
    """Test BaseInboundPlugin construction and inheritance."""

    def test_is_abstract(self):
        """BaseInboundPlugin cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseInboundPlugin({})

    def test_inherits_plugin_config_mixin(self):
        """BaseInboundPlugin inherits from PluginConfigMixin."""
        assert issubclass(BaseInboundPlugin, PluginConfigMixin)

    def test_concrete_instantiation(self):
        """Concrete subclass can be instantiated."""
        plugin = ConcreteInboundPlugin({"lat_field": "lat"})
        assert plugin is not None
        assert plugin.plugin_name == "test_inbound"

    def test_has_encryption_service(self):
        """Plugin has encryption service after construction."""
        plugin = ConcreteInboundPlugin({})
        assert plugin.encryption_service is not None

    def test_stream_starts_as_none(self):
        """Stream reference starts as None."""
        plugin = ConcreteInboundPlugin({})
        assert plugin.stream is None


class TestTransformPayload:
    """Test the transform_payload method."""

    def test_single_location(self):
        """Transform a single JSON object into a location dict."""
        plugin = ConcreteInboundPlugin({})
        import json

        payload = json.dumps({"id": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0})
        result = plugin.transform_payload(payload.encode(), "application/json", {})

        assert len(result) == 1
        assert result[0]["uid"] == "dev-1"
        assert result[0]["name"] == "Alpha"
        assert result[0]["lat"] == 38.9
        assert result[0]["lon"] == -77.0

    def test_multiple_locations(self):
        """Transform a JSON array into multiple location dicts."""
        plugin = ConcreteInboundPlugin({})
        import json

        payload = json.dumps([
            {"id": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0},
            {"id": "dev-2", "name": "Bravo", "lat": 39.0, "lon": -76.5},
        ])
        result = plugin.transform_payload(payload.encode(), "application/json", {})

        assert len(result) == 2
        assert result[0]["uid"] == "dev-1"
        assert result[1]["uid"] == "dev-2"

    def test_invalid_json_raises(self):
        """Invalid JSON payload raises ValueError."""
        plugin = ConcreteInboundPlugin({})
        with pytest.raises(Exception):
            plugin.transform_payload(b"not json", "application/json", {})


class TestValidateInboundRequest:
    """Test the validate_inbound_request method."""

    def test_valid_api_key(self):
        """Valid Bearer token passes auth."""
        plugin = ConcreteInboundPlugin({"api_key": "secret123", "auth_mode": "api_key"})
        # Mock decryption to return the key as-is
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "secret123", "auth_mode": "api_key"
        }):
            is_valid, error = plugin.validate_inbound_request(
                {"Authorization": "Bearer secret123"}
            )
            assert is_valid is True
            assert error is None

    def test_invalid_api_key(self):
        """Invalid Bearer token fails auth."""
        plugin = ConcreteInboundPlugin({"api_key": "secret123", "auth_mode": "api_key"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "secret123", "auth_mode": "api_key"
        }):
            is_valid, error = plugin.validate_inbound_request(
                {"Authorization": "Bearer wrong_key"}
            )
            assert is_valid is False
            assert "Invalid API key" in error

    def test_missing_auth_header(self):
        """Missing Authorization header fails auth."""
        plugin = ConcreteInboundPlugin({"api_key": "secret123", "auth_mode": "api_key"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "secret123", "auth_mode": "api_key"
        }):
            is_valid, error = plugin.validate_inbound_request({})
            assert is_valid is False
            assert "Missing" in error

    def test_non_bearer_auth(self):
        """Non-Bearer Authorization header fails auth."""
        plugin = ConcreteInboundPlugin({"api_key": "secret123", "auth_mode": "api_key"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "api_key": "secret123", "auth_mode": "api_key"
        }):
            is_valid, error = plugin.validate_inbound_request(
                {"Authorization": "Basic dXNlcjpwYXNz"}
            )
            assert is_valid is False

    def test_auth_mode_none(self):
        """Auth mode 'none' skips authentication."""
        plugin = ConcreteInboundPlugin({"auth_mode": "none"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "auth_mode": "none"
        }):
            is_valid, error = plugin.validate_inbound_request({})
            assert is_valid is True
            assert error is None

    def test_no_api_key_configured(self):
        """Missing API key in config fails auth."""
        plugin = ConcreteInboundPlugin({"auth_mode": "api_key"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "auth_mode": "api_key"
        }):
            is_valid, error = plugin.validate_inbound_request(
                {"Authorization": "Bearer anything"}
            )
            assert is_valid is False
            assert "No API key configured" in error


class TestAcceptedContentTypes:
    """Test content type handling."""

    def test_get_accepted_content_types(self):
        """Returns accepted content types from metadata."""
        plugin = ConcreteInboundPlugin({})
        types = plugin.get_accepted_content_types()
        assert types == ["application/json"]

    def test_default_content_types(self):
        """Defaults to application/json if not specified in metadata."""

        class NoContentTypePlugin(BaseInboundPlugin):
            @property
            def plugin_name(self):
                return "no_ct"

            @property
            def plugin_metadata(self):
                return {"config_fields": []}

            def transform_payload(self, raw_body, content_type, headers):
                return []

        plugin = NoContentTypePlugin({})
        assert plugin.get_accepted_content_types() == ["application/json"]


class TestInheritedMixinMethods:
    """Test that mixin methods work correctly on BaseInboundPlugin."""

    def test_get_config_fields(self):
        """Config fields are extracted from metadata."""
        plugin = ConcreteInboundPlugin({})
        fields = plugin.get_config_fields()
        assert len(fields) == 3
        names = [f.name for f in fields]
        assert "api_key" in names
        assert "auth_mode" in names
        assert "lat_field" in names

    def test_get_sensitive_fields(self):
        """Sensitive fields are identified correctly."""
        plugin = ConcreteInboundPlugin({})
        sensitive = plugin.get_sensitive_fields()
        assert "api_key" in sensitive
        assert "auth_mode" not in sensitive

    def test_required_config_fields(self):
        """Required fields are derived from metadata."""
        plugin = ConcreteInboundPlugin({})
        required = plugin.required_config_fields
        assert "lat_field" in required
        assert "api_key" not in required

    def test_validate_config_passes(self):
        """Valid config passes validation."""
        plugin = ConcreteInboundPlugin({"lat_field": "latitude"})
        with patch.object(plugin, "get_decrypted_config", return_value={
            "lat_field": "latitude"
        }):
            assert plugin.validate_config() is True

    def test_validate_config_missing_required(self):
        """Missing required field fails validation."""
        plugin = ConcreteInboundPlugin({})
        with patch.object(plugin, "get_decrypted_config", return_value={}):
            assert plugin.validate_config() is False
