"""
ABOUTME: YAML config schema validation and minimal-default fallbacks for TrakBridge
ABOUTME: Simplified validator (no oneOf/anyOf/allOf/$ref) used by ConfigLoader.load_config_safe
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(
        self,
        message: str,
        file_path: Optional[str] = None,
        field: Optional[str] = None,
    ):
        self.message = message
        self.file_path = file_path
        self.field = field
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        msg = f"Configuration Error: {self.message}"
        if self.file_path:
            msg += f" in file '{self.file_path}'"
        if self.field:
            msg += f" at field '{self.field}'"
        return msg


class ConfigValidator:
    """
    Simplified YAML schema validator for TrakBridge config files.

    Deliberately does not support oneOf / anyOf / allOf / $ref — those
    caused infinite recursion in earlier iterations. Schemas here must be
    flat: type / properties / required / items only.
    """

    schemas: Dict[str, Dict[str, Any]] = {
        "plugins.yaml": {
            "type": "object",
            "properties": {
                "allowed_plugin_modules": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        },
        "authentication.yaml": {
            "type": "object",
            "properties": {
                "authentication": {
                    "type": "object",
                    "properties": {
                        "provider_priority": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["local", "ldap", "oidc"],
                            },
                        },
                        "providers": {"type": "object"},
                    },
                    "required": ["provider_priority", "providers"],
                }
            },
            "required": ["authentication"],
        },
        "database.yaml": {
            "type": "object",
            "properties": {
                "default": {"type": "object"},
                "engine_options": {"type": "object"},
                "environments": {"type": "object"},
                "defaults": {"type": "object"},
            },
            "required": ["default"],
        },
    }

    _minimal_defaults: Dict[str, Dict[str, Any]] = {
        "plugins.yaml": {
            "allowed_plugin_modules": [
                "plugins.garmin_plugin",
                "plugins.spot_plugin",
                "plugins.traccar_plugin",
                "plugins.deepstate_plugin",
            ]
        },
        "authentication.yaml": {
            "authentication": {
                "provider_priority": ["local"],
                "providers": {"local": {"enabled": True}},
            }
        },
        "database.yaml": {
            "database": {
                "default_engine": "sqlite",
                "engines": {"sqlite": {"url": "sqlite:///data/trakbridge.db"}},
            }
        },
    }

    def load_and_validate(
        self,
        file_path: Path,
        config_name: str,
        required_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Parse a YAML file and validate it against the schema for config_name.

        Raises ConfigValidationError on empty/malformed YAML, non-dict root,
        missing required fields, or schema mismatches.
        """
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigValidationError(
                f"Unable to read configuration file: {e}", str(file_path)
            )

        if not content.strip():
            raise ConfigValidationError(
                "Configuration file is empty", str(file_path)
            )

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Invalid YAML syntax: {e}", str(file_path)
            )

        if data is None:
            raise ConfigValidationError(
                "Configuration file parsed to None (possibly empty or invalid YAML)",
                str(file_path),
            )

        if not isinstance(data, dict):
            raise ConfigValidationError(
                f"Configuration must be a dictionary, got {type(data).__name__}",
                str(file_path),
            )

        if required_fields:
            for field in required_fields:
                if field not in data:
                    raise ConfigValidationError(
                        f"Required field '{field}' is missing",
                        str(file_path),
                        field,
                    )

        schema = self.schemas.get(config_name)
        if schema is not None:
            self._validate_schema(data, schema, str(file_path))

        return data

    def _validate_schema(
        self, data: Any, schema: Dict[str, Any], file_path: str
    ) -> None:
        """Recursive schema check for type / required / properties only."""
        if schema.get("type") == "object" and not isinstance(data, dict):
            raise ConfigValidationError(
                f"Expected object, got {type(data).__name__}", file_path
            )

        if "required" in schema and isinstance(data, dict):
            for required_field in schema["required"]:
                if required_field not in data:
                    raise ConfigValidationError(
                        f"Required field '{required_field}' is missing",
                        file_path,
                        required_field,
                    )

        if "properties" in schema and isinstance(data, dict):
            for field, field_schema in schema["properties"].items():
                if field in data:
                    self._validate_schema(data[field], field_schema, file_path)

    def minimal_default(self, config_name: str) -> Dict[str, Any]:
        """Return the last-resort minimal config for config_name, or {}."""
        return dict(self._minimal_defaults.get(config_name, {}))
