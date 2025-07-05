"""
File: plugins/traccar_plugin.py

Description:
    Plugin implementation for fetching and processing location data from the Traccar GPS tracking platform.
    Connects to a Traccar server REST API using basic authentication, supports secure HTTPS connections,
    device filtering, and configurable request timeouts. Implements asynchronous fetching of device and position data,
    normalizes and enriches GPS positions with detailed metadata including speed, altitude, battery, and ignition status.
    Provides detailed metadata for UI integration, validates configuration parameters specific to Traccar,
    and supports enhanced async connection testing with comprehensive results and logging.
    Designed to integrate with the BaseGPSPlugin framework, supporting secure config handling and robust error handling.

Key features:
    - Fetches current GPS positions and device information from Traccar REST API
    - Normalizes raw position data into a standardized location format with detailed attributes
    - Supports device name filtering and configurable API timeouts
    - Validates Traccar-specific configuration including server URL and credentials
    - Handles SSL context and connection optimizations to prevent timeouts
    - Provides async connection testing with detailed success/error feedback and device counts

Author: {{AUTHOR}}
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import asyncio
import json
import ssl
from datetime import datetime, timezone

# Third-party imports
import aiohttp
import certifi

# Local application imports
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField
from typing import List, Dict, Any


class TraccarPlugin(BaseGPSPlugin):
    """Plugin for fetching location data from Traccar GPS tracking platform"""

    PLUGIN_NAME = "traccar"

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
            "display_name": "Traccar GPS Platform",
            "description": "Connect to Traccar GPS tracking platform via REST API",
            "icon": "fas fa-map-marked-alt",
            "category": "platform",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Install and configure Traccar server on your infrastructure",
                        "Create a user account in Traccar with appropriate permissions",
                        "Note your Traccar server URL (e.g., http://localhost:8082)",
                        "Ensure your user has read access to device positions",
                        "API endpoint used: /api/positions"
                    ]
                },
                {
                    "title": "API Information",
                    "content": [
                        "Uses Traccar's REST API to fetch current positions",
                        "Requires basic authentication with username/password",
                        "Returns latest position for each device",
                        "Position data includes coordinates, timestamp, and device info",
                        "Supports both HTTP and HTTPS connections"
                    ]
                },
                {
                    "title": "Security Notes",
                    "content": [
                        "Use HTTPS for production deployments",
                        "Create dedicated API user with minimal required permissions",
                        "Regularly rotate API credentials",
                        "Monitor API access logs for suspicious activity"
                    ]
                }
            ],
            "config_fields": [
                PluginConfigField(
                    name="server_url",
                    label="Traccar Server URL",
                    field_type="url",
                    required=True,
                    placeholder="http://localhost:8082",
                    help_text="Complete URL to your Traccar server (including port if needed)"
                ),
                PluginConfigField(
                    name="username",
                    label="Username",
                    field_type="text",
                    required=True,
                    help_text="Traccar username with device access permissions"
                ),
                PluginConfigField(
                    name="password",
                    label="Password",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Traccar user password"
                ),
                PluginConfigField(
                    name="timeout",
                    label="Request Timeout (seconds)",
                    field_type="number",
                    required=False,
                    default_value=30,
                    min_value=5,
                    max_value=120,
                    help_text="HTTP request timeout in seconds"
                ),
                PluginConfigField(
                    name="device_filter",
                    label="Device Name Filter",
                    field_type="text",
                    required=False,
                    placeholder="vehicle,tracker",
                    help_text="Comma-separated list of device names to include (leave empty for all devices)"
                ),

            ]
        }

    def _create_ssl_context(self) -> ssl.SSLContext:
        """
        Create SSL context with proper configuration to avoid timeout issues

        Returns:
            Configured SSL context
        """
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        # Configure SSL context to handle timeout issues
        ssl_context.options |= ssl.OP_NO_SSLv2
        ssl_context.options |= ssl.OP_NO_SSLv3
        ssl_context.options |= ssl.OP_SINGLE_DH_USE
        ssl_context.options |= ssl.OP_SINGLE_ECDH_USE

        return ssl_context

    def _create_connector(self) -> aiohttp.TCPConnector:
        """
        Create aiohttp connector with SSL timeout fixes

        Returns:
            Configured TCP connector
        """
        ssl_context = self._create_ssl_context()

        return aiohttp.TCPConnector(
            ssl=ssl_context,
            limit=10,  # Limit concurrent connections
            limit_per_host=5,  # Limit per host
            ttl_dns_cache=300,  # DNS cache TTL
            use_dns_cache=True,
            keepalive_timeout=10,  # Reduced keepalive timeout
            enable_cleanup_closed=True,  # Enable cleanup of closed connections
            force_close=False,  # Allow connection reuse but don't force close
            ssl_shutdown_timeout=5,  # Set SSL shutdown timeout to prevent hanging
        )

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch location data from Traccar API

        Returns:
            List of location dictionaries with standardized format
        """
        connector = None
        try:
            # Get decrypted configuration
            config = self.get_decrypted_config()

            # Create a new session with proper SSL configuration if needed
            if not hasattr(session, '_connector') or session._connector is None:
                connector = self._create_connector()
                timeout = aiohttp.ClientTimeout(total=int(config.get("timeout", 30)))

                async with aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout
                ) as custom_session:
                    return await self._fetch_locations_with_session(custom_session, config)
            else:
                return await self._fetch_locations_with_session(session, config)

        except Exception as e:
            self.logger.error(f"Error fetching Traccar positions: {e}")
            return []
        finally:
            # Clean up connector if we created one
            if connector and not connector.closed:
                try:
                    await connector.close()
                except Exception as close_error:
                    self.logger.debug(f"Error closing connector (non-critical): {close_error}")

    async def _fetch_locations_with_session(self, session: aiohttp.ClientSession,
                                            config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Internal method to fetch locations with a given session
        """
        positions = await self._fetch_positions_from_api(session, config)

        if not positions:
            self.logger.warning("No position data received from Traccar API")
            return []

        # Get device information to enrich position data
        devices = await self._fetch_devices_from_api(session, config)
        device_map = {device['id']: device for device in devices} if devices else {}

        # Convert positions to standardized location format
        locations = []
        device_filter = self._parse_device_filter(config.get("device_filter", ""))

        for position in positions:
            device_info = device_map.get(position.get('deviceId'), {})
            device_name = device_info.get('name', f"Device {position.get('deviceId', 'Unknown')}")

            # Apply device filter if specified
            if device_filter and not self._device_matches_filter(device_name, device_filter):
                continue

            location = {
                "name": device_name,
                "lat": float(position.get('latitude', 0)),
                "lon": float(position.get('longitude', 0)),
                "timestamp": self._parse_timestamp(position.get('deviceTime') or position.get('fixTime')),
                "description": self._build_description(position, device_info),
                "uid": f"traccar-{position.get('deviceId', 'unknown')}",
                "additional_data": {
                    "source": "traccar",
                    "device_id": position.get('deviceId'),
                    "position_id": position.get('id'),
                    "speed": position.get('speed'),
                    "course": position.get('course'),
                    "altitude": position.get('altitude'),
                    "accuracy": position.get('accuracy'),
                    "attributes": position.get('attributes', {}),
                    "device_info": device_info
                }
            }
            locations.append(location)

        self.logger.info(f"Successfully fetched {len(locations)} positions from Traccar")
        return locations

    async def _fetch_positions_from_api(self, session: aiohttp.ClientSession,
                                        config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Fetch positions from Traccar API

        Args:
            session: aiohttp session
            config: Decrypted configuration

        Returns:
            List of position dictionaries
        """
        server_url = config["server_url"].rstrip('/')
        url = f"{server_url}/api/positions"

        auth = aiohttp.BasicAuth(config["username"], config["password"])
        timeout = aiohttp.ClientTimeout(total=int(config.get("timeout", 30)))

        # Create SSL context for certificate verification
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        try:
            async with session.get(url, auth=auth, timeout=timeout, ssl=ssl_context) as response:
                if response.status == 200:
                    data = await response.json()
                    self.logger.info(f"Successfully fetched {len(data)} positions from Traccar API")
                    return data
                elif response.status == 401:
                    self.logger.error("Unauthorized access (401). Check Traccar credentials.")
                    return []
                elif response.status == 403:
                    self.logger.error("Forbidden access (403). Check user permissions.")
                    return []
                else:
                    error_text = await response.text()
                    self.logger.error(f"API request failed with status {response.status}: {error_text}")
                    return []

        except asyncio.TimeoutError:
            self.logger.error("Request timed out while fetching positions")
            return []
        except aiohttp.ClientError as e:
            self.logger.error(f"HTTP client error: {e}")
            return []
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON response: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching positions: {e}")
            return []

    async def _fetch_devices_from_api(self, session: aiohttp.ClientSession,
                                      config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Fetch device information from Traccar API

        Args:
            session: aiohttp session
            config: Decrypted configuration

        Returns:
            List of device dictionaries
        """
        server_url = config["server_url"].rstrip('/')
        url = f"{server_url}/api/devices"

        auth = aiohttp.BasicAuth(config["username"], config["password"])
        timeout = aiohttp.ClientTimeout(total=int(config.get("timeout", 30)))

        # Create SSL context for certificate verification
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        try:
            async with session.get(url, auth=auth, timeout=timeout, ssl=ssl_context) as response:
                if response.status == 200:
                    data = await response.json()
                    self.logger.debug(f"Successfully fetched {len(data)} devices from Traccar API")
                    return data
                else:
                    self.logger.warning(f"Could not fetch devices: HTTP {response.status}")
                    return []

        except Exception as e:
            self.logger.warning(f"Error fetching devices (non-critical): {e}")
            return []

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """
        Parse timestamp from Traccar API response

        Args:
            timestamp_str: Timestamp string from API

        Returns:
            Parsed datetime object
        """
        if not timestamp_str:
            return datetime.now(timezone.utc)

        try:
            # Traccar typically returns ISO 8601 format
            # Handle both with and without timezone info
            if timestamp_str.endswith('Z'):
                # UTC timezone
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).replace(tzinfo=None)
            elif '+' in timestamp_str[-6:] or timestamp_str.endswith(('00', '30', '45')):
                # Has timezone offset
                dt = datetime.fromisoformat(timestamp_str)
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                # Assume UTC if no timezone info
                return datetime.fromisoformat(timestamp_str)

        except Exception as e:
            self.logger.debug(f"Could not parse timestamp '{timestamp_str}': {e}")
            return datetime.now(timezone.utc)

    def _build_description(self, position: Dict[str, Any], device_info: Dict[str, Any]) -> str:
        """
        Build description string from position and device data

        Args:
            position: Position data from API
            device_info: Device information from API

        Returns:
            Formatted description string
        """
        parts = []

        # Add device model/type if available
        if device_info.get('model'):
            parts.append(f"Model: {device_info['model']}")

        # Add speed if available
        speed = position.get('speed')
        if speed is not None:
            # Convert from knots to km/h (Traccar default is knots)
            speed_kmh = speed * 1.852
            parts.append(f"Speed: {speed_kmh:.1f} km/h")

        # Add course/heading if available
        course = position.get('course')
        if course is not None:
            parts.append(f"Heading: {course:.0f}°")

        # Add altitude if available
        altitude = position.get('altitude')
        if altitude is not None:
            parts.append(f"Altitude: {altitude:.0f}m")

        # Add accuracy if available
        accuracy = position.get('accuracy')
        if accuracy is not None:
            parts.append(f"Accuracy: {accuracy:.0f}m")

        # Add timestamp
        timestamp = self._parse_timestamp(position.get('deviceTime') or position.get('fixTime'))
        parts.append(f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # Add any notable attributes
        attributes = position.get('attributes', {})
        if attributes.get('battery'):
            parts.append(f"Battery: {attributes['battery']}%")
        if attributes.get('ignition') is not None:
            parts.append(f"Ignition: {'On' if attributes['ignition'] else 'Off'}")

        return " | ".join(parts) if parts else "No additional information"

    def _parse_device_filter(self, filter_str: str) -> List[str]:
        """
        Parse device filter string into list of device names

        Args:
            filter_str: Comma-separated list of device names

        Returns:
            List of device names (lowercase for comparison)
        """
        if not filter_str or not filter_str.strip():
            return []

        return [name.strip().lower() for name in filter_str.split(',') if name.strip()]

    def _device_matches_filter(self, device_name: str, device_filter: List[str]) -> bool:
        """
        Check if device name matches any filter criteria

        Args:
            device_name: Device name to check
            device_filter: List of filter criteria

        Returns:
            True if device matches filter
        """
        if not device_filter:
            return True

        device_name_lower = device_name.lower()
        return any(filter_name in device_name_lower for filter_name in device_filter)

    def validate_config(self) -> bool:
        """
        Enhanced validation for Traccar-specific configuration
        """
        if not super().validate_config():
            return False

        # Additional Traccar-specific validation
        config = self.get_decrypted_config()

        server_url = config.get("server_url", "")
        if not server_url:
            self.logger.error("Server URL is required")
            return False

        # Ensure timeout is properly typed
        timeout = config.get("timeout", 30)
        if isinstance(timeout, str):
            try:
                self.config["timeout"] = int(timeout)
            except ValueError:
                self.logger.error("Timeout must be a valid integer")
                return False

        # Validate verify_ssl setting
        verify_ssl = config.get("verify_ssl", True)
        if not isinstance(verify_ssl, bool):
            self.logger.error("verify_ssl must be a boolean value")
            return False

        # Basic URL validation
        if not server_url.startswith(("http://", "https://")):
            self.logger.error("Server URL must start with http:// or https://")
            return False

        return True

    async def test_connection(self) -> Dict[str, Any]:
        """
        Enhanced connection test that returns detailed results

        Returns:
            Dictionary with connection test results
        """
        connector = None
        try:
            config = self.get_decrypted_config()
            timeout = aiohttp.ClientTimeout(total=int(config.get("timeout", 30)))

            # Create connector with SSL timeout fixes
            connector = self._create_connector()

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                # Test API connectivity by fetching devices first
                devices = await self._fetch_devices_from_api(session, config)

                if devices is None:
                    return {
                        "success": False,
                        "error": "Failed to connect to Traccar API",
                        "message": "Could not fetch device list"
                    }

                # Test positions endpoint
                positions = await self._fetch_positions_from_api(session, config)

                if positions is None:
                    return {
                        "success": False,
                        "error": "Failed to fetch positions from Traccar API",
                        "message": "API connection successful but no position data available"
                    }

                # Apply device filter for count
                device_filter = self._parse_device_filter(config.get("device_filter", ""))
                if device_filter:
                    device_map = {device['id']: device for device in devices}
                    filtered_positions = [
                        pos for pos in positions
                        if self._device_matches_filter(
                            device_map.get(pos.get('deviceId'), {}).get('name', ''),
                            device_filter
                        )
                    ]
                    position_count = len(filtered_positions)
                    filter_info = f" (filtered from {len(positions)} total)"
                else:
                    position_count = len(positions)
                    filter_info = ""

                device_names = [device.get('name', f"Device {device.get('id')}") for device in devices]

                return {
                    "success": True,
                    "message": f"Successfully connected to Traccar. Found {len(devices)} device(s) with {position_count} position(s){filter_info}",
                    "device_count": len(devices),
                    "position_count": position_count,
                    "devices": device_names[:10],  # Limit to first 10 devices
                    "server_url": config["server_url"]
                }

        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed"
            }
        finally:
            # Properly close the connector to prevent SSL shutdown timeouts
            if connector and not connector.closed:
                try:
                    await connector.close()
                except Exception as close_error:
                    self.logger.debug(f"Error closing connector (non-critical): {close_error}")

            # Small delay to allow cleanup
            await asyncio.sleep(0.1)