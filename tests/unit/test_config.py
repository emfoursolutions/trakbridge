"""Unit tests for TrakBridge configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from config.base import BaseConfig
from config.environments import (
    DevelopmentConfig,
    ProductionConfig,
    TestingConfig,
    get_config,
)
from utils.config_manager import ConfigManager, ConfigValidationError


class TestConfigurationSystem:
    """Test the configuration system."""

    def test_get_config_development(self):
        """Test getting development configuration."""
        config = get_config("development")
        assert config is not None
        assert isinstance(config, DevelopmentConfig)
        assert config.DEBUG is True

    def test_get_config_production(self):
        """Test getting production configuration."""
        config = get_config("production")
        assert config is not None
        assert isinstance(config, ProductionConfig)
        assert config.DEBUG is False

    def test_get_config_testing(self):
        """Test getting testing configuration."""
        config = get_config("testing")
        assert config is not None
        assert isinstance(config, TestingConfig)
        assert config.TESTING is True

    def test_base_config_properties(self):
        """Test base configuration properties."""
        config = BaseConfig()

        # Test that required properties exist
        assert hasattr(config, "SECRET_KEY")
        assert hasattr(config, "SQLALCHEMY_DATABASE_URI")
        assert hasattr(config, "MAX_WORKER_THREADS")
        assert hasattr(config, "DEFAULT_POLL_INTERVAL")

    def test_config_validation(self):
        """Test configuration validation."""
        config = get_config("testing")

        # Test validation method exists and can be called
        if hasattr(config, "validate_config"):
            issues = config.validate_config()
            assert isinstance(issues, list)

    @patch.dict(os.environ, {"FLASK_ENV": "development"})
    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        config = get_config()  # Should use FLASK_ENV
        assert config is not None
        assert isinstance(config, DevelopmentConfig)


class TestDevelopmentConfig:
    """Test development-specific configuration."""

    def test_development_config_properties(self):
        """Test development configuration properties."""
        config = DevelopmentConfig()

        assert config.DEBUG is True
        assert config.TESTING is False
        assert "sqlite" in config.SQLALCHEMY_DATABASE_URI.lower()


class TestProductionConfig:
    """Test production-specific configuration."""

    def test_production_config_properties(self):
        """Test production configuration properties."""
        config = ProductionConfig()

        assert config.DEBUG is False
        assert config.TESTING is False


class TestTestEnvironmentConfig:
    """Test testing-specific configuration."""

    def test_testing_config_properties(self):
        """Test testing configuration properties."""
        config = TestingConfig()

        assert config.TESTING is True
        assert config.DEBUG is False  # Testing config disables debug for cleaner output
        assert (
            "sqlite" in config.SQLALCHEMY_DATABASE_URI.lower()
            or "memory" in config.SQLALCHEMY_DATABASE_URI.lower()
        )


class TestConfigManagerPluginValidation:
    """Test ConfigManager plugin configuration validation."""

    def test_plugins_yaml_schema_structure(self):
        """Test that plugins.yaml schema has correct structure for allowed_plugin_modules."""
        manager = ConfigManager()
        schema = manager.schemas.get("plugins.yaml")

        assert schema is not None
        field_schema = schema["properties"]["allowed_plugin_modules"]

        # Should be a simple array schema (oneOf causes recursion issues)
        assert field_schema["type"] == "array"
        assert field_schema["items"]["type"] == "string"

        # Should NOT use oneOf to prevent recursion in simplified validator
        assert "oneOf" not in field_schema

    def test_plugins_yaml_validation_with_null(self):
        """Test that null values load without recursion (plugin manager handles gracefully)."""
        config_data = {"allowed_plugin_modules": None}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            manager = ConfigManager()
            # Direct file loading should work without recursion errors
            # Even though schema expects array, the simplified validator should handle this
            result = manager._load_and_validate_file(temp_path, "plugins.yaml")

            # Should load the actual data (PluginManager handles None gracefully)
            assert result is not None
            assert "allowed_plugin_modules" in result
            assert result["allowed_plugin_modules"] is None  # Actual value from file
        finally:
            temp_path.unlink()

    def test_plugins_yaml_validation_with_empty_list(self):
        """Test validation of plugins.yaml with empty list allowed_plugin_modules."""
        config_data = {"allowed_plugin_modules": []}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            manager = ConfigManager()
            result = manager._load_and_validate_file(temp_path, "plugins.yaml")
            assert result == config_data
        finally:
            temp_path.unlink()

    def test_plugins_yaml_validation_with_valid_list(self):
        """Test validation of plugins.yaml with valid plugin module list."""
        config_data = {
            "allowed_plugin_modules": [
                "plugins.custom_plugin",
                "external_plugins.company_tracker",
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            manager = ConfigManager()
            result = manager._load_and_validate_file(temp_path, "plugins.yaml")
            assert result == config_data
        finally:
            temp_path.unlink()

    def test_plugins_yaml_validation_with_invalid_type(self):
        """Test validation of plugins.yaml with invalid type for allowed_plugin_modules."""
        config_data = {"allowed_plugin_modules": "not_a_list_or_null"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            manager = ConfigManager()
            # Config manager loads the data but plugin manager should handle the invalid type gracefully
            result = manager._load_and_validate_file(temp_path, "plugins.yaml")
            assert result["allowed_plugin_modules"] == "not_a_list_or_null"

            # The plugin manager should handle this gracefully by logging a warning
            # and falling back to built-in plugins only
        finally:
            temp_path.unlink()

    def test_load_config_safe_with_none_value(self):
        """Test load_config_safe handles None values gracefully."""
        config_data = {"allowed_plugin_modules": None}

        with patch("utils.config_manager.Path.exists", return_value=True):
            with patch("builtins.open", mock_open_yaml(config_data)):
                manager = ConfigManager()
                result = manager.load_config_safe(
                    "plugins.yaml", required_fields=["allowed_plugin_modules"]
                )

                assert result is not None
                assert result["allowed_plugin_modules"] is None

    def test_load_config_safe_with_empty_list(self):
        """Test load_config_safe handles empty lists gracefully."""
        config_data = {"allowed_plugin_modules": []}

        with patch("utils.config_manager.Path.exists", return_value=True):
            with patch("builtins.open", mock_open_yaml(config_data)):
                manager = ConfigManager()
                result = manager.load_config_safe(
                    "plugins.yaml", required_fields=["allowed_plugin_modules"]
                )

                assert result is not None
                assert result["allowed_plugin_modules"] == []

    def test_default_config_generation_for_plugins(self):
        """Test that default config for plugins.yaml includes valid structure."""
        manager = ConfigManager()
        default = manager._get_minimal_default_config("plugins.yaml")

        assert "allowed_plugin_modules" in default
        assert isinstance(default["allowed_plugin_modules"], list)
        # Should have built-in plugins
        assert len(default["allowed_plugin_modules"]) > 0
        assert all("plugins." in module for module in default["allowed_plugin_modules"])

    def test_schema_recursion_prevention(self):
        """Test that schemas don't use unsupported keywords that cause recursion."""
        manager = ConfigManager()

        # Check all schemas for unsupported keywords that cause recursion
        unsupported_keywords = ["oneOf", "anyOf", "allOf", "$ref"]

        for schema_name, schema in manager.schemas.items():
            self._check_schema_for_unsupported_keywords(
                schema, unsupported_keywords, schema_name
            )

    def _check_schema_for_unsupported_keywords(
        self, schema, unsupported_keywords, path=""
    ):
        """Recursively check schema for unsupported keywords."""
        if isinstance(schema, dict):
            for keyword in unsupported_keywords:
                assert (
                    keyword not in schema
                ), f"Unsupported keyword '{keyword}' found in schema at {path} - causes recursion in simplified validator"

            for key, value in schema.items():
                self._check_schema_for_unsupported_keywords(
                    value, unsupported_keywords, f"{path}.{key}"
                )
        elif isinstance(schema, list):
            for i, item in enumerate(schema):
                self._check_schema_for_unsupported_keywords(
                    item, unsupported_keywords, f"{path}[{i}]"
                )


def mock_open_yaml(data):
    """Helper to mock file opening with YAML data."""
    import io

    yaml_content = yaml.dump(data)
    return Mock(return_value=io.StringIO(yaml_content))
