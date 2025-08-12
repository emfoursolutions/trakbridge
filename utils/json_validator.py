"""
File: utils/json_validator.py

Description:
    JSON Validation and Security Utility

    This module provides secure JSON parsing and validation capabilities with built-in
    protection against DoS attacks and malformed data. It includes schema validation,
    size limits, and comprehensive error handling for plugin configurations.

    Key features:
    - Size-limited JSON parsing to prevent memory exhaustion attacks
    - Depth-limited parsing to prevent stack overflow attacks  
    - Schema validation using JSON Schema specification
    - Plugin-specific configuration validation
    - Comprehensive error reporting with security context
    - Performance monitoring for parsing operations

Author: Emfour Solutions
Created: 2025-07-26
"""

# Standard library imports
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

# Module-level logger
logger = logging.getLogger(__name__)

# Security limits for JSON parsing
DEFAULT_MAX_SIZE = 1024 * 1024  # 1MB max JSON size
DEFAULT_MAX_DEPTH = 32  # Max nesting depth
DEFAULT_MAX_KEYS = 1000  # Max number of keys per object
DEFAULT_MAX_ARRAY = 10000  # Max array length


@dataclass
class ValidationResult:
    """Result of JSON validation operation"""

    valid: bool
    data: Any = None
    errors: List[str] = None
    warnings: List[str] = None
    size_bytes: int = 0
    parse_time_ms: float = 0.0

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


class JSONValidationError(Exception):
    """Custom exception for JSON validation errors"""

    def __init__(
        self,
        message: str,
        error_type: str = "validation",
        details: Dict[str, Any] = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


class SecureJSONValidator:
    """
    Secure JSON validator with size limits and schema validation
    """

    def __init__(
        self,
        max_size: int = DEFAULT_MAX_SIZE,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_keys: int = DEFAULT_MAX_KEYS,
        max_array: int = DEFAULT_MAX_ARRAY,
    ):
        self.max_size = max_size
        self.max_depth = max_depth
        self.max_keys = max_keys
        self.max_array = max_array

    def validate_and_parse(
        self,
        json_string: str,
        schema: Optional[Dict[str, Any]] = None,
        context: str = "unknown",
    ) -> ValidationResult:
        """
        Validate and parse JSON string with security controls

        Args:
            json_string: The JSON string to parse
            schema: Optional JSON schema for validation
            context: Context description for logging

        Returns:
            ValidationResult with parsed data and validation info
        """
        start_time = time.time()
        result = ValidationResult(valid=False)

        try:
            # Size validation
            if not json_string:
                result.errors.append("JSON string is empty")
                return result

            json_bytes = json_string.encode("utf-8")
            result.size_bytes = len(json_bytes)

            if result.size_bytes > self.max_size:
                result.errors.append(
                    f"JSON size ({result.size_bytes} bytes) exceeds maximum allowed size ({self.max_size} bytes)"
                )
                logger.warning(
                    f"JSON validation failed for {context}: size limit exceeded "
                    f"({result.size_bytes} > {self.max_size})"
                )
                return result

            # Parse with depth and structure validation
            try:
                result.data = self._safe_json_parse(json_string)
            except json.JSONDecodeError as e:
                result.errors.append(f"Invalid JSON format: {str(e)}")
                logger.warning(f"JSON parsing failed for {context}: {str(e)}")
                return result
            except JSONValidationError as e:
                result.errors.append(str(e))
                logger.warning(f"JSON validation failed for {context}: {str(e)}")
                return result

            # Schema validation if provided
            if schema and result.data is not None:
                schema_errors = self._validate_schema(result.data, schema)
                if schema_errors:
                    result.errors.extend(schema_errors)
                    logger.warning(
                        f"Schema validation failed for {context}: {schema_errors}"
                    )
                    return result

            # Success
            result.valid = True
            logger.debug(
                f"JSON validation successful for {context}: {result.size_bytes} bytes"
            )

        except Exception as e:
            result.errors.append(f"Unexpected validation error: {str(e)}")
            logger.error(
                f"Unexpected error during JSON validation for {context}: {e}",
                exc_info=True,
            )

        finally:
            result.parse_time_ms = (time.time() - start_time) * 1000

        return result

    def _safe_json_parse(self, json_string: str) -> Any:
        """
        Parse JSON with depth and structure limits
        """
        try:
            # Parse with standard JSON parser first
            data = json.loads(json_string)

            # Then validate structure
            self._validate_structure(data, current_depth=0)

            return data
        except RecursionError:
            raise JSONValidationError(
                f"JSON nesting depth exceeds maximum allowed depth ({self.max_depth})",
                error_type="depth_limit",
            )
        except json.JSONDecodeError as e:
            raise e  # Re-raise JSON decode errors

    def _validate_structure(self, data: Any, current_depth: int = 0) -> None:
        """
        Validate JSON structure for depth, array size, and object key limits
        """
        if current_depth > self.max_depth:
            raise JSONValidationError(
                f"JSON nesting depth ({current_depth}) exceeds maximum allowed depth ({self.max_depth})",
                error_type="depth_limit",
            )

        if isinstance(data, dict):
            if len(data) > self.max_keys:
                raise JSONValidationError(
                    f"JSON object has too many keys ({len(data)} > {self.max_keys})",
                    error_type="key_limit",
                )
            # Recursively validate nested objects
            for value in data.values():
                self._validate_structure(value, current_depth + 1)

        elif isinstance(data, list):
            if len(data) > self.max_array:
                raise JSONValidationError(
                    f"JSON array is too large ({len(data)} > {self.max_array})",
                    error_type="array_limit",
                )
            # Recursively validate array elements
            for item in data:
                self._validate_structure(item, current_depth + 1)

    def _validate_schema(self, data: Any, schema: Dict[str, Any]) -> List[str]:
        """
        Basic schema validation (can be extended with jsonschema library)
        """
        errors = []

        try:
            # For now, implement basic type and required field validation
            if isinstance(schema, dict) and isinstance(data, dict):
                # Check required fields
                required = schema.get("required", [])
                for field in required:
                    if field not in data:
                        errors.append(f"Required field '{field}' is missing")

                # Check field types
                properties = schema.get("properties", {})
                for field, field_schema in properties.items():
                    if field in data:
                        expected_type = field_schema.get("type")
                        if expected_type:
                            if not self._validate_type(data[field], expected_type):
                                errors.append(
                                    f"Field '{field}' has invalid type, expected {expected_type}"
                                )

        except Exception as e:
            errors.append(f"Schema validation error: {str(e)}")

        return errors

    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """
        Validate value type against expected type
        """
        type_mapping = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }

        expected_python_type = type_mapping.get(expected_type)
        if expected_python_type:
            return isinstance(value, expected_python_type)

        return True  # Unknown type, assume valid


