# =============================================================================
# plugins/spot_plugin.py - SPOT Satellite Tracker Plugin
# =============================================================================

from typing import List, Dict, Any
import aiohttp
import asyncio
import logging
from datetime import datetime
import json
import ssl
import certifi
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField


class SpotPlugin(BaseGPSPlugin):
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
            "category": "satellite",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Log in to your SPOT account at findmespot.com",
                        "Go to 'Shared Page' settings in your account",
                        "Enable the shared page for your SPOT device",
                        "Copy the Feed ID from the shared page URL",
                        "Set a password if you want to protect your feed (optional)"
                    ]
                },
                {
                    "title": "Important Notes",
                    "content": [
                        "Feed updates depend on your SPOT device tracking settings",
                        "Connection may take 15-30 seconds to establish",
                        "Maximum 200 location points can be fetched per request",
                        "Feed password is only required if you've set one in your SPOT account"
                    ]
                }
            ],
            "config_fields": [
                PluginConfigField(
                    name="feed_id",
                    label="SPOT Feed ID",
                    field_type="text",
                    required=True,
                    placeholder="0abcdef1234567890abcdef123456789",
                    help_text="Your SPOT device feed ID from your SPOT account shared page"
                ),
                PluginConfigField(
                    name="feed_password",
                    label="Feed Password",
                    field_type="password",
                    required=False,
                    sensitive=True,
                    help_text="Password if your SPOT feed is password protected (leave blank if not protected)"
                ),
                PluginConfigField(
                    name="max_results",
                    label="Maximum Results",
                    field_type="number",
                    required=False,
                    default_value=50,
                    min_value=1,
                    max_value=200,
                    help_text="Maximum number of location points to fetch per request"
                )
            ]
        }

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
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
            url = f"https://api.findmespot.com/spot-main-web/consumer/rest-api/2.0/public/feed/{feed_id}/message.json"

            params = {}
            if feed_password:
                params["feedPassword"] = feed_password
            if max_results:
                params["limit"] = max_results

            self.logger.info(f"Fetching SPOT data from feed ID: {feed_id}")

            async with session.get(url, params=params, ssl=ssl_context) as response:
                if response.status == 200:
                    data = await response.json()
                    messages = self._parse_spot_response(data)

                    if not messages:
                        self.logger.info("No messages found from SPOT")
                        return []

                    # Find the newest message by timestamp
                    newest_message = max(messages,
                                         key=lambda msg: datetime.fromisoformat(msg["dateTime"].replace('Z', '+00:00')))

                    # Convert to standardized location format
                    location = {
                        "uid": f"{newest_message.get('messengerName', f'SPOT-{feed_id[:8]}')}-{newest_message['id']}",
                        "name": newest_message.get("messengerName", f"SPOT-{feed_id[:8]}"),
                        "lat": float(newest_message["latitude"]),
                        "lon": float(newest_message["longitude"]),
                        "timestamp": datetime.fromisoformat(newest_message["dateTime"].replace('Z', '+00:00')),
                        "description": self._build_description(newest_message),
                        "additional_data": {
                            "source": "spot",
                            "message_type": newest_message.get("messageType"),
                            "battery_state": newest_message.get("batteryState"),
                            "raw_message": newest_message
                        }
                    }

                    self.logger.info(
                        f"Successfully fetched newest location from SPOT (timestamp: {location['timestamp']})")
                    return [location]

                elif response.status == 401:
                    self.logger.error("Unauthorized access to SPOT feed. Check feed password.")
                    return []
                elif response.status == 404:
                    self.logger.error("SPOT feed not found. Check feed ID.")
                    return []
                else:
                    self.logger.error(f"Error fetching SPOT data: HTTP {response.status}")
                    error_text = await response.text()
                    self.logger.debug(f"Response: {error_text}")
                    return []

        except Exception as e:
            self.logger.error(f"Error fetching SPOT locations: {e}")
            return []

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
                        self.logger.error(f"SPOT API error: {error.get('description', 'Unknown error')}")
                else:
                    self.logger.error(f"SPOT API error: {errors.get('description', 'Unknown error')}")
                return []

            messages_container = feed_response.get("messages", {})
            messages = messages_container.get("message", [])

            # Ensure messages is a list (API returns single dict if only one message)
            if isinstance(messages, dict):
                messages = [messages]

            # Sort by date (newest first)
            messages.sort(key=lambda x: x.get("dateTime", ""), reverse=True)

            self.logger.info(f"Parsed {len(messages)} messages from SPOT response")
            return messages

        except Exception as e:
            self.logger.error(f"Error parsing SPOT response: {e}")
            return []

    def _build_description(self, message: Dict[str, Any]) -> str:
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
            self.logger.warning("SPOT feed ID seems unusually short")

        # Validate max_results if provided
        max_results = self.config.get("max_results")
        if max_results is not None:
            try:
                max_results = int(max_results)
                if max_results < 1 or max_results > 200:
                    self.logger.error("max_results must be between 1 and 200")
                    return False
                # Update config with validated integer value
                self.config["max_results"] = max_results
            except (ValueError, TypeError):
                self.logger.error("max_results must be a valid integer")
                return False

        return True

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to SPOT API with detailed results
        """
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                locations = await self.fetch_locations(session)

                if not locations:
                    return {
                        "success": False,
                        "error": "No location data received from SPOT API",
                        "message": "Connection test failed - no data received"
                    }

                devices = [{"name": loc["name"], "status": "active"} for loc in locations]

                return {
                    "success": True,
                    "message": f"Successfully connected to SPOT feed and found {len(locations)} location points",
                    "device_count": len(set(loc["name"] for loc in locations)),  # Unique devices
                    "devices": devices[:5],  # Limit to first 5 for display
                    "total_points": len(locations)
                }

        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed"
            }