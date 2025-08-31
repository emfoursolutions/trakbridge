"""
File: plugins/garmin_plugin.py

Description:
    Refactored Garmin InReach KML plugin for GPS tracking. Streamlined for better
    maintainability, reduced code duplication, and improved structure.

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: 2025-07-21
Version: 2.0.0
"""

import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
import certifi
import defusedxml.ElementTree as ET
from fastkml import kml

from plugins.base_plugin import (
    BaseGPSPlugin,
    PluginConfigField,
    CallsignMappable,
    FieldMetadata,
)

logger = logging.getLogger(__name__)


class GarminPlugin(BaseGPSPlugin, CallsignMappable):
    """Enhanced Plugin for fetching location data from Garmin InReach KML feeds"""

    PLUGIN_NAME = "garmin"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kml_extractor = KMLDataExtractor()

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for UI generation"""
        return {
            "display_name": "Garmin InReach",
            "description": "Connect to Garmin InReach satellite communicators via KML MapShare feeds",
            "icon": "fas fa-satellite-dish",
            "category": "tracker",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Log in to your Garmin account at connect.garmin.com",
                        "Navigate to your InReach device settings",
                        "Go to MapShare settings and enable MapShare",
                        "Create a shareable link and copy the KML feed URL",
                        "Use your Garmin account credentials for authentication",
                    ],
                },
                {
                    "title": "Important Notes",
                    "content": [
                        "Each stream can use different Garmin accounts",
                        "KML feeds update based on your device's tracking settings",
                        "Connection may take 15-30 seconds due to satellite processing",
                        "Feed URLs are device-specific and unique to each InReach",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="url",
                    label="Garmin InReach KML Feed URL",
                    field_type="url",
                    required=True,
                    placeholder="https://share.garmin.com/Feed/Share/...",
                    help_text="Complete URL to your Garmin InReach KML feed from MapShare",
                ),
                PluginConfigField(
                    name="username",
                    label="Garmin Username",
                    field_type="text",
                    required=True,
                    help_text="Your Garmin Connect account username",
                ),
                PluginConfigField(
                    name="password",
                    label="Garmin Password",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Your Garmin Connect account password",
                ),
                PluginConfigField(
                    name="hide_inactive_devices",
                    label="Hide Inactive Devices",
                    field_type="checkbox",
                    required=False,
                    default_value=True,
                    help_text="Hide devices that have tracking turned off",
                ),
                PluginConfigField(
                    name="retry_delay",
                    label="Retry Delay (seconds)",
                    field_type="number",
                    required=False,
                    default_value=60,
                    min_value=30,
                    max_value=300,
                    help_text="Delay between retry attempts on connection failure",
                ),
            ],
        }

    def get_available_fields(self) -> List[FieldMetadata]:
        """Return available identifier fields for callsign mapping"""
        return [
            FieldMetadata(
                name="imei",
                display_name="Device IMEI",
                type="string",
                recommended=True,
                description="Device IMEI from Garmin extended data (most stable identifier)",
            ),
            FieldMetadata(
                name="name",
                display_name="Map Display Name",
                type="string",
                recommended=False,
                description="Device name from Garmin Map Display Name field",
            ),
            FieldMetadata(
                name="uid",
                display_name="Generated UID",
                type="string",
                recommended=False,
                description="TrakBridge generated unique identifier (name-imei)",
            ),
        ]

    def apply_callsign_mapping(
        self, tracker_data: List[dict], field_name: str, callsign_map: dict
    ) -> None:
        """Apply callsign mappings to Garmin tracker data in-place"""
        for location in tracker_data:
            # Get identifier value based on selected field
            identifier_value = None

            if field_name == "imei":
                # Extract IMEI from extended_data in additional_data
                extended_data = (
                    location.get("additional_data", {})
                    .get("raw_placemark", {})
                    .get("extended_data", {})
                )
                identifier_value = extended_data.get("IMEI")
            elif field_name == "name":
                # Use the name field (Map Display Name)
                identifier_value = location.get("name")
            elif field_name == "uid":
                # Use the generated UID
                identifier_value = location.get("uid")

            # Apply mapping if identifier found and mapping exists
            if identifier_value and identifier_value in callsign_map:
                custom_callsign = callsign_map[identifier_value]
                location["name"] = custom_callsign
                logger.debug(
                    f"[Garmin] Applied callsign mapping: {identifier_value} -> {custom_callsign}"
                )

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """Fetch location data from Garmin KML feed"""
        config = self.get_decrypted_config()

        try:
            kml_data = await self._fetch_kml_feed(session, config)

            # Handle error cases
            if kml_data is None:
                return [{"_error": "401", "_error_message": "Authentication failed"}]
            if isinstance(kml_data, dict):  # Error dictionary
                return [kml_data]

            placemarks = self.kml_extractor.extract_placemarks(kml_data)
            locations = self._process_placemarks(placemarks, config)

            logger.info(f"Successfully fetched {len(locations)} locations from Garmin")
            return locations

        except Exception as e:
            logger.error(f"Error fetching Garmin locations: {e}")
            return []

    def _process_placemarks(
        self, placemarks: List[Dict[str, Any]], config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Process placemarks into standardized location format"""
        locations = []
        hide_inactive = self._to_bool(config.get("hide_inactive_devices", True))

        for placemark in placemarks:
            if hide_inactive and self._is_device_inactive(placemark):
                logger.debug(
                    f"Skipping inactive device: {placemark.get('name', 'Unknown')}"
                )
                continue

            location = self._create_location_dict(placemark)
            locations.append(location)

        return locations

    def _create_location_dict(self, placemark: Dict[str, Any]) -> Dict[str, Any]:
        """Create standardized location dictionary from placemark"""
        actual_time = placemark.get("timestamp")
        cot_timestamp = datetime.now(timezone.utc)

        # Build description with reporting time
        base_description = placemark.get("description", "")
        if actual_time:
            time_str = actual_time.strftime("%m/%d/%Y %H:%M:%S UTC")
            remarks_addition = f"Last Reported: {time_str}"
        else:
            remarks_addition = "Reporting time unavailable"

        final_description = f"{base_description}{remarks_addition}".strip()

        return {
            "name": placemark["name"],
            "lat": float(placemark["lat"]),
            "lon": float(placemark["lon"]),
            "timestamp": cot_timestamp,
            "description": final_description,
            "uid": placemark.get("uid"),
            "additional_data": {
                "source": "garmin",
                "actual_reporting_time": actual_time,
                "hide_inactive_setting": self.config.get("hide_inactive_devices", True),
                "raw_placemark": placemark,
            },
        }

    async def _fetch_kml_feed(
        self, session: aiohttp.ClientSession, config: Dict[str, Any]
    ) -> str | Dict[str, str] | None:
        """Fetch Garmin KML feed with retry mechanism"""
        # Ensure credentials are properly encoded as strings to avoid latin-1 encoding issues
        username = str(config["username"]) if config["username"] is not None else ""
        password = str(config["password"]) if config["password"] is not None else ""
        auth = aiohttp.BasicAuth(username, password, encoding="utf-8")
        delay = int(config.get("retry_delay", 60))
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        for attempt in range(3):
            try:
                async with session.get(
                    config["url"], auth=auth, ssl=ssl_context
                ) as response:
                    if response.status == 200:
                        content = await response.text(encoding="utf-8")
                        return self._validate_kml_content(content)
                    else:
                        return await self._handle_http_error(response)

            except ssl.SSLError as ssl_err:
                logger.warning(f"SSL Error on attempt {attempt + 1}: {ssl_err}")
                # Try without SSL verification
                try:
                    async with session.get(
                        config["url"], auth=auth, ssl=False
                    ) as response:
                        if response.status == 200:
                            content = await response.text(encoding="utf-8")
                            if content and "<kml" in content:
                                logger.warning(
                                    "Using insecure SSL connection due to certificate issues"
                                )
                                return content
                except Exception as fallback_err:
                    logger.error(f"Fallback attempt failed: {fallback_err}")

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")

            if attempt < 2:  # Don't sleep after last attempt
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)

        logger.error("Failed to fetch KML feed after multiple attempts")
        return None

    @staticmethod
    def _validate_kml_content(content: str) -> str | Dict[str, str]:
        """Validate KML content"""
        if not content or content.isspace():
            logger.error("Received empty KML feed")
            return {
                "_error": "invalid_url",
                "_error_message": "Empty response from server",
            }

        if "<kml" not in content:
            logger.error("Received non-KML content")
            return {"_error": "invalid_url", "_error_message": "Invalid KML feed URL"}

        logger.info("KML Feed Successfully Fetched")
        return content

    @staticmethod
    async def _handle_http_error(response) -> Dict[str, str]:
        """Handle HTTP error responses"""
        error_messages = {
            401: "Unauthorized access. Check Garmin credentials.",
            403: "Forbidden access. Check user permissions.",
            404: "Resource not found. Check the KML feed URL.",
        }

        error_text = await response.text(encoding="utf-8")
        message = error_messages.get(
            response.status, f"HTTP {response.status}: {error_text}"
        )
        logger.error(message)
        # Return error format expected by COT service
        return {"_error": str(response.status), "_error_message": message}

    @staticmethod
    def _is_device_inactive(placemark: Dict[str, Any]) -> bool:
        """Check if device is inactive based on ExtendedData Event field"""
        try:
            extended_data = placemark.get("extended_data", {})
            event_value = extended_data.get("Event", "")
            return event_value and "tracking turned off" in event_value.lower()
        except Exception as e:
            logger.debug(f"Error checking device activity status: {e}")
            return False

    @staticmethod
    def _to_bool(val, default=False) -> bool:
        """Convert various types to boolean"""
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "1", "on", "yes")
        if isinstance(val, int):
            return val != 0
        return default

    def validate_config(self) -> bool:
        """Enhanced validation for Garmin-specific configuration"""
        if not super().validate_config():
            return False

        url = self.config.get("url", "")
        if "garmin.com" not in url.lower():
            logger.warning("URL does not appear to be a Garmin feed URL")

        # Ensure retry_delay is properly typed
        retry_delay = self.config.get("retry_delay", 60)
        if isinstance(retry_delay, str):
            try:
                self.config["retry_delay"] = int(retry_delay)
            except ValueError:
                logger.error("retry_delay must be a valid integer")
                return False

        return True


