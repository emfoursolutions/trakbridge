"""
ABOUTME: Sample external plugin demonstrating custom GPS tracker integration for TrakBridge
ABOUTME: Shows proper plugin structure and security practices for external Docker volume plugins

Sample Custom Tracker Plugin for TrakBridge
This is an example of how to create an external plugin that can be loaded 
from a Docker volume mount without modifying the core application.

To use this plugin:
1. Copy to your external plugins directory
2. Add 'external_plugins.sample_custom_tracker' to allowed_plugin_modules in plugins.yaml
3. Mount the directory as /app/external_plugins in Docker
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from plugins.base_plugin import BaseGPSPlugin, PluginConfigField

logger = logging.getLogger(__name__)


class SampleCustomTrackerPlugin(BaseGPSPlugin):
    """
    Sample custom GPS tracker plugin demonstrating external plugin structure
    """

    PLUGIN_NAME = "sample_custom_tracker"

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for UI generation"""
        return {
            "display_name": "Sample Custom Tracker",
            "description": "Example integration with a custom GPS tracking service",
            "icon": "fas fa-satellite",
            "category": "custom",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "This is a sample plugin for demonstration purposes",
                        "Replace the API calls with your actual tracking service",
                        "Configure your API credentials in the form below",
                        "Test the connection before saving the stream",
                    ],
                },
                {
                    "title": "Configuration Notes",
                    "content": [
                        "API Key should be kept secure and not shared",
                        "Server URL should include protocol (https://)",
                        "Update interval affects API call frequency",
                        "Device filter helps limit data to specific devices",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Your custom tracker service API key",
                ),
                PluginConfigField(
                    name="server_url",
                    label="Server URL",
                    field_type="url",
                    required=True,
                    placeholder="https://api.example-tracker.com",
                    help_text="Base URL for your tracking service API",
                ),
                PluginConfigField(
                    name="device_filter",
                    label="Device Filter",
                    field_type="text",
                    required=False,
                    placeholder="device1,device2",
                    help_text="Comma-separated list of device IDs to include (leave empty for all)",
                ),
                PluginConfigField(
                    name="update_interval",
                    label="Update Interval (seconds)",
                    field_type="number",
                    required=False,
                    default_value=60,
                    min_value=30,
                    max_value=3600,
                    help_text="How often to fetch location updates",
                ),
            ],
        }

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """
        Fetch location data from the custom tracking service

        This is where you would implement the actual API calls to your tracking service.
        The example below shows the expected return format.
        """
        config = self.get_decrypted_config()

        try:
            # Example API call (replace with your actual service)
            headers = {
                "Authorization": f"Bearer {config['api_key']}",
                "Accept": "application/json",
            }

            api_url = f"{config['server_url']}/api/v1/devices/locations"

            async with session.get(api_url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    locations = self._transform_api_data(data, config)
                    logger.info(
                        f"Successfully fetched {len(locations)} locations from custom tracker"
                    )
                    return locations
                elif response.status == 401:
                    logger.error("Authentication failed - check API key")
                    return [{"_error": "401", "_error_message": "Invalid API key"}]
                elif response.status == 404:
                    logger.error("API endpoint not found - check server URL")
                    return [
                        {"_error": "404", "_error_message": "API endpoint not found"}
                    ]
                else:
                    error_text = await response.text(encoding="utf-8")
                    logger.error(f"API returned status {response.status}: {error_text}")
                    return [
                        {
                            "_error": str(response.status),
                            "_error_message": f"API error: {error_text}",
                        }
                    ]

        except aiohttp.ClientTimeout:
            logger.error("API request timed out")
            return [{"_error": "timeout", "_error_message": "API request timed out"}]
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error: {e}")
            return [{"_error": "network", "_error_message": f"Network error: {str(e)}"}]
        except Exception as e:
            logger.error(f"Unexpected error fetching locations: {e}")
            return [
                {"_error": "unknown", "_error_message": f"Unexpected error: {str(e)}"}
            ]

    def _transform_api_data(
        self, api_data: Dict[str, Any], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Transform API response data to TrakBridge location format

        Modify this method to match your API's response format.
        """
        locations = []
        device_filter = config.get("device_filter", "").strip()
        allowed_devices = set(device_filter.split(",")) if device_filter else None

        # Example: assuming API returns data in this format
        # {
        #   "devices": [
        #     {
        #       "device_id": "tracker001",
        #       "name": "Vehicle 1",
        #       "latitude": 40.7128,
        #       "longitude": -74.0060,
        #       "timestamp": "2024-01-15T10:30:00Z",
        #       "status": "moving",
        #       "battery": 85
        #     }
        #   ]
        # }

        for device in api_data.get("devices", []):
            device_id = device.get("device_id", "unknown")

            # Apply device filter if configured
            if allowed_devices and device_id not in allowed_devices:
                continue

            # Parse timestamp
            timestamp_str = device.get("timestamp")
            timestamp = (
                self._parse_timestamp(timestamp_str)
                if timestamp_str
                else datetime.now(timezone.utc)
            )

            # Build description with additional info
            status = device.get("status", "unknown")
            battery = device.get("battery")
            description_parts = [f"Status: {status}"]
            if battery is not None:
                description_parts.append(f"Battery: {battery}%")

            location = {
                "name": device.get("name", f"Device {device_id}"),
                "lat": float(device.get("latitude", 0)),
                "lon": float(device.get("longitude", 0)),
                "timestamp": timestamp,
                "description": " | ".join(description_parts),
                "uid": f"custom-{device_id}",
                "additional_data": {
                    "source": "sample_custom_tracker",
                    "device_id": device_id,
                    "raw_data": device,
                },
            }

            locations.append(location)

        return locations

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """Parse timestamp from API response"""
        try:
            # Handle ISO format with Z suffix
            if timestamp_str.endswith("Z"):
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            else:
                return datetime.fromisoformat(timestamp_str)
        except ValueError:
            logger.warning(f"Could not parse timestamp: {timestamp_str}")
            return None

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to the custom tracking service
        """
        config = self.get_decrypted_config()

        if not config.get("api_key"):
            return {
                "success": False,
                "error": "API key is required",
                "message": "Please configure your API key",
            }

        if not config.get("server_url"):
            return {
                "success": False,
                "error": "Server URL is required",
                "message": "Please configure your server URL",
            }

        try:
            # Test API connectivity with a simple endpoint
            headers = {
                "Authorization": f"Bearer {config['api_key']}",
                "Accept": "application/json",
            }

            # Use a test endpoint or the same endpoint as fetch_locations
            test_url = f"{config['server_url']}/api/v1/status"  # or /devices/locations

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    test_url, headers=headers, timeout=10
                ) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": "Successfully connected to custom tracker API",
                            "details": {
                                "server_url": config["server_url"],
                                "status_code": response.status,
                                "api_accessible": True,
                            },
                        }
                    elif response.status == 401:
                        return {
                            "success": False,
                            "error": "Authentication failed",
                            "message": "Invalid API key or expired credentials",
                        }
                    else:
                        return {
                            "success": False,
                            "error": f"HTTP {response.status}",
                            "message": f"API returned unexpected status: {response.status}",
                        }

        except aiohttp.ClientTimeout:
            return {
                "success": False,
                "error": "Connection timeout",
                "message": "Could not connect to server within 10 seconds",
            }
        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": "Network error",
                "message": f"Network error: {str(e)}",
            }
        except Exception as e:
            return {
                "success": False,
                "error": "Unexpected error",
                "message": f"Unexpected error during connection test: {str(e)}",
            }

    def validate_config(self) -> bool:
        """Validate plugin configuration"""
        if not super().validate_config():
            return False

        # Additional validation for custom tracker
        config = self.get_decrypted_config()

        api_key = config.get("api_key", "").strip()
        if not api_key:
            logger.error("API key is required")
            return False

        server_url = config.get("server_url", "").strip()
        if not server_url:
            logger.error("Server URL is required")
            return False

        if not server_url.startswith(("http://", "https://")):
            logger.error("Server URL must include protocol (http:// or https://)")
            return False

        # Validate update interval
        update_interval = config.get("update_interval", 60)
        try:
            interval = int(update_interval)
            if interval < 30 or interval > 3600:
                logger.error("Update interval must be between 30 and 3600 seconds")
                return False
        except (ValueError, TypeError):
            logger.error("Update interval must be a valid number")
            return False

        return True
