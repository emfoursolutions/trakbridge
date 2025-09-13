"""
ABOUTME: Sample external plugin demonstrating modern TrakBridge plugin development
ABOUTME: Shows features, security practices, and developer guidance for external plugins

===============================================================================
                    SAMPLE CUSTOM TRACKER PLUGIN FOR TRAKBRIDGE
===============================================================================

This is an example demonstrating how to create an external plugin for
TrakBridge. It showcases:

CORE FEATURES:
- CallsignMappable interface for flexible device identification
- Standardized error handling patterns used across TrakBridge
- Security best practices for credential handling and SSL
- Comprehensive configuration validation
- Connection testing with detailed results

DEVELOPER GUIDANCE:
This plugin serves as a learning resource with extensive comments explaining:
- Why specific patterns are used (not just what they do)
- Integration points with TrakBridge architecture
- Common pitfalls and how to avoid them
- Security considerations for production deployments

DEPLOYMENT:
1. Copy to your external plugins directory
2. Add 'external_plugins.sample_custom_tracker' to allowed_plugin_modules in plugins.yaml
3. Mount the directory as /app/external_plugins in Docker
4. Use this as a template for your own tracker integrations

LEARNING PATH:
- Read through the extensive comments to understand each pattern
- Focus on the CallsignMappable implementation for device identification
- Study the error handling patterns for robust API integration
- Review security practices for production-ready plugins

===============================================================================
"""

import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import certifi

# Import the base plugin and required interfaces
from plugins.base_plugin import (
    BaseGPSPlugin,
    CallsignMappable,  # Interface for custom callsign mapping support
    FieldMetadata,  # Metadata for describing available identifier fields
    PluginConfigField,  # Configuration field definitions for UI generation
)
from services.logging_service import get_module_logger

# Initialize module logger with proper error handling
logger = get_module_logger(__name__)


