"""
File: plugins/spot_plugin.py

Description:
    Plugin implementation for fetching and processing location data from SPOT Satellite trackers.
    Connects to the SPOT public feed API using a feed ID and optional password, supports
    configuration validation specific to SPOT, and provides detailed metadata for UI integration.
    Implements asynchronous fetching of location messages, parses and standardizes the data,
    and supports connection testing with detailed results. Designed to integrate with the
    BaseGPSPlugin framework, supporting secure config handling and logging.

Key features:
    - Fetches the latest location updates from SPOT API
    - Parses and normalizes raw SPOT message data into a common location format
    - Provides user-friendly setup and help instructions as metadata
    - Validates SPOT-specific configuration parameters
    - Supports async connection testing with error handling and feedback

Author: Emfour Solutions
Created: 2025-07-05
"""

# Standard library imports
import logging
import ssl
from datetime import datetime
from typing import Any, Dict, List

# Third-party imports
import aiohttp
import certifi

# Local application imports
from plugins.base_plugin import (
    BaseGPSPlugin,
    CallsignMappable,
    FieldMetadata,
    PluginConfigField,
)
from services.logging_service import get_module_logger

# Module-level logger
logger = get_module_logger(__name__)


class SpotPlugin(BaseGPSPlugin, CallsignMappable):
    """Plugin for fetching location data from SPOT Satellite trackers"""

    # Class-level plugin name for easier discovery
    PLUGIN_NAME = "spot"

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        """Class method to get plugin name without instantiation"""
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for UI generation"""
        return {
            "display_name": "SPOT Satellite",
            "description": "Connect to SPOT satellite trackers via their web API",
            "icon": "fas fa-satellite",
            "category": "tracker",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Log in to your SPOT account at findmespot.com",
                        "Go to 'Shared Page' settings in your account",
                        "Enable the shared page for your SPOT device",
                        "Copy the Feed ID from the shared page URL",
                        "Set a password if you want to protect your feed (optional)",
                    ],
                },
                {
                    "title": "Important Notes",
                    "content": [
                        "Feed updates depend on your SPOT device tracking settings",
                        "Connection may take 15-30 seconds to establish",
                        "Maximum 200 location points can be fetched per request",
                        "Feed password is only required if you've set one in your SPOT account",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="feed_id",
                    label="SPOT Feed ID",
                    field_type="text",
                    required=True,
                    placeholder="0abcdef1234567890abcdef123456789",
                    help_text="Your SPOT device feed ID from your SPOT account shared page",
                ),
                PluginConfigField(
                    name="feed_password",
                    label="Feed Password",
                    field_type="password",
                    required=False,
                    sensitive=True,
                    help_text="Password if your SPOT feed is password protected "
                    "(leave blank if not protected)",
                ),
                PluginConfigField(
                    name="max_results",
                    label="Maximum Results",
                    field_type="number",
                    required=False,
                    default_value=50,
                    min_value=1,
                    max_value=200,
                    help_text="Maximum number of location points to fetch per request",
                ),
            ],
        }

    def get_available_fields(self) -> List[FieldMetadata]:
        """Return available identifier fields for callsign mapping"""
        return [
            FieldMetadata(
                name="messenger_name",
                display_name="Device Name",
                type="string",
                recommended=True,
                description="SPOT device messenger name (most stable identifier)",
            ),
            FieldMetadata(
                name="feed_id",
                display_name="Feed ID",
                type="string",
                recommended=False,
                description="SPOT feed ID from configuration",
            ),
            FieldMetadata(
                name="device_id",
                display_name="Device ID",
                type="string",
                recommended=False,
                description="SPOT internal device ID from message data",
            ),
        ]

    def apply_callsign_mapping(
        self, tracker_data: List[dict], field_name: str, callsign_map: dict
    ) -> None:
        """Apply callsign mappings to SPOT tracker data in-place"""
        for location in tracker_data:
            # Get identifier value based on selected field
            identifier_value = None

            if field_name == "messenger_name":
                # Extract messenger name from additional_data
                identifier_value = (
                    location.get("additional_data", {})
                    .get("raw_message", {})
                    .get("messengerName")
                )
                # Fallback to name field if raw message not available
                if not identifier_value:
                    identifier_value = location.get("name")
            elif field_name == "feed_id":
                # Extract feed_id from additional_data
                identifier_value = location.get("additional_data", {}).get("feed_id")
            elif field_name == "device_id":
                # Extract device ID from raw message data
                identifier_value = (
                    location.get("additional_data", {}).get("raw_message", {}).get("id")
                )

            # Apply mapping if identifier found and mapping exists
            if identifier_value and identifier_value in callsign_map:
                custom_callsign = callsign_map[identifier_value]
                location["name"] = custom_callsign
                logger.debug(
                    f"[SPOT] Applied callsign mapping: {identifier_value} -> {custom_callsign}"
                )

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """
        Fetch location data from SPOT API

        Returns:
            List of location dictionaries with standardized format
        """
        decrypted_config = self.get_decrypted_config()
        try:

            feed_id = decrypted_config["feed_id"]
            feed_password = decrypted_config["feed_password"]
            max_results = decrypted_config["max_results"]

            # Create SSL context for certificate verification
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            # Build SPOT API URL
            base_url = "https://api.findmespot.com/spot-main-web/consumer/rest-api/2.0/public/feed"
            url = f"{base_url}/{feed_id}/message.json"

            params = {}
            if feed_password:
                params["feedPassword"] = feed_password
            if max_results:
                params["limit"] = max_results

            logger.info(f"Fetching SPOT data from feed ID: {feed_id}")

            async with session.get(url, params=params, ssl=ssl_context) as response:
                if response.status == 200:
                    data = await response.json()
                    messages = self._parse_spot_response(data)

                    if not messages:
                        # Check if this was due to a JSON error (like feed not found)
                        if "response" in data and "errors" in data.get("response", {}):
                            # Extract the actual error code from the response
                            errors = (
                                data.get("response", {})
                                .get("errors", {})
                                .get("error", {})
                            )
                            if isinstance(errors, dict):
                                error_code = errors.get("code", "Unknown")
                                error_text = errors.get("text", "Unknown error")

                                # Handle E-0195 as success (no devices found)
                                if error_code == "E-0195":
                                    logger.info(
                                        f"SPOT API: Authentication successful "
                                        f"but no devices found ({error_text})"
                                    )
                                    return [
                                        {
                                            "_error": "no_devices",
                                            "_error_message": (
                                                f"SPOT API error: {error_code} - {error_text}"
                                            ),
                                        }
                                    ]

                                # Map other error codes
                                mapped_error_code = self._map_spot_error_code(
                                    error_code
                                )
                                return [
                                    {
                                        "_error": mapped_error_code,
                                        "_error_message": (
                                            f"SPOT API error: {error_code} - {error_text}"
                                        ),
                                    }
                                ]
                            else:
                                return [
                                    {
                                        "_error": "json_error",
                                        "_error_message": "SPOT API returned error in response",
                                    }
                                ]
                        else:
                            logger.info("No messages found from SPOT")
                            return []

                    # Find the newest message by timestamp
                    newest_message = max(
                        messages,
                        key=lambda msg: datetime.fromisoformat(
                            msg["dateTime"].replace("Z", "+00:00")
                        ),
                    )

                    # Convert to standardized location format
                    location = {
                        "uid": (
                            f"{newest_message.get('messengerName', f'SPOT-{feed_id[:8]}')}"
                            f"-{newest_message['id']}"
                        ),
                        "name": newest_message.get(
                            "messengerName", f"SPOT-{feed_id[:8]}"
                        ),
                        "lat": float(newest_message["latitude"]),
                        "lon": float(newest_message["longitude"]),
                        "timestamp": datetime.fromisoformat(
                            newest_message["dateTime"].replace("Z", "+00:00")
                        ),
                        "description": self._build_description(newest_message),
                        "additional_data": {
                            "source": "spot",
                            "message_type": newest_message.get("messageType"),
                            "battery_state": newest_message.get("batteryState"),
                            "raw_message": newest_message,
                        },
                    }

                    logger.info(
                        f"Successfully fetched newest location from SPOT "
                        f"(timestamp: {location['timestamp']})"
                    )
                    return [location]

                elif response.status == 401:
                    logger.error(
                        "Unauthorized access to SPOT feed. Check feed password."
                    )
                    return [{"_error": "401", "_error_message": "Unauthorized access"}]
                elif response.status == 404:
                    logger.error("SPOT feed not found. Check feed ID.")
                    return [{"_error": "404", "_error_message": "Resource not found"}]
                else:
                    logger.error(f"Error fetching SPOT data: HTTP {response.status}")
                    error_text = await response.text(encoding="utf-8")
                    logger.debug(f"Response: {error_text}")
                    return [
                        {
                            "_error": str(response.status),
                            "_error_message": f"HTTP {response.status} error",
                        }
                    ]

        except Exception as e:
            logger.error(f"Error fetching SPOT locations: {e}")
            return []

    @staticmethod
    def _map_spot_error_code(spot_error_code: str) -> str:
        """
        Map SPOT API error codes to standard error codes used by the base plugin

        SPOT API Error Codes:
        - E-0195: Authentication successful but no devices found -> treated as success (no mapping)
        - E-0173: Authentication failed, incorrect password -> maps to '401'
        - E-0160: Feed ID not found -> maps to '404'

        Args:
            spot_error_code: SPOT API error code (e.g., 'E-0195', 'E-0173', 'E-0160')

        Returns:
            Standard error code that the base plugin understands ('401', '404', or 'json_error')
        """
        error_mapping = {
            "E-0173": "401",  # Authentication failed, incorrect password
            "E-0160": "404",  # Feed ID not found
        }

        return error_mapping.get(spot_error_code, "json_error")

    def _parse_spot_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse SPOT API response and extract messages

        Args:
            data: Raw JSON response from SPOT API

        Returns:
            List of message dictionaries
        """
        try:
            # SPOT API structure: response.feedMessageResponse.messages.message
            feed_response = data.get("response", {}).get("feedMessageResponse", {})

            if "errors" in feed_response:
                errors = feed_response["errors"]["error"]
                if isinstance(errors, list):
                    for error in errors:
                        error_code = error.get("code", "Unknown")
                        error_text = error.get("text", "Unknown error")
                        error_desc = error.get("description", "Unknown error")
                        logger.error(
                            f"SPOT API error {error_code}: {error_text} - {error_desc}"
                        )
                else:
                    error_code = errors.get("code", "Unknown")
                    error_text = errors.get("text", "Unknown error")
                    error_desc = errors.get("description", "Unknown error")
                    logger.error(
                        f"SPOT API error {error_code}: {error_text} - {error_desc}"
                    )

                    # Handle E-0195 as success (no devices found)
                    if error_code == "E-0195":
                        logger.info(
                            f"SPOT API: Authentication successful but no devices found ({error_text})"
                        )
                        return [
                            {
                                "_error": "no_devices",
                                "_error_message": f"SPOT API error: {error_code} - {error_text}",
                            }
                        ]

                    # Map other error codes
                    mapped_error_code = self._map_spot_error_code(error_code)
                    return [
                        {
                            "_error": mapped_error_code,
                            "_error_message": f"SPOT API error: {error_code} - {error_text}",
                        }
                    ]

            messages_container = feed_response.get("messages", {})
            messages = messages_container.get("message", [])

            # Ensure messages is a list (API returns single dict if only one message)
            if isinstance(messages, dict):
                messages = [messages]

            # Sort by date (newest first)
            messages.sort(key=lambda x: x.get("dateTime", ""), reverse=True)

            logger.info(f"Parsed {len(messages)} messages from SPOT response")
            return messages

        except Exception as e:
            logger.error(f"Error parsing SPOT response: {e}")
            return []

    @staticmethod
    def _build_description(message: Dict[str, Any]) -> str:
        """Build a human-readable description for the location point"""
        parts = []

        # Message type
        msg_type = message.get("messageType", "Unknown")
        parts.append(f"Type: {msg_type}")

        # Battery state
        battery = message.get("batteryState")
        if battery:
            parts.append(f"Battery: {battery}")

        # Message content if available
        msg_content = message.get("messageContent")
        if msg_content:
            parts.append(f"Message: {msg_content}")

        # Altitude if available
        altitude = message.get("altitude")
        if altitude:
            parts.append(f"Altitude: {altitude}m")

        return " | ".join(parts) if parts else "SPOT location update"

    def validate_config(self) -> bool:
        """
        Enhanced validation for SPOT-specific configuration
        """
        # Use the standard base class validation
        if not super().validate_config():
            return False

        # Additional SPOT-specific validation
        feed_id = self.config.get("feed_id", "")
        if len(feed_id) < 32:  # SPOT feed IDs are typically 32+ characters
            logger.warning("SPOT feed ID seems unusually short")

        # Validate max_results if provided
        max_results = self.config.get("max_results")
        if max_results is not None:
            try:
                max_results = int(max_results)
                if max_results < 1 or max_results > 200:
                    logger.error("max_results must be between 1 and 200")
                    return False
                # Update config with validated integer value
                self.config["max_results"] = max_results
            except (ValueError, TypeError):
                logger.error("max_results must be a valid integer")
                return False

        return True
