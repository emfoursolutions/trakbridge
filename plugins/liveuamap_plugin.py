# ABOUTME: LiveUAMap OSINT plugin for fetching geolocated news/conflict events
# ABOUTME: Fetches venues from LiveUAMap API across multiple regions and converts them to CoT markers

# Standard library imports
import json
from typing import Any, Dict, List

# Third-party imports
import aiohttp

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

    # Region name → API resid mapping (140+ entries)
    REGIONS = {
        # International/Conflict
        "Afghanistan": 67,
        "Algeria": 68,
        "Bangladesh": 69,
        "Belarus": 70,
        "Brazil": 71,
        "Cameroon": 72,
        "CAR": 73,
        "Caucasus": 74,
        "Central Asia": 75,
        "Colombia": 76,
        "DR Congo": 77,
        "Egypt": 78,
        "Ethiopia": 79,
        "France": 80,
        "Germany": 81,
        "Guyana": 82,
        "Honduras": 83,
        "Hong Kong": 84,
        "Hungary": 85,
        "Indonesia": 86,
        "Iran": 66,
        "Iraq": 4,
        "Ireland": 87,
        "Israel-Palestine": 5,
        "Italy": 88,
        "Japan": 89,
        "Kashmir": 90,
        "Kenya": 91,
        "Koreas": 92,
        "Lebanon": 93,
        "Libya": 6,
        "Maldives": 94,
        "Mexico": 95,
        "Moldova": 96,
        "Myanmar": 97,
        "Nicaragua": 98,
        "Nigeria": 99,
        "North Europe": 100,
        "Pakistan": 101,
        "Philippines": 102,
        "Poland": 103,
        "Qatar": 104,
        "Russia": 105,
        "Sahel": 106,
        "Saudi Arabia": 107,
        "Somalia": 108,
        "South Africa": 109,
        "Spain": 110,
        "Sri Lanka": 111,
        "Sudan": 112,
        "Syria": 3,
        "Taiwan": 113,
        "Tanzania": 114,
        "Thailand": 115,
        "Tunisia": 116,
        "Turkiye": 117,
        "UK": 118,
        "Uganda": 119,
        "Ukraine": 0,
        "Venezuela": 120,
        "Vietnam": 121,
        "Yemen": 7,
        "Zimbabwe": 122,
        "Balkans": 123,
        "Baltics": 124,
        "Caribbean": 125,
        "Central & Eastern Europe": 126,
        "Latin America": 127,
        # US States
        "Alabama": 8,
        "Alaska": 9,
        "Arizona": 10,
        "Arkansas": 11,
        "California": 12,
        "Colorado": 13,
        "Connecticut": 14,
        "Delaware": 15,
        "District of Columbia": 16,
        "Florida": 17,
        "Georgia (US)": 18,
        "Hawaii": 19,
        "Idaho": 20,
        "Illinois": 21,
        "Indiana": 22,
        "Iowa": 23,
        "Kansas": 24,
        "Kentucky": 25,
        "Louisiana": 26,
        "Maine": 27,
        "Maryland": 28,
        "Massachusetts": 29,
        "Michigan": 30,
        "Minnesota": 31,
        "Mississippi": 32,
        "Missouri": 33,
        "Montana": 34,
        "Nebraska": 35,
        "Nevada": 36,
        "New Hampshire": 37,
        "New Jersey": 38,
        "New Mexico": 39,
        "New York": 40,
        "North Carolina": 41,
        "North Dakota": 42,
        "Ohio": 43,
        "Oklahoma": 44,
        "Oregon": 45,
        "Pennsylvania": 46,
        "Puerto Rico": 47,
        "Rhode Island": 48,
        "South Carolina": 49,
        "South Dakota": 50,
        "Tennessee": 51,
        "Texas": 52,
        "Utah": 53,
        "Vermont": 54,
        "Virginia": 55,
        "Washington": 56,
        "West Virginia": 57,
        "Wisconsin": 58,
        "Wyoming": 59,
        # Organizations/Topics
        "Al Qaeda": 60,
        "Al Shabab": 61,
        "Avia": 62,
        "Drugs War": 128,
        "Far-left": 129,
        "Far-right": 130,
        "Hezbollah": 131,
        "ISIS": 1,
        "Kurds": 132,
        "Minsk Monitor": 133,
        "US Protests": 134,
        "Canada": 135,
    }

    # Region groups for UI display
    REGION_GROUPS = {
        "International/Conflict": [
            "Afghanistan", "Algeria", "Bangladesh", "Belarus", "Brazil",
            "Cameroon", "CAR", "Caucasus", "Central Asia", "Colombia",
            "DR Congo", "Egypt", "Ethiopia", "France", "Germany",
            "Guyana", "Honduras", "Hong Kong", "Hungary", "Indonesia",
            "Iran", "Iraq", "Ireland", "Israel-Palestine", "Italy",
            "Japan", "Kashmir", "Kenya", "Koreas", "Lebanon",
            "Libya", "Maldives", "Mexico", "Moldova", "Myanmar",
            "Nicaragua", "Nigeria", "North Europe", "Pakistan", "Philippines",
            "Poland", "Qatar", "Russia", "Sahel", "Saudi Arabia",
            "Somalia", "South Africa", "Spain", "Sri Lanka", "Sudan",
            "Syria", "Taiwan", "Tanzania", "Thailand", "Tunisia",
            "Turkiye", "UK", "Uganda", "Ukraine", "Venezuela",
            "Vietnam", "Yemen", "Zimbabwe", "Balkans", "Baltics",
            "Caribbean", "Central & Eastern Europe", "Latin America",
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
            "Al Qaeda", "Al Shabab", "Avia", "Drugs War", "Far-left",
            "Far-right", "Hezbollah", "ISIS", "Kurds", "Minsk Monitor",
            "US Protests", "Canada",
        ],
    }

    # Colour name → ARGB integer mapping for CoT marker colours
    COLOUR_TO_ARGB = {
        "darkblack": -16777216,      # 0xFF000000
        "black": -16777216,          # 0xFF000000
        "red": -65536,               # 0xFFFF0000
        "darkred": -7667712,         # 0xFF8B0000
        "blue": -16776961,           # 0xFF0000FF
        "darkblue": -16777077,       # 0xFF00008B
        "green": -16744448,          # 0xFF008000
        "darkgreen": -16751616,      # 0xFF006400
        "yellow": -256,              # 0xFFFFFF00
        "orange": -23296,            # 0xFFFFA500
        "brown": -5952982,           # 0xFFA52A2A
        "purple": -8388480,          # 0xFF800080
        "pink": -16181,              # 0xFFFFC0CB
        "grey": -8355712,            # 0xFF808080
        "gray": -8355712,            # 0xFF808080
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
                    name="action",
                    label="API Action",
                    field_type="text",
                    required=False,
                    default_value="mpts",
                    placeholder="mpts",
                    help_text="API action parameter (default: mpts)",
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
                    type="region_selector",
                    field_name="regions",
                    title="Select Regions",
                    icon="fa-globe",
                    help_text="Select one or more regions to monitor for events",
                    config={
                        "regions": self.REGIONS,
                        "region_groups": self.REGION_GROUPS,
                    },
                ),
            ],
        }

    async def fetch_locations(
        self, session: aiohttp.ClientSession
    ) -> List[Dict[str, Any]]:
        """Fetch locations from LiveUAMap API. Stub implementation."""
        return []

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        if not super().validate_config():
            return False

        config = self.get_decrypted_config()
        valid_ids = set(self.REGIONS.values())

        # Validate regions JSON
        regions_str = config.get("regions", "")
        if regions_str:
            try:
                regions = json.loads(regions_str)
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
