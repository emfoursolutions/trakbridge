"""
File: plugins/base_plugin.py

Description:
    Defines the abstract base class for GPS tracking plugins, providing a standard
    interface, common configuration validation, encryption support for sensitive fields,
    and integration with the persistent COT event system. Includes helper classes and
    methods to support plugin metadata, dynamic configuration UI generation, and
    asynchronous communication with TAK servers.

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: 2025-07-05
Version: 1.0.0
"""

# Standard library imports
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Third-party imports
import aiohttp

# Lazy import to avoid circular dependency
_logger_instance = None


def get_logger():
    """Get the module logger, initializing lazily to avoid circular imports"""
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger

        _logger_instance = get_module_logger(__name__)
    return _logger_instance


# For backwards compatibility - provide logger as module attribute
class _LoggerProxy:
    """Proxy that forwards all attribute access to the lazy logger"""

    def __getattr__(self, name):
        return getattr(get_logger(), name)


logger = _LoggerProxy()


@dataclass
class FieldMetadata:
    """Metadata for available identifier fields in tracker plugins"""

    name: str  # Field name in data (e.g., "imei", "device_name")
    display_name: str  # User-friendly name (e.g., "Device IMEI", "Device Name")
    type: str  # Data type ("string", "number")
    recommended: bool = False  # UI should highlight recommended fields
    description: str = ""  # Optional help text for users


class CallsignMappable(ABC):
    """
    Optional interface for plugins that support custom callsign mapping.

    Plugins can choose to implement this interface to enable callsign mapping
    functionality. If not implemented, plugins will use their existing
    hardcoded extraction behavior as fallback.
    """

    @abstractmethod
    def get_available_fields(self) -> List[FieldMetadata]:
        """
        Return available identifier fields for callsign mapping.

        Returns:
            List of FieldMetadata objects describing available fields
            that can be used as identifiers for callsign mapping.
        """
        pass

    @abstractmethod
    def apply_callsign_mapping(
        self, tracker_data: List[dict], field_name: str, callsign_map: dict
    ) -> None:
        """
        Apply callsign mappings to tracker data in-place.

        Args:
            tracker_data: List of tracker dictionaries to modify
            field_name: Name of field to use as identifier
            callsign_map: Dictionary mapping identifier values to custom callsigns
        """
        pass


class PluginConfigField:
    """Configuration field definition for plugin UI generation"""

    def __init__(
        self,
        name: str,
        label: str,
        field_type: str = "text",
        required: bool = False,
        placeholder: str = "",
        help_text: str = "",
        default_value: Any = None,
        options: Optional[List[Dict[str, str]]] = None,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        sensitive: bool = False,
    ):
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
        self.sensitive = sensitive  # For password fields and other sensitive data

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
            "sensitive": self.sensitive,
        }