class TimestampParser:
    """Centralized timestamp parsing utility"""

    FORMATS = ["%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]

    @classmethod
    def parse(cls, timestamp_str: str) -> Optional[datetime]:
        """Parse timestamp from various formats"""
        if not timestamp_str:
            return None

        # Handle ISO format with Z suffix
        if timestamp_str.endswith("Z"):
            try:
                return datetime.fromisoformat(
                    timestamp_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass

        # Try other formats
        for fmt in cls.FORMATS:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue

        logger.debug(f"Could not parse timestamp: {timestamp_str}")
        return None


class KMLDataExtractor:
    """Handles KML data extraction and parsing"""

    KML_NAMESPACE = {"kml": "http://www.opengis.net/kml/2.2"}

    def __init__(self):
        self.logger = logger

    def extract_placemarks(self, kml_data: str) -> List[Dict[str, Any]]:
        """Main entry point for extracting placemarks from KML data"""
        try:
            # Try fastkml first
            placemarks = self._extract_with_fastkml(kml_data)
            if placemarks:
                return placemarks

            # Fallback to XML parsing
            return self._extract_with_xml(kml_data)

        except Exception as e:
            logger.error(f"Error parsing KML data: {e}")
            return []

    def _extract_with_fastkml(self, kml_data: str) -> List[Dict[str, Any]]:
        """Extract placemarks using fastkml library"""
        try:
            k = kml.KML()
            # fastkml.from_string() expects string input, not bytes
            k.from_string(kml_data)

            placemarks = []
            self._traverse_features(k.features, placemarks)
            return placemarks

        except Exception as e:
            logger.debug(f"FastKML parsing failed: {e}")
            return []

    def _traverse_features(self, features, placemarks: List[Dict[str, Any]]):
        """Recursively traverse KML features to find Point placemarks"""
        if not features:
            return

        for feature in features:
            if hasattr(feature, "features") and feature.features:
                self._traverse_features(feature.features, placemarks)
            elif self._is_point_placemark(feature):
                placemark_data = self._extract_placemark_data(feature)
                if placemark_data:
                    placemarks.append(placemark_data)

    @staticmethod
    def _is_point_placemark(feature) -> bool:
        """Check if feature is a Point placemark"""
        return (
            hasattr(feature, "geometry")
            and feature.geometry
            and "Point" in type(feature.geometry).__name__
        )

    def _extract_placemark_data(self, feature) -> Optional[Dict[str, Any]]:
        """Extract data from a single placemark feature"""
        try:
            coords = self._get_coordinates(feature.geometry)
            if not coords:
                return None

            lon, lat = coords
            extended_data = self._extract_extended_data(feature)
            placemark_id = self._extract_device_imei(
                extended_data, getattr(feature, "name", "Unknown")
            )

            # Use Map Display Name from extended data with fallback to feature name
            name = extended_data.get("Map Display Name", "Unknown")
            # Fallback to feature name if Map Display Name is not available
            if name == "Unknown":
                name = str(getattr(feature, "name", "Unknown"))

            clean_name = str(name).replace(" ", "")
            clean_id = str(placemark_id).replace(" ", "")

            return {
                "uid": f"{clean_name}-{clean_id}",
                "name": name,
                "lat": lat,
                "lon": lon,
                "description": getattr(feature, "description", "") or "",
                "timestamp": self._extract_timestamp(feature),
                "extended_data": extended_data,
            }

        except Exception as e:
            logger.warning(f"Error extracting placemark data: {e}")
            return None

    @staticmethod
    def _get_coordinates(geometry) -> Optional[tuple]:
        """Extract coordinates from geometry"""
        try:
            coords = getattr(geometry, "coords", None) or getattr(
                geometry, "coordinates", None
            )
            if not coords:
                return None

            if isinstance(coords, list) and coords:
                coord_pair = (
                    coords[0] if isinstance(coords[0], (list, tuple)) else coords
                )
                return coord_pair[0], coord_pair[1]

        except (IndexError, AttributeError, TypeError):
            pass
        return None

    @staticmethod
    def _extract_extended_data(feature) -> Dict[str, Any]:
        """Extract extended data from feature"""
        extended_data = {}
        try:
            if hasattr(feature, "extended_data") and feature.extended_data:
                for data in feature.extended_data:
                    if hasattr(data, "name") and hasattr(data, "value"):
                        extended_data[data.name] = data.value
        except Exception as e:
            logger.debug(f"Error extracting extended data: {e}")
        return extended_data

    @staticmethod
    def _extract_timestamp(feature) -> Optional[datetime]:
        """Extract timestamp from feature"""
        # Check TimeStamp element
        if hasattr(feature, "timestamp") and feature.timestamp:
            return TimestampParser.parse(feature.timestamp)

        # Check ExtendedData
        if hasattr(feature, "extended_data") and feature.extended_data:
            for data in feature.extended_data:
                if hasattr(data, "name") and data.name in ["Time UTC", "Time"]:
                    return TimestampParser.parse(data.value)

        return None

    def _extract_with_xml(self, kml_data: str) -> List[Dict[str, Any]]:
        """Fallback XML parsing for KML data"""
        try:
            root = ET.fromstring(kml_data)
            placemarks_xml = root.findall(".//kml:Placemark", self.KML_NAMESPACE)

            placemarks = []
            for placemark_xml in placemarks_xml:
                if self._xml_has_point(placemark_xml):
                    placemark_data = self._extract_xml_placemark(placemark_xml)
                    if placemark_data:
                        placemarks.append(placemark_data)

            return placemarks

        except Exception as e:
            logger.error(f"XML parsing failed: {e}")
            return []

    def _xml_has_point(self, placemark_xml) -> bool:
        """Check if XML placemark has Point geometry"""
        return placemark_xml.find(".//kml:Point", self.KML_NAMESPACE) is not None

    def _extract_xml_placemark(self, placemark_xml) -> Optional[Dict[str, Any]]:
        """Extract placemark data from XML element"""
        try:
            # Get coordinates
            coords_elem = placemark_xml.find(
                ".//kml:Point/kml:coordinates", self.KML_NAMESPACE
            )
            if coords_elem is None:
                return None

            coords_text = coords_elem.text.strip()
            coord_parts = coords_text.split(",")
            if len(coord_parts) < 2:
                return None

            lon, lat = float(coord_parts[0]), float(coord_parts[1])

            # Get other data
            desc_elem = placemark_xml.find("kml:description", self.KML_NAMESPACE)
            description = desc_elem.text if desc_elem is not None else ""

            extended_data = self._extract_xml_extended_data(placemark_xml)

            # Use Map Display Name from extended data (consistent with fastkml parsing)
            name = extended_data.get("Map Display Name", "Unknown")
            # Fallback to <name> element if Map Display Name is not available
            if name == "Unknown":
                name_elem = placemark_xml.find("kml:name", self.KML_NAMESPACE)
                name = name_elem.text if name_elem is not None else "Unknown"

            placemark_id = self._extract_device_imei(extended_data, name)

            clean_name = str(name).replace(" ", "")
            clean_id = str(placemark_id).replace(" ", "")

            return {
                "uid": f"{clean_name}-{clean_id}",
                "name": name,
                "lat": lat,
                "lon": lon,
                "description": description,
                "timestamp": self._extract_xml_timestamp(placemark_xml),
                "extended_data": extended_data,
            }

        except (ValueError, IndexError) as e:
            logger.warning(f"Error parsing XML placemark: {e}")
            return None

    def _extract_xml_extended_data(self, placemark_xml) -> Dict[str, Any]:
        """Extract extended data from XML"""
        extended_data = {}
        try:
            extended_elem = placemark_xml.find("kml:ExtendedData", self.KML_NAMESPACE)
            if extended_elem is not None:
                for data_elem in extended_elem.findall("kml:Data", self.KML_NAMESPACE):
                    name_attr = data_elem.get("name")
                    value_elem = data_elem.find("kml:value", self.KML_NAMESPACE)
                    if name_attr and value_elem is not None:
                        extended_data[name_attr] = value_elem.text
        except Exception as e:
            logger.debug(f"Error extracting XML extended data: {e}")
        return extended_data

    def _extract_xml_timestamp(self, placemark_xml) -> Optional[datetime]:
        """Extract timestamp from XML elements"""
        # Check TimeStamp element
        timestamp_elem = placemark_xml.find(
            ".//kml:TimeStamp/kml:when", self.KML_NAMESPACE
        )
        if timestamp_elem is not None:
            return TimestampParser.parse(timestamp_elem.text)

        # Check ExtendedData
        extended_elem = placemark_xml.find("kml:ExtendedData", self.KML_NAMESPACE)
        if extended_elem is not None:
            for data_elem in extended_elem.findall("kml:Data", self.KML_NAMESPACE):
                if data_elem.get("name") in ["Time UTC", "Time"]:
                    value_elem = data_elem.find("kml:value", self.KML_NAMESPACE)
                    if value_elem is not None:
                        parsed = TimestampParser.parse(value_elem.text)
                        if parsed:
                            return parsed

        return None

    def _extract_device_imei(
        self, extended_data: Dict[str, Any], device_name: str
    ) -> str:
        """Extract IMEI with multiple fallback strategies to avoid 'Unknown' identifiers"""
        # Primary: Standard IMEI field
        imei = extended_data.get("IMEI")
        if imei and imei.strip() and imei.strip().lower() != "unknown":
            logger.debug(f"[Garmin] Found IMEI from primary field: {imei}")
            return imei.strip()

        # Fallback 1: Alternative IMEI field names
        for field_name in ["Device IMEI", "IMEI Number", "Device ID", "ESN"]:
            imei = extended_data.get(field_name)
            if imei and imei.strip() and imei.strip().lower() != "unknown":
                logger.debug(f"[Garmin] Found IMEI from {field_name}: {imei}")
                return imei.strip()

        # Fallback 2: Extract from device name if it contains IMEI-like pattern
        if device_name and device_name != "Unknown":
            # Look for 15-digit IMEI pattern in device name
            import re

            imei_pattern = re.search(r"\b\d{15}\b", device_name)
            if imei_pattern:
                logger.debug(
                    f"[Garmin] Extracted IMEI from device name: {imei_pattern.group()}"
                )
                return imei_pattern.group()

        # Fallback 3: Generate stable identifier from other extended data
        stable_fields = [
            "In Emergency",
            "Latitude",
            "Longitude",
            "Elevation (ft)",
            "Velocity (mph)",
            "Course",
            "Valid GPS Fix",
        ]
        for field_name in stable_fields:
            value = extended_data.get(field_name)
            if value and str(value).strip():
                # Create a hash-based stable identifier from field name + first non-empty value
                import hashlib

                stable_id = hashlib.md5(f"{field_name}:{value}".encode()).hexdigest()[
                    :12
                ]
                logger.warning(
                    f"[Garmin] IMEI not found, using generated stable ID from {field_name}: {stable_id}"
                )
                return f"GEN-{stable_id}"

        # Final fallback: Use device name if available
        if device_name and device_name != "Unknown":
            import re

            clean_name = re.sub(r"[^a-zA-Z0-9]", "", device_name)[:12]
            if clean_name:
                logger.warning(
                    f"[Garmin] IMEI not found, using cleaned device name: {clean_name}"
                )
                return f"DEV-{clean_name}"

        # Last resort: Generate based on timestamp to ensure uniqueness
        from datetime import datetime

        timestamp_id = str(int(datetime.now().timestamp()))[-8:]
        logger.error(
            f"[Garmin] IMEI extraction failed completely, using timestamp-based ID: TS-{timestamp_id}"
        )
        return f"TS-{timestamp_id}"
