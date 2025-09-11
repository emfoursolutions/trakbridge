"""
file: utils/config_manager.py
file: Configuration management utilities with validation, auto-repair, and fallback capabilities
"""

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from utils.json_validator import JSONValidationError, safe_json_loads

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails"""

    def __init__(self, message: str, file_path: str = None, field: str = None):
        self.message = message
        self.file_path = file_path
        self.field = field
        super().__init__(self.build_message())

    def build_message(self) -> str:
        """Build detailed error message"""
        msg = f"Configuration Error: {self.message}"
        if self.file_path:
            msg += f" in file '{self.file_path}'"
        if self.field:
            msg += f" at field '{self.field}'"
        return msg


class ConfigManager:
    """
    Comprehensive configuration management with validation, auto-repair, and fallback.

    Features:
    - YAML syntax validation before loading
    - Auto-replacement of corrupted files with container defaults
    - Required field validation for each config file type
    - Graceful fallback to container defaults on errors
    - Detailed error reporting with actionable messages
    - Configuration backup and recovery
    """

    def __init__(
        self,
        external_config_dir: str = "external_config",
        container_config_dir: str = "config/settings",
        backup_dir: str = "backups",
    ):
        self.external_config_dir = Path(external_config_dir)
        self.container_config_dir = Path(container_config_dir)
        self.backup_dir = Path(backup_dir)

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Configuration file schemas - defines required fields for validation
        self.schemas = {
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

    def load_config_safe(
        self, config_name: str, required_fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Safely load a configuration file with validation, auto-repair, and fallback.

        Args:
            config_name: Name of the config file (e.g., "plugins.yaml")
            required_fields: Optional list of required top-level fields

        Returns:
            Dictionary containing the configuration data

        Raises:
            ConfigValidationError: If configuration is invalid and cannot be repaired
        """
        external_path = self.external_config_dir / config_name
        container_path = self.container_config_dir / config_name

        # Try to load external config first
        if external_path.exists():
            try:
                config_data = self._load_and_validate_file(
                    external_path, config_name, required_fields
                )
                logger.info(f"Successfully loaded external config: {external_path}")
                return config_data
            except Exception as e:
                logger.error(f"External config failed validation: {external_path} - {e}")

                # Backup corrupted file
                self._backup_corrupted_file(external_path, str(e))

                # Auto-repair: replace with container default
                if container_path.exists():
                    logger.info(
                        f"Auto-repairing: replacing corrupted {external_path} with container default"
                    )
                    try:
                        shutil.copy2(container_path, external_path)
                        config_data = self._load_and_validate_file(
                            external_path, config_name, required_fields
                        )
                        logger.info(f"Auto-repair successful for {config_name}")
                        return config_data
                    except Exception as repair_error:
                        logger.error(f"Auto-repair failed: {repair_error}")

        # Fall back to container default
        if container_path.exists():
            try:
                config_data = self._load_and_validate_file(
                    container_path, config_name, required_fields
                )
                logger.info(f"Using container default config: {container_path}")
                return config_data
            except Exception as e:
                logger.error(f"Container default config failed: {container_path} - {e}")

        # Final fallback: minimal default configuration
        logger.warning(f"Using minimal default configuration for {config_name}")
        return self._get_minimal_default_config(config_name)

    def _load_and_validate_file(
        self,
        file_path: Path,
        config_name: str,
        required_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Load and validate a single configuration file.

        Args:
            file_path: Path to the configuration file
            config_name: Name of the config file for error reporting
            required_fields: Optional list of required top-level fields

        Returns:
            Dictionary containing validated configuration data

        Raises:
            ConfigValidationError: If validation fails
        """
        try:
            # Step 1: YAML syntax validation
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                raise ConfigValidationError(f"Configuration file is empty", str(file_path))

            # Parse YAML with detailed error reporting
            try:
                config_data = yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise ConfigValidationError(f"Invalid YAML syntax: {e}", str(file_path))

            # Step 2: Basic structure validation
            if config_data is None:
                raise ConfigValidationError(
                    "Configuration file parsed to None (possibly empty or invalid YAML)",
                    str(file_path),
                )

            if not isinstance(config_data, dict):
                raise ConfigValidationError(
                    f"Configuration must be a dictionary, got {type(config_data).__name__}",
                    str(file_path),
                )

            # Step 3: Required fields validation
            if required_fields:
                for field in required_fields:
                    if field not in config_data:
                        raise ConfigValidationError(
                            f"Required field '{field}' is missing",
                            str(file_path),
                            field,
                        )

            # Step 4: Schema validation (if available)
            if config_name in self.schemas:
                self._validate_schema(config_data, self.schemas[config_name], str(file_path))

            return config_data

        except ConfigValidationError:
            raise
        except Exception as e:
            raise ConfigValidationError(
                f"Unexpected error loading configuration: {e}", str(file_path)
            )

    def _validate_schema(self, data: Any, schema: Dict[str, Any], file_path: str):
        """Basic schema validation (simplified implementation)"""
        if schema.get("type") == "object" and not isinstance(data, dict):
            raise ConfigValidationError(f"Expected object, got {type(data).__name__}", file_path)

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

    def _backup_corrupted_file(self, file_path: Path, error_message: str):
        """Backup a corrupted configuration file with timestamp and error info"""
        if not file_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.name}.corrupted.{timestamp}"
        backup_path = self.backup_dir / backup_name

        try:
            shutil.copy2(file_path, backup_path)

            # Write error info alongside backup
            error_file = backup_path.with_suffix(backup_path.suffix + ".error")
            with open(error_file, "w") as f:
                f.write(f"Backup created: {datetime.now().isoformat()}\n")
                f.write(f"Original file: {file_path}\n")
                f.write(f"Error: {error_message}\n")

            logger.info(f"Backed up corrupted config to: {backup_path}")

        except Exception as e:
            logger.warning(f"Failed to backup corrupted config: {e}")

    def _get_minimal_default_config(self, config_name: str) -> Dict[str, Any]:
        """Provide minimal default configuration when all else fails"""
        defaults = {
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

        return defaults.get(config_name, {})

    def validate_all_configs(self) -> Dict[str, Union[bool, str]]:
        """
        Validate all configuration files and return status report.

        Returns:
            Dictionary mapping config names to validation status
        """
        results = {}

        # Get list of all config files that should exist
        config_files = []
        if self.container_config_dir.exists():
            config_files = [f.name for f in self.container_config_dir.glob("*.yaml")]

        for config_name in config_files:
            try:
                self.load_config_safe(config_name)
                results[config_name] = True
            except Exception as e:
                results[config_name] = str(e)

        return results

    def get_config_status_summary(self) -> str:
        """Get a human-readable summary of configuration status"""
        results = self.validate_all_configs()

        total = len(results)
        passed = len([r for r in results.values() if r is True])
        failed = total - passed

        summary = [
            f"Configuration Status: {passed}/{total} files valid",
        ]

        if failed > 0:
            summary.append("Failed configurations:")
            for config_name, result in results.items():
                if result is not True:
                    summary.append(f"  ❌ {config_name}: {result}")

        return "\n".join(summary)


# Global instance for easy import
config_manager = ConfigManager()
