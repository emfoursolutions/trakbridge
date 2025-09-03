"""
File: plugins/deepstate_plugin.py

Description:
    Simplified plugin implementation for fetching and processing location data from 
    the Deepstate OSINT platform. Connects to the Deepstate API to retrieve the 
    latest battlefield positions and events from Ukraine. The plugin fetches data 
    from the public API endpoint and processes only Point-type GeoJSON features.

    Key features:
    - Fetches latest battlefield data from Deepstate OSINT platform
    - Processes only Point-type GeoJSON features
    - Parses English names from multilingual name fields using regex
    - Generates hash-based IDs using DEEPSTATE + English name
    - Filters out "Direction of attack" records
    - Normalizes position data into standardized location format

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: 2025-07-21
Version: 1.0.0
"""

# Standard library imports
import asyncio
import hashlib
import json
import logging
from services.logging_service import get_module_logger
import re
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Third-party imports
import aiohttp
import certifi

# Local application imports
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField

# Module-level logger
logger = get_module_logger(__name__)


class DeepstatePlugin(BaseGPSPlugin):
    """Simplified plugin for fetching data from Deepstate OSINT platform"""

    PLUGIN_NAME = "deepstate"
    DEFAULT_API_URL = "https://deepstatemap.live/api/history/last"

    # Regex pattern to extract English name from multilingual strings
    ENGLISH_NAME_PATTERN = re.compile(
        r"///[ \t\u00A0]*([A-Za-z0-9\-.,' ]+?)[ \t\u00A0]*///", re.UNICODE
    )

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
            "display_name": "Deepstate OSINT Platform",
            "description": "Connect to DeepstateMAP OSINT platform to fetch "
            "latest battlefield positions and events from Ukraine. ",
            "icon": "fas fa-map-marked-alt",
            "category": "osint",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "No authentication required - uses public Deepstate API",
                        "Default API endpoint: https://deepstatemap.live/api/history/last",
                        "Fetches latest battlefield positions and military events",
                        "Only processes point-type features (ignores polygons/lines)",
                        "Automatically extracts English names from multilingual fields",
                        "Data is automatically updated from OSINT sources",
                        "If the COT Type Mode is set to Determine COT Type Per Point",
                        "COT Type selection will be used for Unknown Points.",
                    ],
                },
                {
                    "title": "API Information",
                    "content": [
                        "Uses Deepstate's public REST API",
                        "No authentication required",
                        "Returns latest battlefield events and positions",
                        "Data includes coordinates, timestamps, and event descriptions",
                        "Updates frequently with new OSINT intelligence",
                        "Filters for point features only",
                    ],
                },
                {
                    "title": "Data Processing",
                    "content": [
                        "Filters out non-point geometries (polygons, lines, etc.)",
                        "Extracts English names using regex pattern matching",
                        "Generates unique IDs using hash of 'DEEPSTATE' + English name",
                        "Military unit positions and movements",
                        "Battlefield events and incidents",
                        "Infrastructure damage reports",
                        "Territory control changes",
                        "All data sourced from open-source intelligence",
                    ],
                },
                {
                    "title": "Security Notes",
                    "content": [
                        "Uses HTTPS for secure data transmission",
                        "Public API - no sensitive credentials required",
                        "Data is from open-source intelligence only",
                        "Monitor usage to avoid rate limiting",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="api_url",
                    label="Deepstate API URL",
                    field_type="url",
                    required=True,
                    default_value="https://deepstatemap.live/api/history/last",
                    placeholder="https://deepstatemap.live/api/history/last",
                    help_text="URL to the Deepstate API endpoint (default is latest history)",
                ),
                PluginConfigField(
                    name="cot_type_mode",
                    label="COT Type Mode",
                    field_type="select",
                    required=False,
                    default_value="per_point",
                    options=[
                        {
                            "value": "stream",
                            "label": "Use stream COT type for all points",
                        },
                        {"value": "per_point", "label": "Determine COT type per point"},
                    ],
                    help_text="Choose whether to use the stream's COT type for all "
                    "points or determine COT type individually for each point",
                ),
                PluginConfigField(
                    name="timeout",
                    label="Request Timeout (seconds)",
                    field_type="number",
                    required=False,
                    default_value=30,
                    min_value=5,
                    max_value=120,
                    help_text="HTTP request timeout in seconds",
                ),
                PluginConfigField(
                    name="max_events",
                    label="Maximum Events",
                    field_type="number",
                    required=False,
                    default_value=100,
                    min_value=1,
                    max_value=1000,
                    help_text="Maximum number of events to fetch and process",
                ),
            ],
        }

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """
        Create SSL context with proper configuration to avoid certificate verification issues

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

    def _extract_english_name(self, name_field: str) -> str:
        """
        Extract English name from multilingual name field using regex

        Args:
            name_field: Name field that may contain multilingual text

        Returns:
            Extracted English name or cleaned version of original name
        """
        if not name_field or not isinstance(name_field, str):
            return "Unknown Location"

        name_field = name_field.strip()

        # Try to match the English name pattern

        match = self.ENGLISH_NAME_PATTERN.search(name_field)
        if match:
            english_name = match.group(1).strip()
            # Clean up the extracted name
            english_name = re.sub(r"\s+", " ", english_name)  # Normalize whitespace
            return english_name if english_name else "Unknown Location"

        # Last resort - return a cleaned version
        return "Unknown Location"

    @staticmethod
    def _generate_point_id(english_name: str) -> str:
        """
        Generate a unique ID by hashing 'DEEPSTATE' + English name

        Args:
            english_name: Extracted English name for the point

        Returns:
            SHA-256 hash string (first 16 characters for brevity)
        """
        source_string = f"DEEPSTATE{english_name}"
        hash_obj = hashlib.sha256(source_string.encode("utf-8"))
        return hash_obj.hexdigest()[:16]  # Return first 16 characters

    @staticmethod
    def _should_process_feature(feature: Dict[str, Any]) -> bool:
        """
        Check if a feature should be processed based on type and content
        """
        # Check if it's a Point geometry
        geometry = feature.get("geometry", {})
        geometry_type = geometry.get("type")

        if geometry_type != "Point":
            logger.debug(f"Skipping non-Point geometry: {geometry_type}")
            return False

        # Extract and check the name
        properties = feature.get("properties", {})
        name = properties.get("name", "")

        # Skip if name contains "Direction of attack"
        if "Direction of attack" in name:
            logger.debug(f"Skipping 'Direction of attack' feature: {name}")
            return False

        logger.debug(f"Processing Point feature: {name}")
        return True

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """
        Fetch location data from Deepstate API

        Returns:
            List of location dictionaries with standardized format
        """
        connector = None
        try:
            # Get decrypted configuration
            config = self.get_decrypted_config()

            # Create a new session with proper SSL configuration if needed
            if not hasattr(session, "_connector") or session._connector is None:
                connector = self._create_connector()
                timeout = aiohttp.ClientTimeout(total=int(config.get("timeout", 30)))

                async with aiohttp.ClientSession(
                    connector=connector, timeout=timeout
                ) as custom_session:
                    return await self._fetch_locations_with_session(
                        custom_session, config
                    )
            else:
                return await self._fetch_locations_with_session(session, config)

        except Exception as e:
            logger.error(f"Error fetching Deepstate locations: {e}")
            return [{"_error": "unknown", "_error_message": str(e)}]
        finally:
            # Clean up connector if we created one
            if connector and not connector.closed:
                try:
                    await connector.close()
                except Exception as close_error:
                    logger.debug(
                        f"Error closing connector (non-critical): {close_error}"
                    )

    async def _fetch_locations_with_session(
        self, session: aiohttp.ClientSession, config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Internal method to fetch locations with a given session
        """
        try:
            api_url = config.get("api_url", self.DEFAULT_API_URL)
            timeout = int(config.get("timeout", 30))
            max_events = int(config.get("max_events", 100))

            # Create timeout configuration
            timeout_config = aiohttp.ClientTimeout(total=timeout)

            # Create SSL context for certificate verification
            ssl_context = self._create_ssl_context()

            headers = {
                "User-Agent": "TAK-GPS-Bridge/1.0",
                "Accept": "application/json",
            }
            logger.info(f"API Url: {api_url}")
            logger.info(f"Deepstate Plugin Config: {config}")
            logger.info(
                f"CoT Type Mode from config: {config.get('cot_type_mode', 'per_point')}"
            )

            async with session.get(
                api_url, timeout=timeout_config, headers=headers, ssl=ssl_context
            ) as response:
                if response.status != 200:
                    error_text = await response.text(encoding="utf-8")
                    logger.error(
                        f"API request failed with status {response.status}: {error_text}"
                    )
                    return [
                        {
                            "_error": str(response.status),
                            "_error_message": f"HTTP {response.status} error",
                        }
                    ]

                data = await response.json()
                logger.info(f"Raw API response type: {type(data)}")
                # logger.info(f"Raw API response: {data}")

                # Handle different response formats
                features = []
                if isinstance(data, dict):
                    # Try different possible structures
                    if "map" in data and isinstance(data["map"], dict):
                        features = data["map"].get("features", [])
                        logger.info(
                            f"Found {len(features)} features in nested map structure"
                        )
                    elif "features" in data:
                        features = data.get("features", [])
                        logger.info(
                            f"Found {len(features)} features in direct structure"
                        )
                    else:
                        logger.error(
                            f"No features found in dict response. Available keys: {list(data.keys())}"
                        )
                        return [
                            {
                                "_error": "json_error",
                                "_error_message": "No features found in response",
                            }
                        ]
                elif isinstance(data, list):
                    features = data
                    logger.info(f"Found {len(features)} features in list response")
                else:
                    logger.error(f"Unexpected data format: {type(data)}")
                    return [
                        {
                            "_error": "json_error",
                            "_error_message": "Unexpected data format",
                        }
                    ]

                logger.info(f"Features to process: {len(features)}")
                if features:
                    logger.info(f"First feature: {features[0]}")

                # Get the CoT type mode and stream's default CoT type from stream object
                logger.info(f"DEBUG: hasattr(self, 'stream')={hasattr(self, 'stream')}")
                if hasattr(self, "stream"):
                    logger.info(
                        f"DEBUG: self.stream is not None={self.stream is not None}"
                    )
                    if self.stream:
                        logger.info(
                            f"DEBUG: stream.id={getattr(self.stream, 'id', 'No ID')}"
                        )
                        logger.info(
                            f"DEBUG: stream.cot_type_mode (direct)={getattr(self.stream, 'cot_type_mode', 'NOT_FOUND')}"
                        )
                        logger.info(
                            f"DEBUG: stream.cot_type (direct)={getattr(self.stream, 'cot_type', 'NOT_FOUND')}"
                        )
                        logger.info(
                            f"DEBUG: stream attributes={[attr for attr in dir(self.stream) if not attr.startswith('_')]}"
                        )

                if hasattr(self, "stream") and self.stream:
                    cot_type_mode = getattr(self.stream, "cot_type_mode", "per_point")
                    stream_default_cot_type = getattr(
                        self.stream, "cot_type", "a-f-G-U-C"
                    )
                    logger.info(
                        f"Using stream-level configuration: cot_type_mode={cot_type_mode}, cot_type={stream_default_cot_type}"
                    )
                else:
                    # Fallback to config if stream not available
                    cot_type_mode = config.get("cot_type_mode", "per_point")
                    stream_default_cot_type = config.get("cot_type", "a-f-G-U-C")
                    logger.warning(
                        f"No stream object available, using plugin config fallback: cot_type_mode={cot_type_mode}, cot_type={stream_default_cot_type}"
                    )

                logger.info(
                    f"FINAL VALUES USED: cot_type_mode={cot_type_mode}, stream_default_cot_type={stream_default_cot_type}"
                )

                # Process features
                locations = []
                processed_count = 0

                logger.info(f"Starting to process {len(features)} total features")

                point_features = 0
                for feature in features:
                    if processed_count >= max_events:
                        logger.debug(f"Reached max_events limit ({max_events})")
                        break

                    geometry_type = feature.get("geometry", {}).get("type", "Unknown")
                    feature_name = feature.get("properties", {}).get("name", "Unknown")

                    logger.debug(
                        f"Checking feature: {feature_name} (geometry: {geometry_type})"
                    )

                    if not self._should_process_feature(feature):
                        continue

                    point_features += 1
                    # Pass the stream's CoT type and mode to the conversion function
                    logger.info(
                        f"Converting feature with mode={cot_type_mode}, default_cot={stream_default_cot_type}"
                    )
                    location = self._convert_feature_to_location(
                        feature, stream_default_cot_type, cot_type_mode
                    )
                    if location:
                        locations.append(location)
                        processed_count += 1
                        logger.debug(
                            f"Successfully converted Point feature: {feature_name}"
                        )
                    else:
                        logger.debug(f"Failed to convert Point feature: {feature_name}")

                logger.info(
                    f"Found {point_features} Point features out of {len(features)} total features"
                )
                logger.info(f"Successfully processed {len(locations)} locations")
                return locations

        except asyncio.TimeoutError:
            logger.error("Request timed out while fetching events from Deepstate")
            return [{"_error": "timeout", "_error_message": "Request timed out"}]
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error: {e}")
            return [{"_error": "connection_failed", "_error_message": str(e)}]
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response: {e}")
            return [{"_error": "json_error", "_error_message": "Invalid JSON response"}]
        except Exception as e:
            logger.error(f"Unexpected error fetching events: {e}")
            return [{"_error": "unknown", "_error_message": str(e)}]

    def _convert_feature_to_location(
        self,
        feature: Dict[str, Any],
        default_cot_type: str = "a-n-G",
        cot_type_mode: str = "per_point",
    ) -> Optional[Dict[str, Any]]:
        """
        Convert GeoJSON feature to standardized location format

        Args:
            feature: GeoJSON feature from Deepstate API
            default_cot_type: Default COT type from stream configuration
            cot_type_mode: Mode for COT type determination ("stream" or "per_point")

        Returns:
            Standardized location dictionary or None if invalid
        """
        try:
            # Extract coordinates from Point geometry
            geometry = feature.get("geometry", {})
            coordinates = geometry.get("coordinates", [])

            if len(coordinates) < 2:
                logger.debug("Invalid coordinates in feature")
                return None

            lon, lat = float(coordinates[0]), float(coordinates[1])

            # Extract name from properties
            properties = feature.get("properties", {})
            raw_name = properties.get("name", "")
            logger.debug(f"Raw Name: {raw_name}")

            # Extract English name using regex
            english_name = self._extract_english_name(raw_name)
            logger.debug(f"English Name: {english_name}")

            # Generate unique ID
            event_id = self._generate_point_id(english_name)

            # Get COT type based on the configured mode
            logger.info(
                f"DEBUG FEATURE: name='{english_name}', mode='{cot_type_mode}', default_cot='{default_cot_type}'"
            )
            if cot_type_mode == "stream":
                # Use stream COT type for all points (no per-point analysis)
                cot_type = default_cot_type
                logger.info(
                    f"DEBUG STREAM MODE: Using fixed COT type '{cot_type}' for '{english_name}'"
                )
            else:
                # Use per-point COT type determination with stream COT type as fallback
                cot_type = self._get_cot_type(
                    english_name, properties, default_cot_type
                )
                logger.info(
                    f"DEBUG PER-POINT MODE: Analyzed COT type '{cot_type}' for '{english_name}'"
                )
            logger.debug(f"COT Type: {cot_type}")

            # Build description
            description = (
                f"Location: {english_name} | "
                f"Source: Deepstate OSINT | "
                f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} "
                f"UTC"
            )

            # Create standardized location
            location = {
                "name": english_name,
                "lat": lat,
                "lon": lon,
                "timestamp": datetime.now(timezone.utc),
                "description": description,
                "uid": f"deepstate-{event_id}",
                "cot_type": cot_type,
                "additional_data": {
                    "source": "deepstate",
                    "event_id": event_id,
                    "raw_name": raw_name,
                    "english_name": english_name,
                    "raw_feature": feature,
                },
            }
            logger.info(
                f"Processed Location CoT Type: {location.get('cot_type', 'UNKNOWN')} (Mode: {cot_type_mode})"
            )
            logger.debug(f"Processed Location: {location}")
            return location

        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Error converting feature to location: {e}")
            return None

    @staticmethod
    def _get_cot_type(
        english_name: str,
        properties: Dict[str, Any] = None,
        default_cot_type: str = "a-n-G",
    ) -> str:
        """
        Analyze English name and assign COT type based on content patterns

        Args:
            english_name: The extracted English name
            properties: Additional properties from the feature (optional)
            default_cot_type: Default COT type to use if no patterns match (from stream config)

        Returns:
            COT type string
        """
        # Convert to lowercase for case-insensitive matching
        name_id = english_name.lower()
        cot_type = (
            default_cot_type  # Use the passed default instead of hardcoded "a-n-G"
        )

        # Check properties first for specific markers
        if properties and properties.get("description") == "{icon=enemy}":
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif properties and properties.get("description") == "{icon=headquarter}":
            cot_type = "a-h-G-U-H"  # Hostile ground unit combat infantry
        # Location-based classifications
        elif "kyiv" in name_id:
            cot_type = "a-n-G-I-G"  # Neutral ground installation general
        elif "moscow" in name_id or "minsk" in name_id:
            cot_type = "a-h-G-I-G"  # Hostile ground installation general
        # Military unit classifications
        elif "motorized rifle" in name_id:
            cot_type = "a-h-G-U-C-I-M"  # Hostile ground unit combat infantry mechanized
        elif "motor rifle" in name_id:
            cot_type = "a-h-G-U-C-I-M"  # Hostile ground unit combat infantry mechanized
        elif "somalia" in name_id:
            cot_type = "a-h-G-U-C-A"  # Hostile ground unit combat armor
        elif "piatnashka" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "rifle" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "pmc" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "dpr" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "lpr" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "bars" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        elif "rosguard" in name_id:
            cot_type = "a-h-G-U-C-I"  # Hostile ground unit combat infantry
        # Specialized unit types
        elif "artillery" in name_id:
            cot_type = "a-h-G-U-C-F"  # Hostile ground unit combat field artillery
        elif "tank" in name_id:
            cot_type = "a-h-G-U-C-A"  # Hostile ground unit combat armor
        elif "airborne" in name_id:
            cot_type = "a-h-G-U-C-I-A"  # Hostile ground unit combat infantry airborne
        elif "paratrooper" in name_id:
            cot_type = "a-h-G-U-C-I-A"  # Hostile ground unit combat infantry airborne
        elif "air assault" in name_id:
            cot_type = (
                "a-h-G-U-C-I-S"  # Hostile ground unit combat infantry air assault
            )
        elif "coastal defense" in name_id:
            cot_type = "a-h-G-U-C-I-N"  # Hostile ground unit combat infantry naval
        elif "marine" in name_id:
            cot_type = "a-h-G-U-C-I-N"  # Hostile ground unit combat infantry naval
        elif "naval infantry" in name_id:
            cot_type = "a-h-G-U-C-I-N"  # Hostile ground unit combat infantry naval
        # Infrastructure and installations
        elif any(
            keyword in name_id
            for keyword in [
                "airport",
                "airfield",
                "aerodrom",
                "air base",
                "helicopter base",
            ]
        ):
            cot_type = "a-h-G-I-B-A"  # Hostile ground installation base airfield
        # Special operations
        elif "special purpose" in name_id:
            cot_type = "a-h-F"  # Hostile special operations forces
        elif "spetsnaz" in name_id:
            cot_type = "a-h-F"  # Hostile special operations forces
        # Support units
        elif "engineer" in name_id:
            cot_type = "a-h-G-U-C-E"  # Hostile ground unit combat engineer
        elif "reconnaissance" in name_id:
            cot_type = "a-h-G-U-C-R"  # Hostile ground unit combat reconnaissance
        elif "intelligence" in name_id:
            cot_type = "a-h-G-U-U-M"  # Hostile ground unit military intelligence
        # Weapons systems
        elif "cruise" in name_id:
            cot_type = (
                "a-h-S-C-L-C-C"  # Hostile sea surface combatant line combatant cruiser
            )
        return cot_type

    def validate_config(self) -> bool:
        """
        Validate configuration for Deepstate plugin
        """
        # Run base validation first
        if not super().validate_config():
            return False

        config = self.get_decrypted_config()

        # Validate API URL
        api_url = config.get("api_url", "")
        if not api_url:
            logger.error("API URL is required")
            return False

        if not api_url.startswith(("http://", "https://")):
            logger.error("API URL must start with http:// or https://")
            return False

        # Validate numeric fields
        for field_name in ["timeout", "max_events"]:
            value = config.get(field_name)
            if value is not None and str(value).strip() != "":
                try:
                    num_value = int(value)
                    if field_name == "timeout" and (num_value < 5 or num_value > 120):
                        logger.error("Timeout must be between 5 and 120 seconds")
                        return False
                    elif field_name == "max_events" and (
                        num_value < 1 or num_value > 1000
                    ):
                        logger.error("Max events must be between 1 and 1000")
                        return False
                except (ValueError, TypeError):
                    logger.error(f"Field '{field_name}' must be a valid integer")
                    return False

        return True
