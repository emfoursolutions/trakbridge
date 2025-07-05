"""
File: plugins/garmin_plugin.py

Description:
    Garmin InReach KML plugin for GPS tracking. This plugin connects to Garmin MapShare
    feeds using authenticated requests, fetches and parses KML data, and extracts
    standardized location information for use with TAK servers. It supports retries,
    SSL verification, extended metadata extraction, device filtering (e.g., hiding
    inactive devices), and integration with the plugin framework for metadata-driven
    configuration and UI generation.

Key features:
    - Fetches the latest location updates from Garmin MapShare API
    - Parses and normalizes raw SPOT message data into a Cursor on Target format
    - Provides user-friendly setup and help instructions as metadata
    - Validates Garmin configuration parameters
    - Supports async connection testing with error handling and feedback

Author: {{AUTHOR}}
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import asyncio
import ssl
from datetime import datetime, timezone

# Third-party imports
import aiohttp
import certifi
from fastkml import kml

# Local application imports
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
                    name="hide_inactive_devices",
                    label="Hide Inactive Devices",
                    field_type="checkbox",
                    required=False,
                    default_value=True,
                    help_text="When checked, hides devices that have tracking turned off. When unchecked, shows all devices including those with tracking disabled."
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
        # Get decrypted configuration using the base class method
        decrypted_config = self.get_decrypted_config()

        try:
            kml_data = await self._fetch_kml_feed(
                session,
                decrypted_config["url"],
                decrypted_config["username"],
                decrypted_config["password"]
            )

            if kml_data is None:
                self.logger.warning("No KML data received from Garmin feed")
                return []

            placemarks = self._parse_kml(kml_data)

            # Convert placemarks to standardized location format
            locations = []

            def _to_bool(val, default=False):
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    return val.lower() in ("true", "1", "on", "yes")
                if isinstance(val, int):
                    return val != 0
                return default

            hide_inactive = _to_bool(self.config.get("hide_inactive_devices", True), default=True)
            for placemark in placemarks:
                # Check if device is inactive and should be hidden
                if hide_inactive and self._is_device_inactive(placemark):
                    self.logger.debug(f"Skipping inactive device: {placemark.get('name', 'Unknown')}")
                    continue

                # Get the actual reporting time from ExtendedData/description
                actual_reporting_time = self._parse_timestamp(placemark.get("description"))

                # Always use current time for CoT timestamp, add actual time to remarks
                cot_timestamp = datetime.now(timezone.utc)
                if actual_reporting_time:
                    remarks_addition = f"Last Reported: {actual_reporting_time.strftime('%m/%d/%Y %H:%M:%S UTC')}"
                else:
                    remarks_addition = "Reporting time unavailable"

                # Build description/remarks - handle None values properly
                base_description = placemark.get("description") or ""
                if base_description is None:
                    base_description = ""

                final_description = f"{base_description}{remarks_addition}".strip()

                location = {
                    "name": placemark["name"],
                    "lat": float(placemark["lat"]),
                    "lon": float(placemark["lon"]),
                    "timestamp": cot_timestamp,
                    "description": final_description,
                    "uid": placemark.get("uid"),
                    "additional_data": {
                        "source": "garmin",
                        "actual_reporting_time": actual_reporting_time,
                        "hide_inactive_setting": hide_inactive,
                        "raw_placemark": placemark
                    }
                }
                locations.append(location)

            self.logger.info(
                f"Successfully fetched {len(locations)} locations from Garmin")
            return locations

        except Exception as e:
            self.logger.error(f"Error fetching Garmin locations: {e}")
            return []

    def _is_device_inactive(self, placemark: Dict[str, Any]) -> bool:
        """
        Check if a device is inactive based on the Event field in ExtendedData

        Args:
            placemark: Placemark dictionary

        Returns:
            True if device is inactive (tracking turned off), False otherwise
        """
        try:
            extended_data = placemark.get("extended_data", {})
            if extended_data:
                event_value = extended_data.get("Event", "")
                if event_value and "tracking turned off" in event_value.lower():
                    self.logger.debug(f"Device inactive - Event: {event_value}")
                    return True
            return False
        except Exception as e:
            self.logger.debug(f"Error checking device activity status: {e}")
            return False

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """
        Parse timestamp from Garmin KML or other sources
        Args:
            timestamp_str: Timestamp string
        Returns:
            datetime object (UTC)
        """
        from datetime import datetime, timezone
        if not timestamp_str:
            return datetime.now(timezone.utc)
        try:
            if timestamp_str.endswith('Z'):
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).replace(tzinfo=None)
            else:
                return datetime.fromisoformat(timestamp_str)
        except Exception:
            return datetime.now(timezone.utc)

    def _parse_time_string(self, time_str: str) -> datetime:
        """
        Parse a time string to a datetime object. Return current UTC time if parsing fails.
        """
        from datetime import datetime, timezone
        if not time_str:
            return datetime.now(timezone.utc)
        try:
            if time_str.endswith('Z'):
                return datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)
            else:
                return datetime.fromisoformat(time_str)
        except Exception:
            return datetime.now(timezone.utc)

    def _parse_time_from_description(self, description: str) -> datetime:
        """
        Parse a datetime from a description string. Return current UTC time if not found.
        """
        from datetime import datetime, timezone
        # Implement your parsing logic here, or just return now for safety
        return datetime.now(timezone.utc)

    def _build_description(self, placemark: dict) -> str:
        """
        Build description string from placemark data
        Args:
            placemark: dict
        Returns:
            str
        """
        desc = placemark.get('description')
        if desc is None:
            desc = ''
        return str(desc)

    def _get_some_string_field(self, data: dict) -> str:
        value = data.get('some_field')
        if value is None:
            return ''
        return str(value)

    def _another_string_method(self, value) -> str:
        if value is None:
            return ''
        return str(value)

    def _safe_strip(self, value) -> str:
        if value is None:
            return ''
        return str(value).strip()

    def _string_method_1(self, value) -> str:
        if value is None:
            return ''
        return str(value)

    def _string_method_2(self, value) -> str:
        if value is None:
            return ''
        return str(value)

    def _string_method_3(self, value) -> str:
        if value is None:
            return ''
        return str(value)

    def _string_method_4(self, value) -> str:
        if value is None:
            return ''
        return str(value)

    def _safe_strip_usage(self, value) -> str:
        if value is None:
            return ''
        return str(value).strip()

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

    def _parse_kml(self, kml_data):
        """
        Parse KML data and extract placemarks (Points only, excluding LineStrings)

        Args:
            kml_data: Raw KML content as string

        Returns:
            List of placemark dictionaries
        """
        try:
            k = kml.KML()
            k.from_string(kml_data.encode())
            self.logger.debug(f"KML object created: {k}")

            # Debug the KML structure
            self.logger.debug(f"KML features: {k.features}")
            self.logger.debug(f"KML features length: {len(k.features) if k.features else 'None'}")

            placemarks = []

            def extract_placemarks(feature):
                """Recursively extract Point placemarks from any KML feature"""
                self.logger.debug(f"Feature type: {type(feature)}, has features: {hasattr(feature, 'features')}")

                if hasattr(feature, 'features') and feature.features:
                    # If it has sub-features, recurse into them
                    self.logger.debug(f"Feature has {len(feature.features)} sub-features")
                    for sub_feature in feature.features:
                        extract_placemarks(sub_feature)
                elif hasattr(feature, 'geometry') and feature.geometry:
                    # This is a placemark with geometry
                    geometry_type = type(feature.geometry).__name__
                    self.logger.debug(f"Found placemark with geometry: {geometry_type}")

                    # Only process Point geometries, skip LineString and other geometry types
                    if 'Point' not in geometry_type:
                        self.logger.debug(f"Skipping non-Point geometry: {geometry_type}")
                        return

                    try:
                        # Get coordinates
                        coords = None
                        if hasattr(feature.geometry, 'coords'):
                            coords = feature.geometry.coords
                            self.logger.debug(f"Coords from .coords: {coords}")
                        elif hasattr(feature.geometry, 'coordinates'):
                            coords = feature.geometry.coordinates
                            self.logger.debug(f"Coords from .coordinates: {coords}")

                        if coords:
                            # Handle different coordinate formats
                            if isinstance(coords, list) and len(coords) > 0:
                                if isinstance(coords[0], (list, tuple)):
                                    # Nested list/tuple format
                                    lon, lat = coords[0][0], coords[0][1]
                                else:
                                    # Direct list format
                                    lon, lat = coords[0], coords[1]
                            else:
                                self.logger.warning(f"Unexpected coordinate format: {coords}")
                                return

                            # Extract timestamp from ExtendedData if available
                            timestamp = self._extract_timestamp_from_extended_data(feature)

                            # Extract extended data and get ID
                            extended_data = self._extract_extended_data(feature)
                            placemark_id = extended_data.get('IMEI', 'Unknown')

                            # Clean name and ID by removing spaces
                            clean_name = str(getattr(feature, 'name', 'Unknown')).replace(' ', '')
                            clean_id = str(placemark_id).replace(' ', '')

                            placemark_data = {
                                "uid": f"{clean_name}-{clean_id}",
                                "name": getattr(feature, 'name', 'Unknown'),
                                "lat": lat,
                                "lon": lon,
                                "description": getattr(feature, 'description', 'No description') or 'No description',
                                "timestamp": timestamp,
                                "extended_data": extended_data
                            }
                            placemarks.append(placemark_data)
                            self.logger.debug(f"Added Point placemark: {placemark_data}")

                    except (IndexError, AttributeError, TypeError) as e:
                        self.logger.warning(f"Error parsing placemark {getattr(feature, 'name', 'Unknown')}: {e}")
                else:
                    self.logger.debug(f"Feature has no geometry or sub-features: {getattr(feature, 'name', 'Unknown')}")

            # Start extraction from root features
            self.logger.debug(f"KML features type: {type(k.features)}")
            if k.features:
                # self.logger.debug(f"Number of root features: {len(k.features)}")
                for feature in k.features:
                    self.logger.debug(
                        f"Processing feature type: {type(feature)}, name: {getattr(feature, 'name', 'Unknown')}")
                    extract_placemarks(feature)
            else:
                # self.logger.warning("No features found in KML")

                # Try alternative parsing - direct XML approach (Points only)
                try:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(kml_data)

                    # Look for Placemark elements with Point geometry
                    namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
                    placemarks_xml = root.findall('.//kml:Placemark', namespaces)

                    self.logger.debug(f"Found {len(placemarks_xml)} Placemark elements via XML")

                    for placemark_xml in placemarks_xml:
                        try:
                            # Check if this placemark has a Point (not LineString)
                            point_elem = placemark_xml.find('.//kml:Point', namespaces)
                            if point_elem is None:
                                self.logger.debug("Skipping non-Point placemark")
                                continue

                            # Get name
                            name_elem = placemark_xml.find('kml:name', namespaces)
                            name = name_elem.text if name_elem is not None else 'Unknown'

                            # Get coordinates from Point
                            coords_elem = point_elem.find('kml:coordinates', namespaces)
                            if coords_elem is not None:
                                coords_text = coords_elem.text.strip()
                                # KML coordinates are "lon,lat,elevation"
                                coord_parts = coords_text.split(',')
                                if len(coord_parts) >= 2:
                                    lon = float(coord_parts[0])
                                    lat = float(coord_parts[1])

                                    # Get description
                                    desc_elem = placemark_xml.find('kml:description', namespaces)
                                    description = desc_elem.text if desc_elem is not None else 'No description'

                                    # Extract timestamp from TimeStamp or ExtendedData
                                    timestamp = self._extract_timestamp_from_xml(placemark_xml, namespaces)

                                    # Extract extended data and get ID
                                    extended_data = self._extract_extended_data_from_xml(placemark_xml, namespaces)
                                    placemark_id = extended_data.get('IMEI', 'Unknown')

                                    # Clean name and ID by removing spaces
                                    clean_name = str(name).replace(' ', '')
                                    clean_id = str(placemark_id).replace(' ', '')

                                    placemark_data = {
                                        "uid": f"{clean_name}-{clean_id}",
                                        "name": name,
                                        "lat": lat,
                                        "lon": lon,
                                        "description": description,
                                        "timestamp": timestamp,
                                        "extended_data": extended_data
                                    }
                                    placemarks.append(placemark_data)
                                    self.logger.debug(f"Added Point placemark via XML: {placemark_data}")

                        except (ValueError, IndexError) as e:
                            self.logger.warning(f"Error parsing XML placemark: {e}")

                except Exception as xml_e:
                    self.logger.error(f"Alternative XML parsing failed: {xml_e}")

            self.logger.debug(f"Parsed {len(placemarks)} Point placemarks from KML")
            return placemarks

        except Exception as e:
            self.logger.error(f"Error parsing KML data: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def _extract_timestamp_from_extended_data(self, feature):
        """Extract timestamp from ExtendedData or TimeStamp element"""
        try:
            # Check for TimeStamp element first
            if hasattr(feature, 'timestamp') and feature.timestamp:
                return datetime.fromisoformat(feature.timestamp.replace('Z', '+00:00'))

            # Check ExtendedData
            if hasattr(feature, 'extended_data') and feature.extended_data:
                for data in feature.extended_data:
                    if hasattr(data, 'name') and data.name in ['Time UTC', 'Time']:
                        try:
                            time_str = data.value
                            # Parse different time formats
                            for fmt in ['%m/%d/%Y %I:%M:%S %p', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%SZ']:
                                try:
                                    return datetime.strptime(time_str, fmt)
                                except ValueError:
                                    continue
                        except Exception:
                            continue

            return None
        except Exception as e:
            self.logger.debug(f"Error extracting timestamp from extended data: {e}")
            return None

    def _extract_timestamp_from_xml(self, placemark_xml, namespaces):
        """Extract timestamp from XML TimeStamp or ExtendedData"""
        try:
            # Check for TimeStamp element
            timestamp_elem = placemark_xml.find('.//kml:TimeStamp/kml:when', namespaces)
            if timestamp_elem is not None:
                time_str = timestamp_elem.text
                # Parse ISO format: 2024-09-17T09:47:00Z
                return datetime.fromisoformat(time_str.replace('Z', '+00:00')).replace(tzinfo=None)

            # Check ExtendedData
            extended_data = placemark_xml.find('kml:ExtendedData', namespaces)
            if extended_data is not None:
                for data_elem in extended_data.findall('kml:Data', namespaces):
                    name_attr = data_elem.get('name')
                    if name_attr in ['Time UTC', 'Time']:
                        value_elem = data_elem.find('kml:value', namespaces)
                        if value_elem is not None:
                            time_str = value_elem.text
                            # Parse format: 9/17/2024 9:47:00 AM
                            try:
                                return datetime.strptime(time_str, '%m/%d/%Y %I:%M:%S %p')
                            except ValueError:
                                try:
                                    return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                                except ValueError:
                                    continue

            return None
        except Exception as e:
            self.logger.debug(f"Error extracting timestamp from XML: {e}")
            return None

    def _extract_extended_data(self, feature):
        """Extract extended data from feature"""
        extended_data = {}
        try:
            if hasattr(feature, 'extended_data') and feature.extended_data:
                for data in feature.extended_data:
                    if hasattr(data, 'name') and hasattr(data, 'value'):
                        extended_data[data.name] = data.value
        except Exception as e:
            self.logger.debug(f"Error extracting extended data: {e}")
        return extended_data

    def _extract_extended_data_from_xml(self, placemark_xml, namespaces):
        """Extract extended data from XML"""
        extended_data = {}
        try:
            extended_data_elem = placemark_xml.find('kml:ExtendedData', namespaces)
            if extended_data_elem is not None:
                for data_elem in extended_data_elem.findall('kml:Data', namespaces):
                    name_attr = data_elem.get('name')
                    value_elem = data_elem.find('kml:value', namespaces)
                    if name_attr and value_elem is not None:
                        extended_data[name_attr] = value_elem.text
        except Exception as e:
            self.logger.debug(f"Error extracting extended data from XML: {e}")
        return extended_data

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