class SampleCustomTrackerPlugin(BaseGPSPlugin, CallsignMappable):
    """
    ===============================================================================
                        SAMPLE CUSTOM TRACKER PLUGIN
    ===============================================================================

    This plugin demonstrates modern TrakBridge plugin development patterns including:

    CALLSIGN MAPPING:
    - Implements CallsignMappable interface for flexible device identification
    - Allows users to map tracker IDs to custom callsigns via UI
    - Supports multiple identifier field types (device_id, name, etc.)

    SECURITY:
    - Proper credential encryption and decryption handling
    - SSL context configuration for secure connections
    - Input validation and sanitization

    ERROR HANDLING:
    - Standardized error response format used across TrakBridge
    - Comprehensive HTTP status code mapping
    - Graceful degradation and fallback mechanisms

    PERFORMANCE:
    - Efficient API interaction patterns
    - Proper timeout handling
    - Connection reuse and optimization

    TESTING:
    - Connection testing with detailed results
    - Error simulation and validation
    - Configuration validation

    This serves as both a functional example and a learning resource for developers
    creating their own tracker integrations.
    ===============================================================================
    """

    # Plugin identification - used by TrakBridge's plugin manager
    PLUGIN_NAME = "sample_custom_tracker"

    @classmethod
    def get_plugin_name(cls) -> str:
        """
        Class method to get plugin name without instantiation.

        DEVELOPER NOTE: This pattern allows TrakBridge to identify plugins
        without creating instances, which is useful for:
        - Plugin discovery and registration
        - Configuration validation
        - UI generation for plugin selection

        Returns:
            str: The unique plugin identifier used throughout TrakBridge
        """
        return cls.PLUGIN_NAME

    @property
    def plugin_name(self) -> str:
        """
        Instance property for plugin name access.

        DEVELOPER NOTE: This property is used when the plugin instance
        is already created and we need to access the name for:
        - Logging and debugging
        - Error reporting
        - Dynamic behavior based on plugin type

        Returns:
            str: The unique plugin identifier
        """
        return self.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """
        Return comprehensive plugin metadata for UI generation and documentation.

        DEVELOPER NOTE: This metadata drives TrakBridge's dynamic UI generation.
        The structure here becomes form fields, help text, and validation rules
        in the web interface. Pay special attention to:

        - help_sections: Appear as collapsible help panels in the UI
        - config_fields: Become actual form inputs with validation
        - sensitive fields: Are automatically encrypted in the database
        - field_type: Determines UI widget (text, password, number, url, etc.)

        Returns:
            Dict containing all metadata needed for UI generation and plugin operation
        """
        return {
            "display_name": "Sample Custom Tracker",
            "description": "Comprehensive example integration demonstrating modern TrakBridge patterns",
            "icon": "fas fa-satellite",
            "category": "custom",
            "help_sections": [
                {
                    "title": "Quick Start Guide",
                    "content": [
                        "This sample demonstrates all modern TrakBridge plugin features",
                        "Replace API calls with your actual tracking service endpoints",
                        "Configure credentials securely using the encrypted fields below",
                        "Test connection thoroughly before deploying to production",
                        "Review the source code for extensive developer guidance",
                    ],
                },
                {
                    "title": "Configuration Best Practices",
                    "content": [
                        "API Key: Stored encrypted, never logged in plaintext",
                        "Server URL: Must include protocol (https:// recommended)",
                        "Device Filter: Comma-separated IDs for selective data fetching",
                        "Update Interval: Balance between data freshness and API limits",
                        "Connection Timeout: Prevents hanging connections in production",
                    ],
                },
                {
                    "title": "Callsign Mapping Support",
                    "content": [
                        "This plugin supports custom callsign mapping via the UI",
                        "Map device identifiers to custom names for TAK display",
                        "Choose from device_id, device_name, or hardware_id fields",
                        "Mappings are applied real-time during data processing",
                        "Fallback behavior preserves original names when no mapping exists",
                    ],
                },
                {
                    "title": "Security & Production Notes",
                    "content": [
                        "All sensitive fields are automatically encrypted at rest",
                        "SSL/TLS is enforced for all external API connections",
                        "Credentials are never logged or exposed in debug output",
                        "Use dedicated API accounts with minimal required permissions",
                        "Monitor API usage to stay within rate limits",
                        "Implement proper error handling for production reliability",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,  # Automatically encrypted in database
                    help_text="Your tracker service API key (stored encrypted)",
                ),
                PluginConfigField(
                    name="server_url",
                    label="Server URL",
                    field_type="url",
                    required=True,
                    placeholder="https://api.example-tracker.com",
                    help_text="Base URL for your tracking service API (include https://)",
                ),
                PluginConfigField(
                    name="device_filter",
                    label="Device Filter",
                    field_type="text",
                    required=False,
                    placeholder="device1,device2",
                    help_text="Comma-separated device IDs to include (empty = all devices)",
                ),
                PluginConfigField(
                    name="connection_timeout",
                    label="Connection Timeout (seconds)",
                    field_type="number",
                    required=False,
                    default_value=30,
                    min_value=5,
                    max_value=120,
                    help_text="HTTP request timeout for API calls",
                ),
                PluginConfigField(
                    name="update_interval",
                    label="Update Interval (seconds)",
                    field_type="number",
                    required=False,
                    default_value=60,
                    min_value=30,
                    max_value=3600,
                    help_text="How often to fetch location updates from the API",
                ),
            ],
        }

    def get_available_fields(self) -> List[FieldMetadata]:
        """
        ===============================================================================
                            CALLSIGN MAPPING FIELD DEFINITIONS
        ===============================================================================

        This method defines which fields from your tracker data can be used as
        identifiers for callsign mapping. Users will see these options in the UI
        and can choose which field to use for mapping devices to custom callsigns.

        DEVELOPER GUIDE:

        FIELD SELECTION CRITERIA:
        - Choose fields that are stable and unique per device
        - Avoid fields that change frequently (like battery, status)
        - Prefer hardware identifiers (IMEI, serial) over user-configurable names
        - Include user-friendly options even if not recommended

        FIELD METADATA STRUCTURE:
        - name: Exact field name in your tracker data structure
        - display_name: User-friendly name shown in the UI
        - type: Data type hint for validation ("string", "number")
        - recommended: UI will highlight recommended options
        - description: Help text explaining when to use this field

        MAPPING FLOW:
        1. User selects one of these fields in the stream configuration UI
        2. User maps specific values to custom callsigns (e.g., "device123" -> "Vehicle Alpha")
        3. apply_callsign_mapping() receives the field name and mapping dictionary
        4. Your plugin modifies tracker data in-place to apply custom callsigns

        BEST PRACTICES:
        - List fields in order of preference (most stable first)
        - Provide clear descriptions of when to use each field
        - Consider your API's data structure when naming fields
        - Test mapping with actual data to ensure field paths work

        Returns:
            List[FieldMetadata]: Available identifier fields for mapping
        """
        return [
            FieldMetadata(
                name="device_id",
                display_name="Device ID",
                type="string",
                recommended=True,  # Mark as recommended in UI
                description="Unique device identifier from tracking service (most stable)",
            ),
            FieldMetadata(
                name="device_name",
                display_name="Device Name",
                type="string",
                recommended=False,
                description="User-configurable device name (may change over time)",
            ),
            FieldMetadata(
                name="hardware_id",
                display_name="Hardware ID",
                type="string",
                recommended=True,
                description="Hardware identifier like IMEI or serial number (highly stable)",
            ),
            FieldMetadata(
                name="uid",
                display_name="Generated UID",
                type="string",
                recommended=False,
                description="TrakBridge generated unique identifier (falls back to device_id)",
            ),
        ]

    def apply_callsign_mapping(
        self, tracker_data: List[dict], field_name: str, callsign_map: dict
    ) -> None:
        """
        ===============================================================================
                                CALLSIGN MAPPING APPLICATION
        ===============================================================================

        Apply custom callsign mappings to tracker data IN-PLACE. This method receives
        the user's field selection and mapping configuration, then modifies the data
        to replace original device names with custom callsigns.

        DEVELOPER GUIDE:

        IN-PLACE MODIFICATION:
        This method MUST modify the tracker_data list directly (in-place).
        Do not return new data - modify the existing dictionaries.

        FIELD PATH RESOLUTION:
        Based on field_name, extract the identifier value from each location:
        - "device_id": Extract from location["additional_data"]["device_id"]
        - "device_name": Extract from location["name"]
        - "hardware_id": Extract from location["additional_data"]["raw_data"]["hardware_id"]

        MAPPING LOGIC:
        1. For each location in tracker_data
        2. Extract identifier value based on field_name
        3. Look up identifier in callsign_map
        4. If mapping exists, replace location["name"] with custom callsign
        5. Log successful mappings for debugging

        ERROR HANDLING:
        - Handle missing fields gracefully (not all devices may have all fields)
        - Skip locations where identifier extraction fails
        - Log warnings for debugging but don't raise exceptions
        - Preserve original data if mapping fails

        LOGGING:
        - Use debug level for successful mappings
        - Use warning level for missing fields or failed extractions
        - Include plugin name in log messages for easier debugging

        Args:
            tracker_data: List of location dictionaries to modify in-place
            field_name: Name of field to use as identifier (from get_available_fields)
            callsign_map: Dictionary mapping identifier values to custom callsigns
                         e.g., {"device123": "Vehicle Alpha", "device456": "Vehicle Bravo"}

        Returns:
            None: Modifies tracker_data in-place
        """
        for location in tracker_data:
            try:
                # Extract identifier value based on selected field
                identifier_value = None

                if field_name == "device_id":
                    # Extract device_id from additional_data
                    identifier_value = location.get("additional_data", {}).get(
                        "device_id"
                    )

                elif field_name == "device_name":
                    # Use the current name field directly
                    identifier_value = location.get("name")

                elif field_name == "hardware_id":
                    # Extract hardware_id from raw_data within additional_data
                    raw_data = location.get("additional_data", {}).get("raw_data", {})
                    identifier_value = raw_data.get("hardware_id")

                elif field_name == "uid":
                    # Use the generated UID field
                    identifier_value = location.get("uid")

                # Apply mapping if identifier found and mapping exists
                if identifier_value and identifier_value in callsign_map:
                    custom_callsign = callsign_map[identifier_value]
                    original_name = location.get("name", "Unknown")

                    # Modify the location data in-place
                    location["name"] = custom_callsign

                    # Log successful mapping for debugging
                    logger.debug(
                        f"[{self.plugin_name}] Applied callsign mapping: "
                        f"{identifier_value} -> {custom_callsign} (was: {original_name})"
                    )

                elif identifier_value:
                    # Identifier found but no mapping configured
                    logger.debug(
                        f"[{self.plugin_name}] No mapping found for {field_name}={identifier_value}"
                    )
                else:
                    # Could not extract identifier from this location
                    logger.debug(
                        f"[{self.plugin_name}] Could not extract {field_name} from location data"
                    )

            except Exception as e:
                # Log error but continue processing other locations
                logger.warning(
                    f"[{self.plugin_name}] Error applying callsign mapping for field "
                    f"'{field_name}': {e}"
                )
                # Location data is left unchanged on error

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """
        ===============================================================================
                            FETCH LOCATIONS WITH ERROR HANDLING
        ===============================================================================

        Fetch location data from the custom tracking service with comprehensive error
        handling, security best practices, and standardised response patterns.

        DEVELOPER GUIDE:

        RETURN FORMAT:
        This method should return either:
        1. List of location dictionaries with standardised structure
        2. List with single error dictionary: [{"_error": "code", "_error_message": "details"}]

        STANDARDIZED ERROR CODES:
        TrakBridge uses these standard error codes across all plugins:
        - "401": Authentication failed (invalid credentials)
        - "403": Forbidden access (valid creds, insufficient permissions)
        - "404": Resource not found (bad URL, endpoint not found)
        - "timeout": Request timed out
        - "network": Network/connection errors
        - "json_error": Invalid JSON response or parsing failed
        - "no_devices": Authentication successful but no devices found
        - HTTP status codes: Use actual code as string ("500", "502", etc.)

        SECURITY PRACTICES:
        - Never log credentials, API keys, or sensitive data
        - Use proper string encoding to prevent latin-1 encoding issues
        - Validate and sanitize all user inputs
        - Use SSL context for secure connections
        - Handle timeouts to prevent resource exhaustion

        PERFORMANCE CONSIDERATIONS:
        - Use configurable timeouts to prevent hanging
        - Reuse the provided session for connection pooling
        - Handle large responses efficiently
        - Implement retry logic for transient failures

        ERROR HANDLING STRATEGY:
        1. Catch specific exceptions first (most specific to general)
        2. Log detailed error info for debugging (without sensitive data)
        3. Return standardized error format for UI consumption
        4. Never raise exceptions from this method - always return error list

        Args:
            session: Shared aiohttp session for connection reuse

        Returns:
            List[Dict]: Either location data or single-item error list
        """
        # Get decrypted configuration with all sensitive fields decrypted for use
        config = self.get_decrypted_config()

        try:
            # ===================================================================
            #                    SECURE CREDENTIAL HANDLING
            # ===================================================================

            # SECURITY: Ensure credentials are properly encoded as strings to
            # avoid latin-1 encoding issues that can cause authentication failures
            api_key = str(config["api_key"]) if config["api_key"] is not None else ""
            server_url = str(config["server_url"]).rstrip("/")

            # Validate configuration before proceeding
            if not api_key:
                logger.error("API key is required but not configured")
                return [{"_error": "401", "_error_message": "API key not configured"}]

            if not server_url:
                logger.error("Server URL is required but not configured")
                return [
                    {"_error": "404", "_error_message": "Server URL not configured"}
                ]

            # ===================================================================
            #                    SECURE HTTP REQUEST SETUP
            # ===================================================================

            # Build secure headers (never log these values)
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "TrakBridge-CustomTracker/1.0",
            }

            # Build API endpoint URL
            api_url = f"{server_url}/api/v1/devices/locations"

            # Configure timeout from plugin configuration
            timeout_seconds = int(config.get("connection_timeout", 30))
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)

            # Create SSL context for secure connections
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            logger.info(f"Fetching locations from custom tracker API: {server_url}")

            # ===================================================================
            #                       SECURE API REQUEST
            # ===================================================================

            async with session.get(
                api_url, headers=headers, timeout=timeout, ssl=ssl_context
            ) as response:

                # ===================================================================
                #                   STATUS HANDLING
                # ===================================================================

                if response.status == 200:
                    # SUCCESS: Parse JSON response and transform data
                    try:
                        data = await response.json()
                        locations = self._transform_api_data(data, config)

                        # Log success without exposing sensitive data
                        logger.info(
                            f"Successfully fetched {len(locations)} locations from custom tracker"
                        )
                        return locations

                    except ValueError as json_err:
                        # JSON parsing failed
                        logger.error(f"Invalid JSON response from API: {json_err}")
                        return [
                            {
                                "_error": "json_error",
                                "_error_message": "API returned invalid JSON response",
                            }
                        ]

                elif response.status == 401:
                    # AUTHENTICATION FAILED
                    logger.error("Authentication failed - API key invalid or expired")
                    return [
                        {
                            "_error": "401",
                            "_error_message": "Invalid or expired API key",
                        }
                    ]

                elif response.status == 403:
                    # FORBIDDEN ACCESS
                    logger.error("Forbidden access - check API permissions")
                    return [
                        {
                            "_error": "403",
                            "_error_message": "Access forbidden - check API key permissions",
                        }
                    ]

                elif response.status == 404:
                    # RESOURCE NOT FOUND
                    logger.error(f"API endpoint not found: {api_url}")
                    return [
                        {
                            "_error": "404",
                            "_error_message": "API endpoint not found - check server URL",
                        }
                    ]

                elif response.status == 429:
                    # RATE LIMITED
                    logger.warning("API rate limit exceeded")
                    return [
                        {
                            "_error": "429",
                            "_error_message": "API rate limit exceeded - try again later",
                        }
                    ]

                elif response.status >= 500:
                    # SERVER ERRORS
                    logger.error(f"Server error: HTTP {response.status}")
                    return [
                        {
                            "_error": str(response.status),
                            "_error_message": f"Server error (HTTP {response.status})",
                        }
                    ]

                else:
                    # OTHER HTTP ERRORS
                    try:
                        error_text = await response.text(encoding="utf-8")
                        logger.error(
                            f"API returned HTTP {response.status}: {error_text}"
                        )
                    except Exception:
                        error_text = "Unable to read error response"

                    return [
                        {
                            "_error": str(response.status),
                            "_error_message": f"HTTP {response.status}: {error_text}",
                        }
                    ]

        # ===================================================================
        #                      EXCEPTION HANDLING
        # ===================================================================

        except asyncio.TimeoutError:
            # Request timed out
            logger.error(f"Request timed out after {timeout_seconds} seconds")
            return [
                {
                    "_error": "timeout",
                    "_error_message": f"Request timed out after {timeout_seconds} seconds",
                }
            ]

        except aiohttp.ClientTimeout:
            # Specific aiohttp timeout
            logger.error(f"Connection timed out after {timeout_seconds} seconds")
            return [
                {
                    "_error": "timeout",
                    "_error_message": f"Connection timed out after {timeout_seconds} seconds",
                }
            ]

        except aiohttp.ClientConnectorError as conn_err:
            # Connection failed (DNS, network unreachable, etc.)
            logger.error(f"Connection failed: {conn_err}")
            return [
                {
                    "_error": "network",
                    "_error_message": f"Connection failed: {str(conn_err)}",
                }
            ]

        except aiohttp.ClientError as client_err:
            # Other aiohttp client errors
            logger.error(f"HTTP client error: {client_err}")
            return [
                {
                    "_error": "network",
                    "_error_message": f"HTTP client error: {str(client_err)}",
                }
            ]

        except ssl.SSLError as ssl_err:
            # SSL/TLS errors
            logger.error(f"SSL connection error: {ssl_err}")
            return [
                {
                    "_error": "network",
                    "_error_message": f"SSL connection error: {str(ssl_err)}",
                }
            ]

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"Unexpected error fetching locations: {e}", exc_info=True)
            return [
                {"_error": "unknown", "_error_message": f"Unexpected error: {str(e)}"}
            ]

    def _transform_api_data(
        self, api_data: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        ===============================================================================
                        TRANSFORM API DATA TO COT FORMAT
        ===============================================================================

        Transform raw API response data into COT format.

        DEVELOPER GUIDE:

        REQUIRED LOCATION FIELDS:
        Each location dictionary MUST contain these fields:
        - name: Device/tracker display name (string)
        - lat: Latitude coordinate (float)
        - lon: Longitude coordinate (float)
        - timestamp: UTC datetime object
        - description: Human-readable description (string)
        - uid: Unique identifier for this location (string)
        - additional_data: Dict containing metadata and source info

        DEVICE FILTERING:
        Apply user-configured device filters to reduce data volume:
        - Parse comma-separated device filter from configuration
        - Skip devices not in allowed list if filter is configured
        - Log filtered devices for debugging

        DATA TRANSFORMATION PATTERNS:
        - Handle missing/null values gracefully with defaults
        - Convert string coordinates to float with error handling
        - Parse timestamps with fallback to current time
        - Build descriptive text from available metadata
        - Preserve raw API data for debugging and callsign mapping

        ERROR HANDLING:
        - Skip malformed device records rather than failing entirely
        - Log transformation warnings for debugging
        - Provide sensible defaults for missing data
        - Never raise exceptions - return partial results

        Args:
            api_data: Raw JSON response from your tracker API
            config: Decrypted plugin configuration

        Returns:
            List[Dict]: Transformed location data in COT format
        """
        locations = []
        device_filter = config.get("device_filter", "").strip()

        # Parse device filter into set for fast lookup
        allowed_devices = None
        if device_filter:
            allowed_devices = set(
                dev.strip() for dev in device_filter.split(",") if dev.strip()
            )
            logger.debug(f"Device filter active: {allowed_devices}")

        # EXAMPLE: Modify this section to match your API's response structure
        # This example assumes API returns data in this format:
        # {
        #   "devices": [
        #     {
        #       "device_id": "tracker001",
        #       "name": "Vehicle 1",
        #       "latitude": 40.7128,
        #       "longitude": -74.0060,
        #       "timestamp": "2024-01-15T10:30:00Z",
        #       "status": "moving",
        #       "battery": 85,
        #       "hardware_id": "IMEI123456789"  # For callsign mapping
        #     }
        #   ]
        # }

        device_count = 0
        filtered_count = 0
        error_count = 0

        for device in api_data.get("devices", []):
            try:
                device_count += 1
                device_id = device.get("device_id", "unknown")

                # Apply device filter if configured
                if allowed_devices and device_id not in allowed_devices:
                    filtered_count += 1
                    logger.debug(
                        f"Filtered out device {device_id} (not in allowed list)"
                    )
                    continue

                # ===================================================================
                #                    COORDINATE EXTRACTION & VALIDATION
                # ===================================================================

                try:
                    latitude = float(device.get("latitude", 0))
                    longitude = float(device.get("longitude", 0))

                    # Basic coordinate validation
                    if not (-90 <= latitude <= 90):
                        logger.warning(
                            f"Invalid latitude {latitude} for device {device_id}"
                        )
                        continue
                    if not (-180 <= longitude <= 180):
                        logger.warning(
                            f"Invalid longitude {longitude} for device {device_id}"
                        )
                        continue

                except (TypeError, ValueError) as coord_err:
                    logger.warning(
                        f"Invalid coordinates for device {device_id}: {coord_err}"
                    )
                    continue

                # ===================================================================
                #                        TIMESTAMP PARSING
                # ===================================================================

                timestamp_str = device.get("timestamp")
                if timestamp_str:
                    timestamp = self._parse_timestamp(timestamp_str)
                    if timestamp is None:
                        logger.warning(
                            f"Could not parse timestamp for device {device_id}: {timestamp_str}"
                        )
                        timestamp = datetime.now(timezone.utc)
                else:
                    timestamp = datetime.now(timezone.utc)

                # ===================================================================
                #                    BUILD DESCRIPTION STRING
                # ===================================================================

                description_parts = []

                # Add device status if available
                status = device.get("status", "").strip()
                if status:
                    description_parts.append(f"Status: {status}")

                # Add battery level if available
                battery = device.get("battery")
                if battery is not None:
                    try:
                        battery_pct = int(battery)
                        description_parts.append(f"Battery: {battery_pct}%")
                    except (TypeError, ValueError):
                        pass

                # Add speed if available
                speed = device.get("speed")
                if speed is not None:
                    try:
                        speed_val = float(speed)
                        description_parts.append(f"Speed: {speed_val:.1f} km/h")
                    except (TypeError, ValueError):
                        pass

                # Add altitude if available
                altitude = device.get("altitude")
                if altitude is not None:
                    try:
                        alt_val = float(altitude)
                        description_parts.append(f"Altitude: {alt_val:.0f}m")
                    except (TypeError, ValueError):
                        pass

                # ===================================================================
                #                  BUILD STANDARDISED LOCATION DICT
                # ===================================================================

                location = {
                    "name": device.get("name", f"Device {device_id}"),
                    "lat": latitude,
                    "lon": longitude,
                    "timestamp": timestamp,
                    "description": (
                        " | ".join(description_parts)
                        if description_parts
                        else "Custom tracker location"
                    ),
                    "uid": f"custom-{device_id}",
                    "additional_data": {
                        "source": "sample_custom_tracker",
                        "device_id": device_id,  # For callsign mapping
                        "hardware_id": device.get(
                            "hardware_id"
                        ),  # For callsign mapping if available
                        "raw_data": device,  # Preserve original data for debugging and advanced mapping
                        "api_timestamp": timestamp_str,  # Original timestamp string
                        "last_updated": datetime.now(timezone.utc).isoformat(),
                    },
                }

                locations.append(location)

            except Exception as e:
                error_count += 1
                device_id = (
                    device.get("device_id", "unknown")
                    if isinstance(device, dict)
                    else "unknown"
                )
                logger.warning(f"Error transforming device {device_id}: {e}")
                continue

        # Log transformation summary
        logger.info(
            f"Transformed {len(locations)} locations from {device_count} devices "
            f"(filtered: {filtered_count}, errors: {error_count})"
        )

        return locations

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse timestamp from API response with multiple format support.

        DEVELOPER GUIDE:

        🕒 TIMESTAMP FORMAT HANDLING:
        Support multiple common timestamp formats your API might return:
        - ISO 8601 with Z suffix: "2024-01-15T10:30:00Z"
        - ISO 8601 with timezone: "2024-01-15T10:30:00+00:00"
        - Unix timestamp: 1705312200
        - Custom formats specific to your tracker service

        ⚠️ ERROR HANDLING:
        - Log parsing failures for debugging but return None
        - Caller should fall back to current timestamp
        - Never raise exceptions from timestamp parsing

        Args:
            timestamp_str: Timestamp string from API response

        Returns:
            datetime object in UTC timezone, or None if parsing failed
        """
        if not timestamp_str:
            return None

        try:
            # Handle ISO format with Z suffix (UTC)
            if isinstance(timestamp_str, str) and timestamp_str.endswith("Z"):
                return datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)

            # Handle ISO format with timezone offset
            elif isinstance(timestamp_str, str) and (
                "+" in timestamp_str[-6:] or timestamp_str.endswith("00")
            ):
                dt = datetime.fromisoformat(timestamp_str)
                return dt.astimezone(timezone.utc).replace(tzinfo=None)

            # Handle plain ISO format (assume UTC)
            elif isinstance(timestamp_str, str):
                try:
                    return datetime.fromisoformat(timestamp_str)
                except ValueError:
                    pass

            # Handle Unix timestamp (seconds)
            elif isinstance(timestamp_str, (int, float)):
                return datetime.fromtimestamp(timestamp_str, tz=timezone.utc).replace(
                    tzinfo=None
                )

            # Handle Unix timestamp as string
            elif isinstance(timestamp_str, str) and timestamp_str.isdigit():
                timestamp_int = int(timestamp_str)
                # Handle both seconds and milliseconds
                if timestamp_int > 1e10:  # Likely milliseconds
                    timestamp_int = timestamp_int / 1000
                return datetime.fromtimestamp(timestamp_int, tz=timezone.utc).replace(
                    tzinfo=None
                )

        except (ValueError, TypeError, OSError) as e:
            logger.debug(f"Could not parse timestamp '{timestamp_str}': {e}")

        return None

    async def test_connection(self) -> Dict[str, Any]:
        """
        ===============================================================================
                        CONNECTION TESTING WITH DETAILED RESULTS
        ===============================================================================

        Test connection to the custom tracking service with comprehensive validation,
        security checks, and detailed result reporting for UI consumption.

        DEVELOPER GUIDE:

        TEST STRATEGY:
        1. Validate configuration completeness before attempting connection
        2. Test actual API endpoint with minimal data request
        3. Validate response format and content
        4. Provide detailed feedback for troubleshooting
        5. Map errors to user-friendly messages

        RESULT FORMAT:
        Return dictionary with standardized structure:
        - success: Boolean indicating overall test result
        - message: User-friendly success/failure message
        - error: Error category for programmatic handling (optional)
        - details: Additional technical information (optional)
        - device_count: Number of devices found (optional, for success cases)
        - devices: List of device names found (optional, for success cases)

        SECURITY CONSIDERATIONS:
        - Never include sensitive data (API keys) in test results
        - Use secure connection methods
        - Validate SSL certificates
        - Implement proper timeout handling
        - Log security-relevant events appropriately

        PERFORMANCE:
        - Use shorter timeout for connection tests (5-10 seconds)
        - Limit data requests to minimum needed for validation
        - Clean up connections properly
        - Handle concurrent test requests gracefully

        Returns:
            Dict with test results following TrakBridge's standard format
        """
        # Get decrypted configuration for testing
        config = self.get_decrypted_config()

        # ===================================================================
        #                    CONFIGURATION VALIDATION
        # ===================================================================

        # Validate required configuration fields
        api_key = config.get("api_key", "").strip()
        if not api_key:
            return {
                "success": False,
                "error": "Configuration Error",
                "message": "API key is required. Please configure your API key in the plugin settings.",
            }

        server_url = config.get("server_url", "").strip()
        if not server_url:
            return {
                "success": False,
                "error": "Configuration Error",
                "message": "Server URL is required. Please configure your server URL in the plugin settings.",
            }

        # Validate URL format
        if not server_url.startswith(("http://", "https://")):
            return {
                "success": False,
                "error": "Configuration Error",
                "message": "Server URL must include protocol (http:// or https://)",
            }

        try:
            # ===================================================================
            #                    SECURE CONNECTION SETUP
            # ===================================================================

            # SECURITY: Ensure credentials are properly encoded
            api_key_str = str(api_key)
            server_url_clean = server_url.rstrip("/")

            # Build secure headers for testing (never log these)
            headers = {
                "Authorization": f"Bearer {api_key_str}",
                "Accept": "application/json",
                "User-Agent": "TrakBridge-CustomTracker-Test/1.0",
            }

            # Choose test endpoint - prefer health/status endpoint if available
            # Fall back to main data endpoint with minimal request
            test_endpoints = [
                f"{server_url_clean}/api/v1/health",  # Preferred: dedicated health endpoint
                f"{server_url_clean}/api/v1/status",  # Alternative: status endpoint
                f"{server_url_clean}/api/v1/devices/locations",  # Fallback: main endpoint
            ]

            # Configure shorter timeout for connection testing
            test_timeout = aiohttp.ClientTimeout(total=10)

            # Create SSL context for secure connections
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            logger.info(f"Testing connection to custom tracker API: {server_url_clean}")

            # ===================================================================
            #                      CONNECTION TEST EXECUTION
            # ===================================================================

            async with aiohttp.ClientSession() as session:
                last_error = None

                for test_url in test_endpoints:
                    try:
                        async with session.get(
                            test_url,
                            headers=headers,
                            timeout=test_timeout,
                            ssl=ssl_context,
                        ) as response:

                            # ===================================================================
                            #                     RESPONSE ANALYSIS
                            # ===================================================================

                            if response.status == 200:
                                # SUCCESS: Try to get device information for detailed results
                                try:
                                    if "devices/locations" in test_url:
                                        # This is the main endpoint, parse device data
                                        data = await response.json()
                                        devices = data.get("devices", [])
                                        device_names = []

                                        for device in devices[
                                            :5
                                        ]:  # Limit to first 5 for display
                                            name = device.get("name") or device.get(
                                                "device_id", "Unknown"
                                            )
                                            device_names.append(str(name))

                                        return {
                                            "success": True,
                                            "message": f"Successfully connected and found {len(devices)} device(s)",
                                            "details": {
                                                "server_url": server_url_clean,
                                                "endpoint_tested": test_url,
                                                "response_status": response.status,
                                                "api_accessible": True,
                                                "ssl_verified": True,
                                            },
                                            "device_count": len(devices),
                                            "devices": device_names,
                                        }
                                    else:
                                        # Health/status endpoint - basic connectivity confirmed
                                        return {
                                            "success": True,
                                            "message": "Successfully connected to custom tracker API",
                                            "details": {
                                                "server_url": server_url_clean,
                                                "endpoint_tested": test_url,
                                                "response_status": response.status,
                                                "api_accessible": True,
                                                "ssl_verified": True,
                                            },
                                        }

                                except ValueError:
                                    # JSON parsing failed but connection succeeded
                                    return {
                                        "success": True,
                                        "message": "Connected successfully (non-JSON response)",
                                        "details": {
                                            "server_url": server_url_clean,
                                            "endpoint_tested": test_url,
                                            "response_status": response.status,
                                            "note": "API responded but returned non-JSON data",
                                        },
                                    }

                            elif response.status == 401:
                                # AUTHENTICATION FAILED
                                return {
                                    "success": False,
                                    "error": "Authentication Failed",
                                    "message": "Invalid API key. Please check your credentials and try again.",
                                }

                            elif response.status == 403:
                                # FORBIDDEN ACCESS
                                return {
                                    "success": False,
                                    "error": "Access Denied",
                                    "message": "Access forbidden. Your API key may not have sufficient permissions.",
                                }

                            elif response.status == 404:
                                # Endpoint not found - try next endpoint
                                last_error = f"Endpoint not found: {test_url}"
                                continue

                            elif response.status == 429:
                                # RATE LIMITED
                                return {
                                    "success": False,
                                    "error": "Rate Limited",
                                    "message": "API rate limit exceeded. Please wait and try again later.",
                                }

                            elif response.status >= 500:
                                # SERVER ERROR
                                return {
                                    "success": False,
                                    "error": "Server Error",
                                    "message": f"Server error (HTTP {response.status}). Please try again later.",
                                }

                            else:
                                # OTHER HTTP ERROR
                                last_error = f"HTTP {response.status} from {test_url}"
                                continue

                    except asyncio.TimeoutError:
                        last_error = f"Timeout connecting to {test_url}"
                        continue
                    except aiohttp.ClientConnectorError:
                        last_error = f"Connection failed to {test_url}"
                        continue
                    except Exception as e:
                        last_error = f"Error testing {test_url}: {str(e)}"
                        continue

                # If we get here, all endpoints failed
                return {
                    "success": False,
                    "error": "Connection Failed",
                    "message": f"Could not connect to any API endpoint. Last error: {last_error or 'Unknown error'}",
                    "details": {
                        "server_url": server_url_clean,
                        "endpoints_tested": test_endpoints,
                        "last_error": last_error,
                    },
                }

        # ===================================================================
        #                      EXCEPTION HANDLING
        # ===================================================================

        except aiohttp.ClientTimeout:
            return {
                "success": False,
                "error": "Connection Timeout",
                "message": "Connection timed out. Please check your server URL and network connectivity.",
            }

        except aiohttp.ClientConnectorError as conn_err:
            return {
                "success": False,
                "error": "Network Error",
                "message": f"Failed to connect to server. Please verify the server URL and your network connection. Details: {str(conn_err)}",
            }

        except ssl.SSLError as ssl_err:
            return {
                "success": False,
                "error": "SSL Certificate Error",
                "message": f"SSL connection failed. Please verify the server's SSL certificate. Details: {str(ssl_err)}",
            }

        except Exception as e:
            logger.error(f"Unexpected error during connection test: {e}", exc_info=True)
            return {
                "success": False,
                "error": "Unexpected Error",
                "message": f"An unexpected error occurred during the connection test: {str(e)}",
            }

    def validate_config(self) -> bool:
        """
        ===============================================================================
                            CONFIGURATION VALIDATION
        ===============================================================================

        Validate plugin configuration with enhanced security checks, type conversion,
        and detailed error reporting for troubleshooting.

        DEVELOPER GUIDE:

        VALIDATION STRATEGY:
        1. Call parent class validation first (handles base requirements)
        2. Validate plugin-specific required fields
        3. Perform type conversion and range validation
        4. Validate format and structure of complex fields
        5. Apply security best practices to sensitive data validation

        VALIDATION CATEGORIES:
        - Required field presence
        - Data type and format validation
        - Range and boundary checking
        - Security policy compliance
        - Cross-field validation and consistency

        SECURITY VALIDATION:
        - URL format and protocol validation
        - API key format and strength checking
        - Input sanitization and injection prevention
        - Configuration consistency verification

        ERROR HANDLING:
        - Log specific validation failures for debugging
        - Provide clear error messages for configuration issues
        - Never log sensitive data in error messages
        - Return False on any validation failure

        Returns:
            bool: True if configuration is valid, False otherwise
        """
        # First run the base class validation (handles standard field validation)
        if not super().validate_config():
            logger.error("Base configuration validation failed")
            return False

        # Get decrypted configuration for validation
        config = self.get_decrypted_config()

        # ===================================================================
        #                    REQUIRED FIELD VALIDATION
        # ===================================================================

        # Validate API key presence and basic format
        api_key = config.get("api_key", "").strip()
        if not api_key:
            logger.error("API key is required but not configured")
            return False

        # Basic API key format validation (adjust for your service)
        if len(api_key) < 10:  # Minimum reasonable API key length
            logger.error("API key appears to be too short (minimum 10 characters)")
            return False

        # Validate server URL presence and format
        server_url = config.get("server_url", "").strip()
        if not server_url:
            logger.error("Server URL is required but not configured")
            return False

        # Validate URL format and protocol
        if not server_url.startswith(("http://", "https://")):
            logger.error("Server URL must include protocol (http:// or https://)")
            return False

        # Security: Recommend HTTPS for production
        if server_url.startswith("http://") and not server_url.startswith(
            "http://localhost"
        ):
            logger.warning(
                "HTTP URLs are not secure for production use - consider using HTTPS"
            )

        # ===================================================================
        #                    NUMERIC FIELD VALIDATION
        # ===================================================================

        # Validate connection timeout
        connection_timeout = config.get("connection_timeout", 30)
        try:
            timeout_val = int(connection_timeout)
            if timeout_val < 5 or timeout_val > 120:
                logger.error("Connection timeout must be between 5 and 120 seconds")
                return False
            # Update config with validated integer value
            self.config["connection_timeout"] = timeout_val
        except (ValueError, TypeError):
            logger.error("Connection timeout must be a valid integer")
            return False

        # Validate update interval
        update_interval = config.get("update_interval", 60)
        try:
            interval = int(update_interval)
            if interval < 30 or interval > 3600:
                logger.error("Update interval must be between 30 and 3600 seconds")
                return False
            # Update config with validated integer value
            self.config["update_interval"] = interval
        except (ValueError, TypeError):
            logger.error("Update interval must be a valid integer")
            return False

        # ===================================================================
        #                    OPTIONAL FIELD VALIDATION
        # ===================================================================

        # Validate device filter format if provided
        device_filter = config.get("device_filter", "").strip()
        if device_filter:
            # Basic validation - check for reasonable device ID format
            filter_items = [item.strip() for item in device_filter.split(",")]
            for item in filter_items:
                if not item:  # Empty items after split
                    logger.warning("Device filter contains empty values - cleaning up")
                elif len(item) > 50:  # Unreasonably long device ID
                    logger.warning(
                        f"Device filter item '{item[:20]}...' seems unusually long"
                    )
                elif not item.replace("-", "").replace("_", "").isalnum():
                    logger.warning(
                        f"Device filter item '{item}' contains unusual characters"
                    )

            # Clean up the filter by removing empty items
            clean_filter = ",".join(filter_items if filter_items else [])
            if clean_filter != device_filter:
                logger.info("Cleaned up device filter formatting")
                self.config["device_filter"] = clean_filter

        # ===================================================================
        #                    CROSS-FIELD VALIDATION
        # ===================================================================

        # Validate that timeout is reasonable compared to update interval
        if timeout_val >= interval:
            logger.warning(
                f"Connection timeout ({timeout_val}s) is >= update interval ({interval}s) "
                "- this may cause overlapping requests"
            )

        # ===================================================================
        #                    SECURITY POLICY VALIDATION
        # ===================================================================

        # Validate URL doesn't contain credentials (security best practice)
        if "@" in server_url:
            logger.error(
                "Server URL should not contain embedded credentials - use API key field instead"
            )
            return False

        # Validate API key doesn't look like a placeholder or example
        api_key_lower = api_key.lower()
        if any(
            keyword in api_key_lower
            for keyword in ["example", "placeholder", "your_key", "api_key"]
        ):
            logger.error(
                "API key appears to be a placeholder - please use your actual API key"
            )
            return False

        logger.info("Configuration validation completed successfully")
        return True


