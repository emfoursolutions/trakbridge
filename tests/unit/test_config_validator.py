"""
ABOUTME: Unit tests for the ConfigValidator schema/validation module
ABOUTME: Locks in schema shape, recursion prevention, minimal-default generation, and null/empty list handling
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from config.validator import ConfigValidationError, ConfigValidator


class TestConfigValidatorSchemas:
    """Schema shape contract: keeps the simplified validator recursion-safe."""

    def test_plugins_yaml_schema_structure(self):
        """plugins.yaml schema must be a simple array-of-string, no oneOf."""
        validator = ConfigValidator()
        schema = validator.schemas.get("plugins.yaml")

        assert schema is not None
        field_schema = schema["properties"]["allowed_plugin_modules"]
        assert field_schema["type"] == "array"
        assert field_schema["items"]["type"] == "string"
        # oneOf/anyOf/allOf/$ref cause recursion in the simplified validator
        assert "oneOf" not in field_schema

    def test_schemas_have_no_recursive_keywords(self):
        """Walk every schema; no oneOf/anyOf/allOf/$ref anywhere."""
        validator = ConfigValidator()
        unsupported = ["oneOf", "anyOf", "allOf", "$ref"]

        for schema_name, schema in validator.schemas.items():
            _assert_no_unsupported_keywords(schema, unsupported, schema_name)


class TestConfigValidatorValidate:
    """Validation behaviour against real YAML files."""

    def test_validate_null_field_does_not_recurse(self, tmp_path):
        """Null allowed_plugin_modules must not blow up the validator."""
        config = {"allowed_plugin_modules": None}
        path = _write_yaml(tmp_path, "plugins.yaml", config)

        validator = ConfigValidator()
        # Should return the parsed data as-is; plugin_manager handles None downstream
        result = validator.load_and_validate(path, "plugins.yaml")

        assert result == config
        assert result["allowed_plugin_modules"] is None

    def test_validate_empty_list_field(self, tmp_path):
        """Empty allowed_plugin_modules list is valid."""
        config = {"allowed_plugin_modules": []}
        path = _write_yaml(tmp_path, "plugins.yaml", config)

        validator = ConfigValidator()
        result = validator.load_and_validate(path, "plugins.yaml")

        assert result == config

    def test_validate_valid_module_list(self, tmp_path):
        """Well-formed plugin module list validates."""
        config = {
            "allowed_plugin_modules": [
                "plugins.custom_plugin",
                "external_plugins.company_tracker",
            ]
        }
        path = _write_yaml(tmp_path, "plugins.yaml", config)

        validator = ConfigValidator()
        result = validator.load_and_validate(path, "plugins.yaml")

        assert result == config

    def test_validate_wrong_type_field_passes_through(self, tmp_path):
        """Invalid type on allowed_plugin_modules loads; downstream handles it."""
        config = {"allowed_plugin_modules": "not_a_list_or_null"}
        path = _write_yaml(tmp_path, "plugins.yaml", config)

        validator = ConfigValidator()
        # Simplified validator loads the file; plugin_manager warns + falls back
        result = validator.load_and_validate(path, "plugins.yaml")

        assert result["allowed_plugin_modules"] == "not_a_list_or_null"

    def test_validate_missing_required_field_raises(self, tmp_path):
        """Missing required field raises ConfigValidationError."""
        config = {"unrelated_key": "value"}
        path = _write_yaml(tmp_path, "plugins.yaml", config)

        validator = ConfigValidator()
        with pytest.raises(ConfigValidationError):
            validator.load_and_validate(
                path, "plugins.yaml", required_fields=["allowed_plugin_modules"]
            )

    def test_validate_empty_file_raises(self, tmp_path):
        """Empty YAML file is rejected."""
        path = tmp_path / "plugins.yaml"
        path.write_text("")

        validator = ConfigValidator()
        with pytest.raises(ConfigValidationError):
            validator.load_and_validate(path, "plugins.yaml")

    def test_validate_malformed_yaml_raises(self, tmp_path):
        """Invalid YAML syntax is rejected."""
        path = tmp_path / "plugins.yaml"
        path.write_text("allowed_plugin_modules: [unclosed")

        validator = ConfigValidator()
        with pytest.raises(ConfigValidationError):
            validator.load_and_validate(path, "plugins.yaml")


class TestConfigValidatorMinimalDefault:
    """Minimal default fallback for last-resort config loading."""

    def test_minimal_default_for_plugins_yaml(self):
        validator = ConfigValidator()
        default = validator.minimal_default("plugins.yaml")

        assert "allowed_plugin_modules" in default
        assert isinstance(default["allowed_plugin_modules"], list)
        assert len(default["allowed_plugin_modules"]) > 0
        assert all(m.startswith("plugins.") for m in default["allowed_plugin_modules"])

    def test_minimal_default_for_unknown_returns_empty(self):
        validator = ConfigValidator()
        assert validator.minimal_default("unknown.yaml") == {}


def _write_yaml(tmp_path: Path, name: str, data: dict) -> Path:
    """Write dict as YAML to a tmp_path file, return the path."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data))
    return path


def _assert_no_unsupported_keywords(schema, unsupported, path):
    if isinstance(schema, dict):
        for keyword in unsupported:
            assert keyword not in schema, (
                f"Unsupported keyword '{keyword}' found in schema at {path} "
                f"— causes recursion in simplified validator"
            )
        for key, value in schema.items():
            _assert_no_unsupported_keywords(value, unsupported, f"{path}.{key}")
    elif isinstance(schema, list):
        for i, item in enumerate(schema):
            _assert_no_unsupported_keywords(item, unsupported, f"{path}[{i}]")
