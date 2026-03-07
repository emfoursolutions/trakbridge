# ABOUTME: LiveUAMap OSINT plugin for fetching geolocated news/conflict events
# ABOUTME: Fetches venues from LiveUAMap API across multiple regions and converts them to CoT markers

# Standard library imports
import asyncio
import json
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Third-party imports
import aiohttp
import certifi

# Local application imports
from plugins.base_plugin import (
    BaseGPSPlugin,
    PluginConfigField,
    PluginCustomComponent,
)
from services.logging_service import get_module_logger

# Module-level logger
logger = get_module_logger(__name__)


class LiveuamapPlugin(BaseGPSPlugin):
    """Plugin for fetching geolocated OSINT events from the LiveUAMap API"""

    PLUGIN_NAME = "liveuamap"

    # Region name → API resid mapping
    # Source: LiveUAMap settings page region checkboxes
    REGIONS = {
        # International/Conflict
        "Ukraine": 0,
        "World": 1,
        "Israel-Palestine": 2,
        "Syria": 3,
        "Caucasus": 4,
        "Asia": 6,
        "Middle East": 7,
        "Africa": 8,
        "Korea": 9,
        "Europe": 10,
        "America": 11,
        "Hong Kong": 12,
        "Egypt": 16,
        "Russia": 18,
        "Turkiye": 19,
        "Hungary": 20,
        "Belarus": 31,
        "Balkans": 29,
        "Poland": 30,
        "Baltics": 52,
        "Yemen": 53,
        "Libya": 54,
        "Kashmir": 55,
        "Afghanistan": 56,
        "Central Asia": 57,
        "Colombia": 63,
        "Brazil": 64,
        "Iraq": 65,
        "Iran": 66,
        "Pakistan": 69,
        "Venezuela": 70,
        "Philippines": 72,
        "Qatar": 73,
        "Lebanon": 74,
        "Mexico": 133,
        "Kenya": 135,
        "Moldova": 137,
        "Somalia": 138,
        "Ireland": 139,
        "Guyana": 140,
        "UK": 141,
        "Taiwan": 142,
        "Uganda": 144,
        "Spain": 146,
        "Sudan": 147,
        "Myanmar": 148,
        "Japan": 149,
        "Vietnam": 150,
        "Thailand": 151,
        "DR Congo": 152,
        "Bangladesh": 153,
        "Caribbean": 154,
        "South Africa": 155,
        "Indonesia": 156,
        "Tanzania": 157,
        "Nigeria": 158,
        "Ethiopia": 159,
        "North Europe": 160,
        "Germany": 161,
        "France": 162,
        "Italy": 163,
        "Sahel": 166,
        "Nicaragua": 167,
        "Latin America": 169,
        "Canada": 170,
        "CAR": 171,
        "Sri Lanka": 172,
        "Maldives": 173,
        "Zimbabwe": 174,
        "Tunisia": 175,
        "Algeria": 176,
        "Honduras": 178,
        "Saudi Arabia": 179,
        "Cameroon": 180,
        "Central & Eastern Europe": 129,
        # US States
        "California": 75,
        "Texas": 76,
        "Florida": 77,
        "New York": 78,
        "Illinois": 79,
        "Pennsylvania": 80,
        "Ohio": 81,
        "Georgia (US)": 82,
        "North Carolina": 83,
        "Michigan": 84,
        "New Jersey": 85,
        "Virginia": 86,
        "Washington": 87,
        "Massachusetts": 88,
        "Arizona": 89,
        "Indiana": 90,
        "Tennessee": 91,
        "Missouri": 92,
        "Maryland": 93,
        "Wisconsin": 94,
        "Minnesota": 95,
        "Colorado": 96,
        "Alabama": 97,
        "South Carolina": 98,
        "Louisiana": 99,
        "Oregon": 101,
        "Oklahoma": 102,
        "Connecticut": 103,
        "Iowa": 104,
        "Arkansas": 105,
        "Mississippi": 106,
        "Utah": 107,
        "Kansas": 108,
        "Nevada": 109,
        "New Mexico": 110,
        "Nebraska": 111,
        "West Virginia": 112,
        "Idaho": 113,
        "Hawaii": 114,
        "Maine": 115,
        "New Hampshire": 116,
        "Rhode Island": 117,
        "Montana": 118,
        "Delaware": 119,
        "South Dakota": 120,
        "North Dakota": 121,
        "Alaska": 122,
        "Vermont": 123,
        "Wyoming": 124,
        "District of Columbia": 125,
        "Kentucky": 126,
        "Puerto Rico": 128,
        # Organizations/Topics
        "ISIS": 5,
        "Women": 14,
        "US Protests": 15,
        "Trade Wars": 17,
        "Cyberwar": 21,
        "USA": 22,
        "Pacific": 23,
        "China": 24,
        "India": 26,
        "Disasters": 27,
        "Human Rights": 28,
        "Travel": 32,
        "War": 33,
        "Avia": 34,
        "Life Style": 35,
        "Epidemics": 36,
        "Sports": 37,
        "Wildlife": 38,
        "Arctic": 49,
        "Kurds": 50,
        "Roads": 51,
        "Al Shabab": 67,
        "Piracy": 68,
        "Hezbollah": 71,
        "Minsk Monitor": 62,
        "Al Qaeda": 130,
        "Drugs War": 131,
        "MSF": 132,
        "Corruption": 136,
        "Energy": 143,
        "Climate": 145,
        "Far-right": 164,
        "Far-left": 165,
        "Houston": 168,
        "Visegrad 4": 127,
        "Weapons": 177,
    }

    # Region groups for UI display
    REGION_GROUPS = {
        "International/Conflict": [
            "Ukraine", "World", "Israel-Palestine", "Syria", "Caucasus",
            "Asia", "Middle East", "Africa", "Korea", "Europe",
            "America", "Hong Kong", "Egypt", "Russia", "Turkiye",
            "Hungary", "Belarus", "Balkans", "Poland", "Baltics",
            "Yemen", "Libya", "Kashmir", "Afghanistan", "Central Asia",
            "Colombia", "Brazil", "Iraq", "Iran", "Pakistan",
            "Venezuela", "Philippines", "Qatar", "Lebanon", "Mexico",
            "Kenya", "Moldova", "Somalia", "Ireland", "Guyana",
            "UK", "Taiwan", "Uganda", "Spain", "Sudan",
            "Myanmar", "Japan", "Vietnam", "Thailand", "DR Congo",
            "Bangladesh", "Caribbean", "South Africa", "Indonesia", "Tanzania",
            "Nigeria", "Ethiopia", "North Europe", "Germany", "France",
            "Italy", "Sahel", "Nicaragua", "Latin America", "Canada",
            "CAR", "Sri Lanka", "Maldives", "Zimbabwe", "Tunisia",
            "Algeria", "Honduras", "Saudi Arabia", "Cameroon",
            "Central & Eastern Europe",
        ],
        "US States": [
            "Alabama", "Alaska", "Arizona", "Arkansas", "California",
            "Colorado", "Connecticut", "Delaware", "District of Columbia",
            "Florida", "Georgia (US)", "Hawaii", "Idaho", "Illinois",
            "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
            "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
            "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
            "New Hampshire", "New Jersey", "New Mexico", "New York",
            "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
            "Pennsylvania", "Puerto Rico", "Rhode Island", "South Carolina",
            "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
            "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
        ],
        "Organizations/Topics": [
            "ISIS", "Women", "US Protests", "Trade Wars", "Cyberwar",
            "USA", "Pacific", "China", "India", "Disasters",
            "Human Rights", "Travel", "War", "Avia", "Life Style",
            "Epidemics", "Sports", "Wildlife", "Arctic", "Kurds",
            "Roads", "Al Shabab", "Piracy", "Hezbollah", "Minsk Monitor",
            "Al Qaeda", "Drugs War", "MSF", "Corruption", "Energy",
            "Climate", "Far-right", "Far-left", "Houston", "Visegrad 4",
            "Weapons",
        ],
    }

    # Colour name → ARGB integer mapping for CoT marker colours
    COLOUR_TO_ARGB = {
        "darkblack": -16777216,      # 0xFF000000
        "black": -16777216,          # 0xFF000000
        "red": -65536,               # 0xFFFF0000
        "darkred": -65536,         # 0xFF8B0000
        "blue": -16776961,           # 0xFF0000FF
        "darkblue": -16776961,       # 0xFF00008B
        "green": -16711936,          # 0xFF008000
        "darkgreen": -16711936,      # 0xFF006400
        "yellow": -256,              # 0xFFFFFF00
        "orange": -35072,            # 0xFFFFA500
        "brown": -7650029,           # 0xFFA52A2A
        "purple": -65281,          # 0xFF800080
        "pink": -65281,              # 0xFFFFC0CB
        "grey": -8947849,            # 0xFF808080
        "gray": -8947849,            # 0xFF808080
        "white": -1,                 # 0xFFFFFFFF
        "cyan": -16711681,           # 0xFF00FFFF
        "magenta": -65281,           # 0xFFFF00FF
    }

    @property
    def plugin_name(self) -> str:
        return self.PLUGIN_NAME

    @classmethod
    def get_plugin_name(cls) -> str:
        """Class method to get plugin name without instantiation"""
        return cls.PLUGIN_NAME

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "LiveUAMap OSINT",
            "description": "Fetch geolocated news and conflict events from LiveUAMap across multiple regions",
            "icon": "fas fa-globe",
            "category": "osint",
            "hide_cot_type": True,
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Obtain a LiveUAMap API key from your account.",
                        "Select one or more regions to monitor.",
                        "Events are fetched as spot map markers with colour-coded icons.",
                        "Leave 'Event Time' empty to fetch the latest events, or specify a datetime for historical queries.",
                    ],
                },
                {
                    "title": "API Information",
                    "content": [
                        "API endpoint: https://a.liveuamap.com/api",
                        "Each selected region makes one API call per poll cycle.",
                        "All venues from all regions are aggregated and returned in one batch.",
                        "CoT type is fixed to b-m-p-s-m (spot map marker) for all events.",
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    placeholder="Enter your LiveUAMap API key",
                    help_text="Your LiveUAMap API key for authentication",
                    sensitive=True,
                ),
                PluginConfigField(
                    name="regions",
                    label="Regions",
                    field_type="text",
                    required=True,
                    placeholder="Select regions using the selector below",
                    help_text="JSON array of region IDs to monitor (populated by region selector)",
                ),
                PluginConfigField(
                    name="event_time",
                    label="Event Time",
                    field_type="text",
                    required=False,
                    default_value="",
                    placeholder="Leave empty for current time",
                    help_text="Optional datetime for historical queries (format: YYYY-MM-DD HH:MM). Uses local timezone. Leave empty for latest events.",
                ),
                PluginConfigField(
                    name="count",
                    label="Events Per Region",
                    field_type="number",
                    required=False,
                    default_value=50,
                    min_value=1,
                    max_value=500,
                    help_text="Number of events to fetch per region per poll (1-500)",
                ),
                PluginConfigField(
                    name="timeout",
                    label="Request Timeout (seconds)",
                    field_type="number",
                    required=False,
                    default_value=30,
                    min_value=5,
                    max_value=120,
                    help_text="HTTP request timeout in seconds (5-120)",
                ),
            ],
            "custom_components": [
                PluginCustomComponent(
                    type="grouped_multi_select",
                    field_name="regions",
                    title="Select Regions",
                    icon="fa-globe",
                    help_text="Select one or more regions to monitor for events",
                    config={
                        "items": self.REGIONS,
                        "groups": self.REGION_GROUPS,
                    },
                ),
            ],
        }

    @staticmethod
    def _parse_colour_from_picpath(picpath) -> str:
        """Extract colour name from a picpath URL.

        Parses the filename from the URL, splits on '_', and takes
        the last segment before '.png' as the colour name.
        Falls back to 'darkblack' on any error.
        """
        fallback = "darkblack"
        if not picpath or not isinstance(picpath, str):
            return fallback
        try:
            parsed = urlparse(picpath)
            path = parsed.path if parsed.scheme else picpath
            filename = path.rsplit("/", 1)[-1]
            if "." not in filename or "_" not in filename:
                return fallback
            name_part = filename.rsplit(".", 1)[0]
            colour = name_part.rsplit("_", 1)[-1]
            return colour if colour else fallback
        except Exception:
            return fallback

    @classmethod
    def _build_custom_cot_attrib(cls, venue) -> Dict[str, Any]:
        """Build custom_cot_attrib dict with colour and icon for a venue."""
        picpath = venue.get("picpath", "")
        colour = cls._parse_colour_from_picpath(picpath)
        argb = cls.COLOUR_TO_ARGB.get(
            colour, cls.COLOUR_TO_ARGB["darkblack"]
        )
        logger.debug(f"Venue {venue.get('id', '?')}: picpath={picpath!r} -> colour={colour!r} -> argb={argb}")
        iconsetpath = f"COT_MAPPING_SPOTMAP/b-m-p-s-m/{argb}"
        return {
            "detail": {
                "color": {
                    "_attributes": {"argb": str(argb)}
                },
                "usericon": {
                    "_attributes": {"iconsetpath": iconsetpath}
                },
            }
        }

    @classmethod
    def _convert_venue_to_location(
        cls, venue: Dict, region_name: str, region_id: int
    ) -> Optional[Dict[str, Any]]:
        """Convert a LiveUAMap venue dict to a standardized location dict.

        Returns None if the venue is missing required fields (id, lat, lng).
        """
        venue_id = venue.get("id")
        lat = venue.get("lat")
        lng = venue.get("lng")

        if venue_id is None or lat is None or lng is None:
            return None

        name = venue.get("name", "Unknown Event")
        if len(name) > 100:
            name = name[:100]

        ts = venue.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

        location_str = venue.get("location", "")
        description = f"[LiveUAMap] {name}"
        if location_str:
            description += f" — {location_str}"

        return {
            "uid": f"liveuamap-{venue_id}",
            "name": name,
            "lat": lat,
            "lon": lng,
            "timestamp": dt,
            "description": description,
            "cot_type": "b-m-p-s-m",
            "custom_cot_attrib": cls._build_custom_cot_attrib(venue),
            "additional_data": {
                "source": "liveuamap",
                "event_id": venue_id,
                "region": region_name,
                "category_id": venue.get("category_id"),
                "source_url": venue.get("source_url", ""),
                "link": venue.get("link", ""),
                "picpath": venue.get("picpath", ""),
                "svimg": venue.get("svimg", ""),
                "img_share": venue.get("img_share", ""),
            },
        }

    @staticmethod
    def _create_ssl_context() -> ssl.SSLContext:
        """Create SSL context with proper configuration."""
        ssl_context = ssl.create_default_context(
            cafile=certifi.where()
        )
        ssl_context.options |= ssl.OP_NO_SSLv2
        ssl_context.options |= ssl.OP_NO_SSLv3
        return ssl_context

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """Fetch venues from LiveUAMap API across all configured regions.

        Loops through each selected region, makes one API call per region,
        aggregates all venues, and returns the full list of locations.
        """
        config = self.get_decrypted_config()
        api_key = config.get("api_key", "")
        count = int(config.get("count", 50))
        timeout_secs = int(config.get("timeout", 30))

        # Parse regions - may be a list (already parsed) or JSON string
        regions_raw = config.get("regions", "[]")
        if isinstance(regions_raw, list):
            region_ids = regions_raw
        else:
            try:
                region_ids = json.loads(regions_raw)
            except (json.JSONDecodeError, TypeError):
                logger.error("Invalid regions JSON in config")
                return [{"_error": "config_error",
                         "_error_message": "Invalid regions JSON"}]

        # Build reverse lookup: id -> name
        id_to_name = {v: k for k, v in self.REGIONS.items()}

        # Determine timestamp
        event_time = config.get("event_time", "")
        if event_time and event_time.strip():
            try:
                dt = datetime.strptime(
                    event_time.strip(), "%Y-%m-%d %H:%M"
                )
                dt = dt.replace(tzinfo=timezone.utc)
                unix_ts = int(dt.timestamp())
            except ValueError:
                logger.warning(
                    f"Invalid event_time format: {event_time}, "
                    "using current time"
                )
                unix_ts = int(time.time())
        else:
            unix_ts = int(time.time())

        locations = []
        timeout_config = aiohttp.ClientTimeout(
            total=timeout_secs
        )

        for region_id in region_ids:
            region_name = id_to_name.get(region_id, f"Region-{region_id}")

            url = (
                f"https://a.liveuamap.com/api"
                f"?a=mpts"
                f"&resid={region_id}"
                f"&time={unix_ts}"
                f"&count={count}"
                f"&key={api_key}"
            )

            try:
                async with session.get(
                    url, timeout=timeout_config
                ) as response:
                    if response.status == 429:
                        logger.warning(
                            f"Rate limited for region {region_name}"
                        )
                        locations.append({
                            "_error": "429",
                            "_error_message": "Rate limit exceeded",
                        })
                        continue

                    if response.status != 200:
                        logger.error(
                            f"HTTP {response.status} for "
                            f"region {region_name}"
                        )
                        locations.append({
                            "_error": str(response.status),
                            "_error_message": (
                                f"HTTP {response.status} error"
                            ),
                        })
                        continue

                    # content_type=None skips mimetype check;
                    # the API returns JSON with text/html header
                    data = await response.json(
                        content_type=None
                    )

                    if not data.get("success", False):
                        logger.error(
                            f"API returned success=false "
                            f"for region {region_name}"
                        )
                        locations.append({
                            "_error": "api_failure",
                            "_error_message": (
                                f"API failure for {region_name}"
                            ),
                        })
                        continue

                    venues = data.get("venues", [])
                    logger.info(
                        f"Fetched {len(venues)} venues "
                        f"from {region_name}"
                    )

                    for venue in venues:
                        loc = self._convert_venue_to_location(
                            venue, region_name, region_id
                        )
                        if loc is not None:
                            locations.append(loc)
                        else:
                            logger.debug(
                                "Skipped malformed venue: "
                                f"{venue.get('id', 'unknown')}"
                            )

            except asyncio.TimeoutError:
                logger.warning(
                    f"Timeout fetching region {region_name}"
                )
                continue

            except aiohttp.ClientError as e:
                logger.error(
                    f"Connection error for {region_name}: {e}"
                )
                locations.append({
                    "_error": "connection_failed",
                    "_error_message": str(e),
                })
                continue

            except Exception as e:
                logger.error(
                    f"Unexpected error for {region_name}: {e}"
                )
                locations.append({
                    "_error": "unknown",
                    "_error_message": str(e),
                })
                continue

        return locations

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False

        config = self.get_decrypted_config()
        valid_ids = set(self.REGIONS.values())

        # Validate regions - may be a list (already parsed) or JSON string
        regions_raw = config.get("regions", "")
        if regions_raw:
            if isinstance(regions_raw, list):
                regions = regions_raw
            else:
                try:
                    regions = json.loads(regions_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.error("Regions must be valid JSON array")
                    return False

            if not isinstance(regions, list) or len(regions) == 0:
                logger.error("At least one region must be selected")
                return False

            for rid in regions:
                if rid not in valid_ids:
                    logger.error(f"Invalid region ID: {rid}")
                    return False

        return True