# Plugin-specific validation schemas
PLUGIN_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "api_key": {"type": "string", "minLength": 1, "maxLength": 1000},
        "server_url": {"type": "string", "pattern": "^https?://.*"},
        "username": {"type": "string", "maxLength": 255},
        "password": {"type": "string", "maxLength": 1000},
        "poll_interval": {"type": "integer", "minimum": 30, "maximum": 3600},
        "timeout": {"type": "integer", "minimum": 5, "maximum": 300},
        "max_retries": {"type": "integer", "minimum": 0, "maximum": 10},
        "device_filter": {"type": "string", "maxLength": 1000},
    },
    "additionalProperties": True,  # Allow plugin-specific fields
}

# Global validator instance
json_validator = SecureJSONValidator()


def validate_plugin_config(
    config_string: str, context: str = "plugin_config"
) -> ValidationResult:
    """
    Validate plugin configuration JSON with appropriate schema

    Args:
        config_string: JSON string to validate
        context: Context for logging and error reporting

    Returns:
        ValidationResult with validation outcome
    """
    return json_validator.validate_and_parse(
        config_string, schema=PLUGIN_CONFIG_SCHEMA, context=context
    )


def safe_json_loads(
    json_string: str, max_size: int = DEFAULT_MAX_SIZE, context: str = "unknown"
) -> Any:
    """
    Safe JSON parsing with size limits - backwards compatible interface

    Args:
        json_string: JSON string to parse
        max_size: Maximum allowed size in bytes
        context: Context for logging

    Returns:
        Parsed JSON data

    Raises:
        JSONValidationError: If validation fails
    """
    validator = SecureJSONValidator(max_size=max_size)
    result = validator.validate_and_parse(json_string, context=context)

    if not result.valid:
        raise JSONValidationError(
            f"JSON validation failed: {', '.join(result.errors)}",
            error_type="validation",
            details={
                "size_bytes": result.size_bytes,
                "parse_time_ms": result.parse_time_ms,
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

    return result.data