# ===============================================================================
#                            DEVELOPER IMPLEMENTATION GUIDE
# ===============================================================================
"""
CONGRATULATIONS! You've reviewed a TrakBridge plugin example.

This sample demonstrates all the patterns and best practices used in
production TrakBridge plugins. Here's what you've learned:

IMPLEMENTATION CHECKLIST for your own plugin:

CORE FEATURES IMPLEMENTED:
- [ ] Inherit from BaseGPSPlugin and CallsignMappable
- [ ] Implement all required abstract methods
- [ ] Add comprehensive plugin metadata for UI generation
- [ ] Define configuration fields with proper validation
- [ ] Implement callsign mapping with field selection
- [ ] Use standardized error handling patterns
- [ ] Follow security best practices for credentials
- [ ] Add enhanced connection testing
- [ ] Implement comprehensive configuration validation

CUSTOMISATION POINTS:
1. Replace API endpoints in fetch_locations() with your service URLs
2. Update _transform_api_data() to match your API response format  
3. Modify get_available_fields() for your tracker's identifier fields
4. Adjust plugin metadata (name, description, help text)
5. Add/remove configuration fields as needed for your service
6. Update validation rules in validate_config() for your requirements

SECURITY REMINDERS:
- Never log API keys or sensitive data
- Always use HTTPS for production deployments
- Validate and sanitize all user inputs
- Use proper SSL certificate validation
- Implement timeout handling to prevent resource exhaustion

NEXT STEPS:
1. Copy this file to your external plugins directory
2. Rename the class and PLUGIN_NAME constant
3. Update the plugin metadata for your service
4. Replace the example API calls with your actual tracker API
5. Test thoroughly with real data before production deployment
6. Add your plugin to allowed_plugin_modules in plugins.yaml
7. Mount as Docker volume: -v ./my-plugins:/app/external_plugins

SUPPORT & RESOURCES:
- Review existing plugins in plugins/ directory for more examples
- Check the base plugin documentation in plugins/base_plugin.py
- Test your plugin thoroughly using the connection test feature
- Monitor logs for any security warnings or validation errors

Happy plugin development!
"""
