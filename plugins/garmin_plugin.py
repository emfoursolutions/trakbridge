# =============================================================================
# plugins/garmin_plugin.py - Garmin KML Feed Plugin
# =============================================================================

from typing import List, Dict, Any
import aiohttp
import asyncio
import logging
from datetime import datetime
from fastkml import kml
from plugins.base_plugin import BaseGPSPlugin


class GarminPlugin(BaseGPSPlugin):
    """Plugin for fetching location data from Garmin InReach KML feeds"""

    # Class-level plugin name for easier discovery
    PLUGIN_NAME = "garmin"

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        """Class method to get plugin name without instantiation"""
        return cls.PLUGIN_NAME

    @property
    def required_config_fields(self) -> List[str]:
        return ["url", "username", "password"]

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
                    "timestamp": datetime.utcnow(),
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
        delay = self.config.get("retry_delay", 60)

        for attempt in range(retries):
            try:
                async with session.get(url, auth=auth) as response:
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
        if not url.startswith(("http://", "https://")):
            self.logger.error("Garmin URL must be a valid HTTP/HTTPS URL")
            return False

        # Check for optional retry configuration
        retry_delay = self.config.get("retry_delay", 60)
        if not isinstance(retry_delay, (int, float)) or retry_delay < 0:
            self.logger.warning("Invalid retry_delay, using default of 60 seconds")
            self.config["retry_delay"] = 60

        return True

    async def test_connection(self) -> bool:
        """
        Test connection to Garmin KML feed
        """
        try:
            timeout = aiohttp.ClientTimeout(total=30)  # Longer timeout for KML feeds
            async with aiohttp.ClientSession(timeout=timeout) as session:
                kml_data = await self._fetch_kml_feed(
                    session,
                    self.config["url"],
                    self.config["username"],
                    self.config["password"]
                )

                if kml_data is None:
                    return False

                # Try to parse the KML to ensure it's valid
                placemarks = self._parse_kml(kml_data)

                self.logger.info(f"Connection test successful - found {len(placemarks)} devices")
                return True

        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False