# =============================================================================
# plugins/base_plugin.py - Enhanced Base Plugin Class with Metadata System
# =============================================================================

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import asyncio
import aiohttp
import logging
from datetime import datetime


class PluginConfigField:
    """Configuration field definition for plugin UI generation"""

    def __init__(self, name: str, label: str, field_type: str = "text",
                 required: bool = False, placeholder: str = "",
                 help_text: str = "", default_value: Any = None,
                 options: Optional[List[Dict[str, str]]] = None,
                 min_value: Optional[int] = None, max_value: Optional[int] = None,
                 sensitive: bool = False):
        self.name = name
        self.label = label
        self.field_type = field_type  # text, password, url, number, select, email
        self.required = required
        self.placeholder = placeholder
        self.help_text = help_text
        self.default_value = default_value
        self.options = options or []  # For select fields
        self.min_value = min_value
        self.max_value = max_value
        self.sensitive = sensitive  # For password fields

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "name": self.name,
            "label": self.label,
            "type": self.field_type,
            "required": self.required,
            "placeholder": self.placeholder,
            "help": self.help_text,
            "default": self.default_value,
            "options": self.options,
            "min": self.min_value,
            "max": self.max_value,
            "sensitive": self.sensitive
        }


class BaseGPSPlugin(ABC):
    """Enhanced base class for GPS tracking plugins with metadata system"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f'{self.__class__.__name__}')

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """Return the name of this plugin"""
        pass

    @property
    @abstractmethod
    def plugin_metadata(self) -> Dict[str, Any]:
        """
        Return plugin metadata for UI generation

        Returns:
            Dictionary containing:
            - display_name: Human-readable plugin name
            - description: Plugin description
            - icon: FontAwesome icon class
            - help_sections: List of help content sections
            - config_fields: List of PluginConfigField objects
        """
        pass

    @property
    def required_config_fields(self) -> List[str]:
        """Return list of required configuration fields (derived from metadata)"""
        return [field.name for field in self.get_config_fields() if field.required]

    def get_config_fields(self) -> List[PluginConfigField]:
        """Get configuration fields from plugin metadata"""
        metadata = self.plugin_metadata
        fields = []

        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, PluginConfigField):
                fields.append(field_data)
            elif isinstance(field_data, dict):
                # Convert dict to PluginConfigField
                fields.append(PluginConfigField(**field_data))

        return fields

    @abstractmethod
    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch location data from the GPS service

        Returns:
            List of location dictionaries with keys:
            - name: Device/tracker name
            - lat: Latitude (float)
            - lon: Longitude (float)
            - timestamp: UTC timestamp (datetime)
            - description: Optional description
            - additional_data: Dict of any additional data
        """
        pass

    def validate_config(self) -> bool:
        """Enhanced validation using plugin metadata"""
        config_fields = self.get_config_fields()

        for field in config_fields:
            field_name = field.name
            field_value = self.config.get(field_name)

            # Check required fields
            if field.required and (field_value is None or field_value == ""):
                self.logger.error(f"Missing required configuration field: {field_name}")
                return False

            # Type-specific validation
            if field_value is not None and field_value != "":
                if field.field_type in ["url"] and not str(field_value).startswith(("http://", "https://")):
                    self.logger.error(f"Field '{field_name}' must be a valid URL")
                    return False

                if field.field_type == "number":
                    try:
                        num_value = float(field_value)
                        if field.min_value is not None and num_value < field.min_value:
                            self.logger.error(f"Field '{field_name}' must be at least {field.min_value}")
                            return False
                        if field.max_value is not None and num_value > field.max_value:
                            self.logger.error(f"Field '{field_name}' must be at most {field.max_value}")
                            return False
                    except (ValueError, TypeError):
                        self.logger.error(f"Field '{field_name}' must be a valid number")
                        return False

                if field.field_type == "email" and "@" not in str(field_value):
                    self.logger.error(f"Field '{field_name}' must be a valid email address")
                    return False

        return True

    async def test_connection(self) -> Dict[str, Any]:
        """
        Enhanced connection test that returns detailed results

        Returns:
            Dictionary with:
            - success: bool
            - message: str
            - device_count: int (optional)
            - devices: List[str] (optional)
            - error: str (optional)
        """
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                locations = await self.fetch_locations(session)

                if locations is None:
                    return {
                        "success": False,
                        "error": "Failed to fetch location data",
                        "message": "Connection test failed"
                    }

                device_names = [loc.get("name", "Unknown") for loc in locations]

                return {
                    "success": True,
                    "message": f"Successfully connected and found {len(locations)} device(s)",
                    "device_count": len(locations),
                    "devices": device_names
                }

        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed"
            }