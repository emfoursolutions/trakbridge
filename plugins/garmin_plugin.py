# =============================================================================
# plugins/garmin_plugin.py - Enhanced Garmin KML Feed Plugin with Metadata
# =============================================================================

from typing import List, Dict, Any
import aiohttp
import asyncio
import logging
import ssl
import certifi
from datetime import datetime
from fastkml import kml
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField


class GarminPlugin(BaseGPSPlugin):
    """Enhanced Plugin for fetching location data from Garmin InReach KML feeds"""

    PLUGIN_NAME = "garmin"

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
            "display_name": "Garmin InReach",
            "description": "Connect to Garmin InReach satellite communicators via KML MapShare feeds",
            "icon": "fas fa-satellite-dish",
            "category": "satellite",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Log in to your Garmin account at connect.garmin.com",
                        "Navigate to your InReach device settings",
                        "Go to MapShare settings and enable MapShare",
                        "Create a shareable link and copy the KML feed URL",
                        "Use your Garmin account credentials for authentication"
                    ]
                },
                {
                    "title": "Important Notes",
                    "content": [
                        "Each stream can use different Garmin accounts",
                        "KML feeds update based on your device's tracking settings",
                        "Connection may take 15-30 seconds due to satellite processing",
                        "Feed URLs are device-specific and unique to each InReach"
                    ]
                }
            ],
            "config_fields": [
                PluginConfigField(
                    name="url",
                    label="Garmin InReach KML Feed URL",
                    field_type="url",
                    required=True,
                    placeholder="https://share.garmin.com/Feed/Share/...",
                    help_text="Complete URL to your Garmin InReach KML feed from MapShare"
                ),
                PluginConfigField(
                    name="username",
                    label="Garmin Username",
                    field_type="text",
                    required=True,
                    help_text="Your Garmin Connect account username"
                ),
                PluginConfigField(
                    name="password",
                    label="Garmin Password",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Your Garmin Connect account password"
                ),
                PluginConfigField(
                    name="retry_delay",
                    label="Retry Delay (seconds)",
                    field_type="number",
                    required=False,
                    default_value=60,
                    min_value=30,
                    max_value=300,
                    help_text="Delay between retry attempts on connection failure"
                )
            ]
        }

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch location data from Garmin KML feed

        Returns:
            List of location dictionaries with standardized format
        """
        try:
            kml_data = await self._fetch_kml_feed(
                session,
                self.config["url"],
                self.config["username"],
                self.config["password"]
            )

            if kml_data is None:
                self.logger.warning("No KML data received from Garmin feed")
                return []

            placemarks = self._parse_kml(kml_data)

            # Convert placemarks to standardized location format
            locations = []
            for placemark in placemarks:
                location = {
                    "name": placemark["name"],
                    "lat": float(placemark["lat"]),
                    "lon": float(placemark["lon"]),
                    "timestamp": self._parse_timestamp(placemark) or datetime.utcnow(),
                    "description": placemark.get("description", ""),
                    "additional_data": {
                        "source": "garmin",
                        "raw_placemark": placemark
                    }
                }
                locations.append(location)

            self.logger.info(f"Successfully fetched {len(locations)} locations from Garmin")
            return locations

        except Exception as e:
            self.logger.error(f"Error fetching Garmin locations: {e}")
            return []

    def _parse_timestamp(self, placemark: Dict[str, Any]) -> datetime:
        """
        Try to extract timestamp from placemark description or extended data

        Args:
            placemark: Placemark dictionary

        Returns:
            Parsed datetime or None if not found
        """
        try:
            # Try to parse timestamp from description
            description = placemark.get("description", "")

            # Common Garmin timestamp patterns
            import re

            # Pattern: "Time: 2024-06-06 12:34:56 UTC"
            time_match = re.search(r'Time:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})', description)
            if time_match:
                time_str = time_match.group(1)
                return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")

            # Pattern: ISO format in description
            iso_match = re.search(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})', description)
            if iso_match:
                time_str = iso_match.group(1)
                return datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%S")

        except Exception as e:
            self.logger.debug(f"Could not parse timestamp from placemark: {e}")

        return None

    async def _fetch_kml_feed(self, session: aiohttp.ClientSession, url: str,
                              username: str, password: str, retries: int = 3) -> str:
        """
        Fetch Garmin KML feed with retry mechanism

        Args:
            session: aiohttp session
            url: Garmin KML feed URL
            username: Garmin username
            password: Garmin password
            retries: Number of retry attempts

        Returns:
            KML content as string or None if failed
        """
        auth = aiohttp.BasicAuth(username, password)

        # Ensure retry_delay is an integer
        delay = int(self.config.get("retry_delay", 60))

        # Create SSL context for certificate verification
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        for attempt in range(retries):
            try:
                # Use SSL context or disable SSL verification if needed
                async with session.get(url, auth=auth, ssl=ssl_context) as response:
                    if response.status == 200:
                        content = await response.text()

                        # Validate content
                        if not content or content.isspace():
                            self.logger.error("Received empty KML feed")
                            return None

                        if "<kml" not in content:
                            self.logger.error("Received non-KML content")
                            return None

                        self.logger.info("KML Feed Successfully Fetched")
                        return content

                    elif response.status == 401:
                        self.logger.error("Unauthorized access (401). Check Garmin credentials.")
                        return None

                    else:
                        self.logger.error(f"Error fetching KML feed: HTTP {response.status}")

            except ssl.SSLError as ssl_err:
                self.logger.warning(f"SSL Error on attempt {attempt + 1}: {ssl_err}")
                # Fallback to no SSL verification on SSL errors
                try:
                    async with session.get(url, auth=auth, ssl=False) as response:
                        if response.status == 200:
                            content = await response.text()
                            if content and "<kml" in content:
                                self.logger.warning("Using insecure SSL connection due to certificate issues")
                                return content
                except Exception as fallback_err:
                    self.logger.error(f"Fallback attempt failed: {fallback_err}")

            except Exception as e:
                self.logger.warning(f"Attempt {attempt + 1} failed: {e}")

            if attempt < retries - 1:
                self.logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)

        self.logger.error("Failed to fetch KML feed after multiple attempts")
        return None

    def _parse_kml(self, kml_data: str) -> List[Dict[str, Any]]:
        """
        Parse KML data and extract placemarks

        Args:
            kml_data: Raw KML content

        Returns:
            List of placemark dictionaries
        """
        try:
            k = kml.KML()
            k.from_string(kml_data.encode())

            placemarks = []

            # Parse through the KML to find placemarks
            for document in k.features():
                for folder in document.features():
                    for placemark in folder.features():
                        if isinstance(placemark, kml.Placemark):
                            try:
                                coords = placemark.geometry.coords[0]
                                name = placemark.name or "Unknown Device"

                                placemark_data = {
                                    "name": name,
                                    "lat": coords[1],
                                    "lon": coords[0],
                                    "description": (
                                        placemark.description
                                        if placemark.description
                                        else "No description"
                                    ),
                                }
                                placemarks.append(placemark_data)

                            except (IndexError, AttributeError) as e:
                                self.logger.warning(f"Error parsing placemark {placemark.name}: {e}")
                                continue

            self.logger.info(f"Parsed {len(placemarks)} placemarks from KML")
            return placemarks

        except Exception as e:
            self.logger.error(f"Error parsing KML data: {e}")
            return []

    def validate_config(self) -> bool:
        """
        Enhanced validation for Garmin-specific configuration
        """
        if not super().validate_config():
            return False

        # Additional Garmin-specific validation
        url = self.config.get("url", "")
        if "garmin.com" not in url.lower():
            self.logger.warning("URL does not appear to be a Garmin feed URL")

        # Ensure retry_delay is properly typed
        retry_delay = self.config.get("retry_delay", 60)
        if isinstance(retry_delay, str):
            try:
                self.config["retry_delay"] = int(retry_delay)
            except ValueError:
                self.logger.error("retry_delay must be a valid integer")
                return False

        return True