class BaseGPSPlugin(ABC):
    """Enhanced base class for GPS tracking plugins with persistent COT support"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        from services.encryption_service import EncryptionService

        self.encryption_service = EncryptionService()

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
            - category: Plugin category
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

    def get_sensitive_fields(self) -> List[str]:
        """Get list of sensitive field names from plugin metadata"""
        sensitive_fields = []
        config_fields = self.get_config_fields()

        for field in config_fields:
            if field.sensitive:
                sensitive_fields.append(field.name)

        return sensitive_fields

    def get_decrypted_config(self) -> Dict[str, Any]:
        """Get plugin configuration with sensitive fields decrypted for use"""
        sensitive_fields = self.get_sensitive_fields()
        if not sensitive_fields:
            return self.config.copy()

        decrypted_config = self.config.copy()

        for field_name in sensitive_fields:
            if field_name in decrypted_config:
                value = decrypted_config[field_name]
                if value:
                    try:
                        decrypted_config[field_name] = self.encryption_service.decrypt_value(
                            str(value)
                        )
                    except Exception as e:
                        get_logger().error(f"Failed to decrypt field '{field_name}': {e}")
                        # Keep original value if decryption fails

        return decrypted_config

    @staticmethod
    def encrypt_config_for_storage(plugin_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encrypt sensitive fields in configuration before storing in database

        Args:
            plugin_type: The plugin type name
            config: Configuration dictionary

        Returns:
            Configuration with sensitive fields encrypted
        """
        from plugins.plugin_manager import get_plugin_manager
        from services.encryption_service import EncryptionService

        plugin_manager = get_plugin_manager()
        metadata = plugin_manager.get_plugin_metadata(plugin_type)
        if not metadata:
            return config

        sensitive_fields = []
        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, dict) and field_data.get("sensitive"):
                sensitive_fields.append(field_data["name"])
            elif hasattr(field_data, "sensitive") and field_data.sensitive:
                sensitive_fields.append(field_data.name)

        if sensitive_fields:
            encryption_service = EncryptionService()
            return encryption_service.encrypt_config(config, sensitive_fields)

        return config

    @staticmethod
    def decrypt_config_from_storage(plugin_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decrypt sensitive fields in configuration after loading from database

        Args:
            plugin_type: The plugin type name
            config: Configuration dictionary with encrypted fields

        Returns:
            Configuration with sensitive fields decrypted
        """
        from plugins.plugin_manager import get_plugin_manager
        from services.encryption_service import EncryptionService

        plugin_manager = get_plugin_manager()
        metadata = plugin_manager.get_plugin_metadata(plugin_type)
        if not metadata:
            return config

        sensitive_fields = []
        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, dict) and field_data.get("sensitive"):
                sensitive_fields.append(field_data["name"])
            elif hasattr(field_data, "sensitive") and field_data.sensitive:
                sensitive_fields.append(field_data.name)

        if sensitive_fields:
            encryption_service = EncryptionService()
            return encryption_service.decrypt_config(config, sensitive_fields)

        return config

    def supports_callsign_mapping(self) -> bool:
        """
        Check if this plugin implements the CallsignMappable interface.

        Returns:
            True if plugin supports callsign mapping, False otherwise
        """
        return isinstance(self, CallsignMappable)

    def get_callsign_fields(self) -> List[FieldMetadata]:
        """
        Get available fields for callsign mapping with fallback behavior.

        Returns:
            List of FieldMetadata if plugin implements CallsignMappable,
            empty list otherwise for graceful degradation
        """
        if self.supports_callsign_mapping():
            return self.get_available_fields()
        return []

    def apply_callsign_mappings(
        self, tracker_data: List[dict], field_name: str, callsign_map: dict
    ) -> bool:
        """
        Apply callsign mappings with fallback behavior.

        Args:
            tracker_data: List of tracker dictionaries to modify
            field_name: Name of field to use as identifier
            callsign_map: Dictionary mapping identifier values to custom callsigns

        Returns:
            True if mapping was applied, False if fallback behavior should be used
        """
        if self.supports_callsign_mapping() and callsign_map:
            try:
                self.apply_callsign_mapping(tracker_data, field_name, callsign_map)
                return True
            except Exception as e:
                get_logger().error(f"[{self.plugin_name}] Failed to apply callsign mapping: {e}")
                return False
        return False

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
            - cot_type: Optional COT type (only used when cot_type_mode is "per_point")
        """
        pass

    async def process_and_enqueue_locations(self, locations: List[Dict[str, Any]], stream) -> None:
        """
        Process locations and enqueue COT events using persistent COT service.

        This method replaces direct TAK server connections with queue-based messaging
        through the persistent COT service.

        Args:
            locations: List of location dictionaries from fetch_locations()
            stream: Stream model instance (must have tak_server_id, cot_type, cot_stale_time)
        """
        if not locations:
            get_logger().debug("No locations to process")
            return

        try:
            # Import here to avoid circular imports
            from services.cot_service import EnhancedCOTService, cot_service

            # Ensure persistent worker is running for this TAK server
            if hasattr(stream, "tak_server_id") and stream.tak_server_id:
                await cot_service.ensure_worker_running(stream.tak_server_id)

            # Create COT events from locations
            cot_events = await EnhancedCOTService().create_cot_events(
                locations,
                cot_type=getattr(stream, "cot_type", "a-f-G-U-C"),
                stale_time=getattr(stream, "cot_stale_time", 300),
            )

            # Enqueue events to persistent worker
            enqueued_count = 0
            for event in cot_events:
                if hasattr(stream, "tak_server_id") and stream.tak_server_id:
                    cot_service.enqueue_event(event, stream.tak_server_id)
                    enqueued_count += 1
                else:
                    get_logger().warning(
                        f"Stream {getattr(stream, 'id', 'unknown')} has no TAK server ID"
                    )

            get_logger().info(
                f"[{self.plugin_name}] Enqueued {enqueued_count} "
                f"COT events for stream {getattr(stream, 'id', 'unknown')}"
            )

        except Exception as e:
            get_logger().error(
                f"[{self.plugin_name}] Error processing and enqueuing locations: {e}",
                exc_info=True,
            )

    def validate_config(self) -> bool:
        """Enhanced validation using plugin metadata"""
        config_fields = self.get_config_fields()

        # Use decrypted config for validation
        config_to_validate = self.get_decrypted_config()

        for field in config_fields:
            field_name = field.name
            field_value = config_to_validate.get(field_name)

            # Check required fields
            if field.required and (field_value is None or field_value == ""):
                get_logger().error(f"Missing required configuration field: {field_name}")
                return False

            # Type-specific validation
            if field_value is not None and field_value != "":
                if field.field_type in ["url"] and not str(field_value).startswith(
                    ("http://", "https://")
                ):
                    get_logger().error(f"Field '{field_name}' must be a valid URL")
                    return False

                if field.field_type == "number":
                    try:
                        num_value = float(field_value)
                        if field.min_value is not None and num_value < field.min_value:
                            get_logger().error(
                                f"Field '{field_name}' must be at least {field.min_value}"
                            )
                            return False
                        if field.max_value is not None and num_value > field.max_value:
                            get_logger().error(
                                f"Field '{field_name}' must be at most {field.max_value}"
                            )
                            return False
                    except (ValueError, TypeError):
                        get_logger().error(f"Field '{field_name}' must be a valid number")
                        return False

                if field.field_type == "email" and "@" not in str(field_value):
                    get_logger().error(f"Field '{field_name}' must be a valid email address")
                    return False

        return True

    async def health_check(self) -> dict:
        """
        Return a health status dict for the plugin.
        Override in subclasses for plugin-specific checks.
        """
        try:
            # Default: use test_connection if available
            if hasattr(self, "test_connection"):
                result = await self.test_connection()
                status = "healthy" if result.get("success") else "unhealthy"
                return {"status": status, "details": result}
            return {"status": "unknown", "details": "No health check implemented"}
        except Exception as e:
            get_logger().error(
                f"[{self.__class__.__name__}] health_check failed: {e}", exc_info=True
            )
            return {"status": "unhealthy", "details": str(e)}

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
                        "error": "Failed: Unable to fetch location data",
                        "message": "Connection test failed",
                    }

                # Check if the plugin returned an error indicator
                if (
                    locations
                    and len(locations) > 0
                    and isinstance(locations[0], dict)
                    and "_error" in locations[0]
                ):
                    error_info = locations[0]
                    error_code = error_info.get("_error", "unknown")
                    # error_message = error_info.get("_error_message", "Unknown error")

                    # Map error codes to specific messages
                    if error_code == "401":
                        return {
                            "success": False,
                            "error": "Invalid Credentials",
                            "message": "Authentication failed. Check your username and password.",
                        }
                    elif error_code == "403":
                        return {
                            "success": False,
                            "error": "Unauthorised Access",
                            "message": "Access forbidden. Check your user permissions.",
                        }
                    elif error_code == "404":
                        return {
                            "success": False,
                            "error": "Invalid URL or API End Point",
                            "message": "Resource not found. Check the server URL and API endpoint.",
                        }
                    elif error_code == "500":
                        return {
                            "success": False,
                            "error": "Server Error",
                            "message": "Server error occurred. Please try again later.",
                        }
                    elif error_code == "json_error":
                        return {
                            "success": False,
                            "error": "Invalid Feed ID or Password",
                            "message": "API returned an error. Check your feed ID and password.",
                        }
                    elif error_code == "connection_failed":
                        return {
                            "success": False,
                            "error": "Connection Failed - Unknown Error",
                            "message": "Failed to fetch KML feed. "
                            "Check your credentials and feed URL.",
                        }
                    elif error_code == "invalid_url":
                        return {
                            "success": False,
                            "error": "Invalid URL or API End Point",
                            "message": "Invalid KML feed URL. "
                            "Check the URL and ensure it's a feed.",
                        }
                    elif error_code == "no_devices":
                        return {
                            "success": False,
                            "error": "No Devices Found",
                            "message": "Successfully connected. " "No devices returned.",
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {error_code} Error",
                            "message": f"HTTP error occurred: {error_code}",
                        }

                # Check if we got an empty list - this could indicate authentication failure
                if len(locations) == 0:
                    return {
                        "success": False,
                        "error": "Invalid Credentials or No Devices Found",
                        "message": "No devices found. "
                        "This usually indicates authentication or permission issues.",
                    }

                device_names = [loc.get("name", "Unknown") for loc in locations]

                return {
                    "success": True,
                    "message": f"Successfully connected and found {len(locations)} device(s)",
                    "device_count": len(locations),
                    "devices": device_names,
                }

        except Exception as e:
            get_logger().error(
                f"[{self.__class__.__name__}] Connection test failed: {e}",
                exc_info=True,
                extra={
                    "plugin": self.__class__.__name__,
                    "operation": "test_connection",
                },
            )
            return {
                "success": False,
                "error": f"{str(e)}",
                "message": "Connection test failed",
            }
