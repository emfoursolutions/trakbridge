# TrakBridge Plugin Development Guide

## Overview

TrakBridge provides an extensible plugin architecture for integrating various GPS tracking devices, OSINT platforms, and emergency management systems. This guide covers developing custom plugins, understanding the plugin categorization system, and implementing secure, maintainable integrations.

## Plugin Architecture

### Base Plugin Class

All TrakBridge plugins inherit from the `BaseGPSPlugin` abstract base class, which provides:

- **Standardized Interface**: Consistent methods for data fetching and transformation
- **Configuration Management**: Automatic UI generation and field validation
- **Security Features**: Built-in encryption support for sensitive fields
- **Error Handling**: Comprehensive error management and logging
- **Integration Support**: COT (Cursor on Target) format conversion

### Core Plugin Components

#### Required Methods

```python
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField
from typing import Dict, Any, List
import aiohttp

class CustomPlugin(BaseGPSPlugin):

    @property
    def plugin_name(self) -> str:
        """Return unique plugin identifier"""
        return "custom_tracker"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for UI generation and configuration"""
        return {
            "display_name": "Custom Tracker",
            "description": "Connect to custom GPS tracking system",
            "icon": "fas fa-map-marker-alt",
            "category": "tracker",  # osint, tracker, or ems
            "help_sections": [...],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True
                ),
                # ... more config fields
            ]
        }

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch and transform location data from external source.

        Args:
            session: aiohttp ClientSession for making HTTP requests

        Returns:
            List of location dictionaries with required fields (uid, name, lat, lon)
        """
        # Implementation: Fetch data from API and transform to TrakBridge format
        # Return list of location dictionaries
        pass
```

**Note**: The plugin implements a **single method** (`fetch_locations`) that handles both data fetching and transformation. 

## Plugin Categories

### Category System Overview

TrakBridge organizes plugins into categories to simplify user experience and system organization. The default ones are:

#### OSINT (Open Source Intelligence)
**Purpose**: Intelligence platforms and open-source data feeds
**Category Key**: `"osint"`
**Display Category**: `"OSINT"`

**Characteristics**:
- Public or semi-public data sources
- Intelligence and situational awareness focus
- Often require minimal authentication
- Data typically includes analyzed intelligence products

**Example Sources**:
- Battlefield intelligence platforms
- Crisis monitoring systems  
- Public safety information feeds
- Social media intelligence platforms

#### Tracker (GPS and Satellite Devices)
**Purpose**: GPS tracking devices and location services
**Category Key**: `"tracker"`, `"satellite"`, `"platform"`
**Display Category**: `"Tracker"`

**Characteristics**:
- Real-time or near real-time location data
- Require device-specific authentication
- Focus on precision and currency of location information
- Support for multiple tracking targets per plugin

**Example Sources**:
- Satellite communicators (Garmin InReach, SPOT)
- GPS tracking platforms (Traccar)
- Fleet management systems
- Personal location devices

#### EMS (Emergency Management Systems)
**Purpose**: Emergency management and response systems
**Category Key**: `"ems"`
**Display Category**: `"EMS"`

**Characteristics**:
- Emergency response and coordination systems
- Critical system integration requirements
- High reliability and availability needs
- Integration with dispatch and command systems

**Example Sources**:
- Emergency dispatch systems
- First responder tracking systems
- Crisis communication platforms
- Emergency services coordination systems

### Implementing Category Support

#### Setting Plugin Category
```python
@property
def plugin_metadata(self) -> Dict[str, Any]:
    return {
        "display_name": "Emergency Dispatch Tracker",
        "description": "Connect to emergency dispatch system",
        "icon": "fas fa-ambulance",
        "category": "ems",  # Will be mapped to "EMS" display category
        # ... other metadata
    }
```

#### Category Mapping Logic
The plugin categorization service automatically maps plugin categories to display categories:

```python
# Category mapping in services/plugin_category_service.py
_category_mapping = {
    'osint': 'OSINT',
    'satellite': 'Tracker', 
    'platform': 'Tracker',
    'tracker': 'Tracker',
    'ems': 'EMS'
}
```

## Plugin Development Process

### Development Environment Setup

#### 1. Development Installation
```bash
# Clone repository
git clone https://github.com/emfoursolutions/trakbridge.git
cd trakbridge

# Create development environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"
```

#### 2. Plugin Directory Structure
```
plugins/
├── __init__.py
├── base_plugin.py          # Base plugin class
├── plugin_manager.py       # Plugin management
├── your_plugin.py          # Your custom plugin
└── tests/
    └── test_your_plugin.py  # Plugin tests
```

### Creating a Custom Plugin

#### Understanding the Plugin Data Flow

**IMPORTANT**: TrakBridge plugins implement a **single-method pattern** for data retrieval:

- ✅ **Implement**: `fetch_locations(session)` - Returns fully-transformed location dictionaries
- ❌ **DO NOT implement**: `fetch_data()` or `transform_data()` - These methods do not exist

The `fetch_locations()` method receives an `aiohttp.ClientSession` and must return a list of location dictionaries in TrakBridge standard format. All data fetching and transformation happens within this single method.

#### Plugin Class Implementation

```python
# plugins/example_tracker_plugin.py
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from plugins.base_plugin import BaseGPSPlugin, PluginConfigField

logger = logging.getLogger(__name__)

class ExampleTrackerPlugin(BaseGPSPlugin):
    """Example tracker plugin implementation"""

    @property
    def plugin_name(self) -> str:
        return "example_tracker"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Example Tracker",
            "description": "Connect to example GPS tracking service",
            "icon": "fas fa-map-marker-alt",
            "category": "tracker",
            "help_sections": [
                {
                    "title": "Setup Instructions",
                    "content": [
                        "Obtain API credentials from Example Tracker service",
                        "Configure API endpoint URL if using custom server",
                        "Set appropriate refresh interval for your use case",
                        "Test connection before activating stream"
                    ]
                },
                {
                    "title": "Configuration Notes",
                    "content": [
                        "API key must have location data access permissions",
                        "Refresh interval should be 300+ seconds to avoid rate limiting",
                        "Device IDs can be comma-separated for multiple devices"
                    ]
                }
            ],
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Your Example Tracker API key with location access"
                ),
                PluginConfigField(
                    name="api_url",
                    label="API Endpoint URL",
                    field_type="url",
                    required=False,
                    default_value="https://api.example-tracker.com/v1",
                    help_text="Custom API endpoint (leave blank for default)"
                ),
                PluginConfigField(
                    name="device_ids",
                    label="Device IDs",
                    field_type="text",
                    required=False,
                    placeholder="device1,device2,device3",
                    help_text="Comma-separated device IDs (blank for all devices)"
                ),
                PluginConfigField(
                    name="refresh_interval",
                    label="Refresh Interval (seconds)",
                    field_type="number",
                    required=False,
                    default_value=300,
                    min_value=60,
                    max_value=3600,
                    help_text="How often to poll for new data (60-3600 seconds)"
                )
            ]
        }

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch and transform location data from Example Tracker API.

        This method handles both data fetching and transformation in a single step,
        returning location dictionaries in TrakBridge standard format.

        Args:
            session: aiohttp ClientSession for making HTTP requests

        Returns:
            List of location dictionaries with required fields (name, lat, lon, uid)
        """
        try:
            # Get decrypted configuration (handles sensitive field decryption automatically)
            config = self.get_decrypted_config()

            api_key = config.get("api_key")
            api_url = config.get("api_url", "https://api.example-tracker.com/v1")
            device_ids = config.get("device_ids", "")

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "TrakBridge/1.1"
            }

            # Build API request
            url = f"{api_url}/locations"
            params = {}
            if device_ids:
                params["devices"] = device_ids

            # Fetch data from API
            async with session.get(url, headers=headers, params=params) as response:
                response.raise_for_status()
                api_data = await response.json()

            # Transform API data to TrakBridge format
            locations = []
            for item in api_data.get("locations", []):
                try:
                    # Extract and validate required fields
                    device_id = item.get("device_id")
                    latitude = item.get("lat")
                    longitude = item.get("lon")
                    timestamp_str = item.get("timestamp")

                    if not all([device_id, latitude, longitude]):
                        logger.warning(f"Skipping incomplete location: {item}")
                        continue

                    # Parse timestamp if provided
                    timestamp = None
                    if timestamp_str:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

                    # Create TrakBridge location dictionary
                    location = {
                        # Required fields
                        "uid": f"EXTRACK_{device_id}",  # Unique identifier
                        "name": item.get("device_name", f"Device {device_id}"),
                        "lat": float(latitude),
                        "lon": float(longitude),

                        # Optional timestamp (can be string or datetime object)
                        "timestamp": timestamp,

                        # Optional: metadata that doesn't go into CoT XML directly
                        "additional_data": {
                            "source": "Example Tracker",
                            "device_id": device_id,
                            "battery_level": item.get("battery"),
                            "signal_strength": item.get("signal"),
                            "altitude_m": item.get("altitude")
                        }
                    }

                    # Add speed and course as TOP-LEVEL fields for CoT integration
                    if item.get("speed") is not None:
                        # Convert to m/s if needed (example: API returns km/h)
                        location["speed"] = float(item["speed"]) / 3.6
                    if item.get("heading") is not None:
                        location["course"] = float(item["heading"])

                    locations.append(location)

                except Exception as e:
                    logger.error(f"Error transforming location {item}: {e}")
                    continue

            logger.info(f"Fetched and transformed {len(locations)} locations from Example Tracker")
            return locations

        except Exception as e:
            logger.error(f"Error fetching Example Tracker data: {e}")
            raise

    async def test_connection(self) -> Dict[str, Any]:
        """Test API connection and credentials"""
        try:
            # Create temporary session for connection test
            async with aiohttp.ClientSession() as session:
                locations = await self.fetch_locations(session)

            return {
                "success": True,
                "message": f"Successfully connected to Example Tracker API. Retrieved {len(locations)} locations.",
                "device_count": len(locations)
            }

        except aiohttp.ClientResponseError as e:
            return {
                "success": False,
                "message": f"API request failed: HTTP {e.status}",
                "error_type": "api_error"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection test failed: {str(e)}",
                "error_type": type(e).__name__
            }
```

## TrakBridge Location Data Format

### Standard Location Dictionary

The `fetch_locations()` method must return a list of location dictionaries conforming to the TrakBridge standard format.

**Field Naming Notes**:

- Use `"uid"` for unique identifier (backward compatible: `"id"` accepted as fallback)
- Use `"name"` for device name (backward compatible: `"callsign"` accepted as fallback)
- Use `"additional_data"` for metadata (NOT `"metadata"`)
- `"timestamp"` can be either ISO format string OR datetime object

```python
{
    # Required fields
    "name": str,           # Device/tracker name for display
    "lat": float,          # Latitude in decimal degrees
    "lon": float,          # Longitude in decimal degrees
    "uid": str,            # Unique identifier for the device

    # Optional top-level fields for CoT integration
    "speed": float,        # Speed in meters per second (m/s)
    "course": float,       # Course/heading in degrees (0-360)
    "timestamp": str,      # ISO format timestamp

    # Optional nested data structure
    "additional_data": {
        "battery_state": int,              # Battery percentage (0-100)
        "team_member_enabled": bool,       # Enable ATAK team member CoT format
        "team_role": str,                  # Team role (if team member enabled)
        "team_color": str,                 # Team color (if team member enabled)
        # ... plugin-specific metadata
    },

    # Optional custom CoT XML attributes (v1.1.0+)
    "custom_cot_attrib": {
        # See Custom CoT Attributes section below
    }
}
```

### Top-Level vs Additional Data

**Critical distinction for CoT integration**:

- **Top-level fields** (`speed`, `course`): Extracted by CoT service for inclusion in `<track>` element (team members) or `<remarks>` (standard CoT)
- **additional_data fields**: Metadata not directly included in CoT XML structure

#### Example: Speed and Course

```python
# ✓ CORRECT - Top-level for CoT integration
location = {
    "name": "Tracker 1",
    "lat": 38.8977,
    "lon": -77.0365,
    "uid": "TRACK-001",
    "speed": 9.055,     # m/s - Will be included in CoT <track> or <remarks>
    "course": 315.0,    # degrees - Will be included in CoT <track> or <remarks>
    "additional_data": {
        "battery_state": 100,
        "altitude": 500.0  # Metadata only
    }
}

# ✗ INCORRECT - Speed/course in additional_data won't be processed
location = {
    "name": "Tracker 1",
    "lat": 38.8977,
    "lon": -77.0365,
    "uid": "TRACK-001",
    "additional_data": {
        "speed": 9.055,      # Won't be extracted for CoT!
        "course": 315.0      # Won't be extracted for CoT!
    }
}
```

### Custom CoT XML Attributes (v1.1.0+)

Plugins can add custom XML elements and attributes to generated CoT messages using the `custom_cot_attrib` field.

#### Basic Structure

```python
location = {
    "name": "Tracker 1",
    "lat": 38.8977,
    "lon": -77.0365,
    "uid": "TRACK-001",
    "custom_cot_attrib": {
        "event": {           # Attributes for <event> element
            "_attributes": {
                "access": "Unclassified",
                "qos": "1-r-c"
            }
        },
        "detail": {          # Elements under <detail>
            "element_name": {
                # Element configuration
            }
        }
    }
}
```

#### Special Keys

- **`_text`**: Element text content
- **`_attributes`**: XML attributes for the element

#### Examples

##### Military Symbol (2525C)

```python
"custom_cot_attrib": {
    "detail": {
        "__milsym": {
            "_text": "SFGPUCI-------"  # 2525C symbol code
        }
    }
}
```

Result: `<detail><__milsym>SFGPUCI-------</__milsym></detail>`

##### Custom Icon

```python
"custom_cot_attrib": {
    "detail": {
        "usericon": {
            "iconsetpath": "34ae1613-9645-4222-a9d2-e5f243dea2865/Military/a-u-G.png"
        }
    }
}
```

Result: `<detail><usericon><iconsetpath>34ae1613.../a-u-G.png</iconsetpath></usericon></detail>`

##### Link Element (Parent-Child Relationship)

```python
"custom_cot_attrib": {
    "detail": {
        "link": {
            "_attributes": {
                "uid": "SERVER-001",
                "production_time": "2025-11-08T10:00:00Z",
                "type": "a-f-G-E-S",
                "parent_callsign": "HQ",
                "relation": "p-p"
            }
        }
    }
}
```

Result: `<detail><link uid="SERVER-001" production_time="..." type="..." parent_callsign="HQ" relation="p-p" /></detail>`

##### Event-Level Attributes

```python
"custom_cot_attrib": {
    "event": {
        "_attributes": {
            "access": "Unclassified",
            "qos": "1-r-c"
        }
    }
}
```

Result: `<event ... access="Unclassified" qos="1-r-c">...</event>`

##### Simple String Values

```python
"custom_cot_attrib": {
    "detail": {
        "custom_field": "Simple text value"
    }
}
```

Result: `<detail><custom_field>Simple text value</custom_field></detail>`

##### Multiple Custom Elements

```python
"custom_cot_attrib": {
    "detail": {
        "__milsym": {"_text": "SFGPUCI-------"},
        "usericon": {
            "iconsetpath": "path/to/icon.png"
        },
        "custom_data": {"_text": "Custom value"}
    }
}
```

#### Protected Elements

The following elements cannot be overridden for security and CoT integrity:

**Event-level protected attributes**:

- `version`, `uid`, `type`, `time`, `start`, `stale`, `how`

**Detail-level protected elements**:

- `contact`, `uid`, `precisionlocation`, `__group`, `status`, `track`

Attempts to override protected elements will be logged as warnings and ignored.

#### XML Name Validation

Element and attribute names are validated to prevent XML injection:

- Must start with letter or underscore
- Can contain letters, digits, hyphens, periods, underscores
- Pattern: `^[a-zA-Z_][\w\-\.]*$`

Invalid names are rejected with logged warnings.

#### Use Cases

1. **Military Symbology**: Add MIL-STD-2525C/D symbols via `__milsym`
2. **Custom Icons**: Specify custom icon paths for ATAK/WinTAK
3. **Team Links**: Define parent-child relationships between units
4. **Classification Markings**: Add security classification attributes
5. **Extended Metadata**: Include plugin-specific data in CoT messages
6. **QoS Settings**: Configure quality of service parameters

### Battery State Handling

**SPOT Plugin Example** - Dynamic battery state mapping:

```python
# SPOT provides battery as "GOOD" or "LOW"
@staticmethod
def _map_battery_state(battery_str: str) -> int:
    """Map SPOT battery state to numeric percentage"""
    if not battery_str:
        return 100  # Default

    battery_upper = battery_str.upper()
    if battery_upper == "GOOD":
        return 100
    elif battery_upper == "LOW":
        return 20
    else:
        return 100  # Unknown states default to 100

# In transform_data:
location = {
    "name": "SPOT Tracker",
    "lat": 38.8977,
    "lon": -77.0365,
    "uid": "SPOT-001",
    "additional_data": {
        "battery_state": self._map_battery_state(raw_data.get("batteryState"))
    }
}
```

The CoT service will extract `battery_state` from `additional_data` and include it in the `<status>` element.

### Velocity and Course Parsing

**Garmin Plugin Example** - Parsing velocity from KML ExtendedData:

```python
@staticmethod
def _parse_velocity(velocity_str: str) -> Optional[float]:
    """
    Parse velocity from Garmin KML format to m/s.
    Supports: km/h, kph, mph, m/s
    Example: "32.6 km/h" -> 9.055 m/s
    """
    import re
    if not velocity_str:
        return None

    try:
        # Extract numeric value
        match = re.search(r"([\d.]+)", velocity_str)
        if not match:
            return None
        value = float(match.group(1))

        # Detect unit and convert to m/s
        velocity_lower = velocity_str.lower()
        if "km/h" in velocity_lower or "kph" in velocity_lower:
            return value / 3.6  # km/h to m/s
        elif "mph" in velocity_lower:
            return value * 0.44704  # mph to m/s
        elif "m/s" in velocity_lower:
            return value
        else:
            return value / 3.6  # Default to km/h
    except (ValueError, AttributeError):
        return None

@staticmethod
def _parse_course(course_str: str) -> Optional[float]:
    """
    Parse course/heading from Garmin KML format.
    Example: "315.00 ° True" -> 315.0
    Normalizes to 0-360 range.
    """
    import re
    if not course_str:
        return None

    try:
        match = re.search(r"([\d.]+)", course_str)
        if not match:
            return None
        course = float(match.group(1))
        return course % 360.0  # Normalize to 0-360
    except (ValueError, AttributeError):
        return None

# In transform_data:
extended_data = placemark.get("extended_data", {})
speed = self._parse_velocity(extended_data.get("Velocity"))
course = self._parse_course(extended_data.get("Course"))

location = {
    "name": "Garmin Device",
    "lat": 46.886493,
    "lon": 29.207861,
    "uid": "GARMIN-001"
}

# Add as top-level fields for CoT integration
if speed is not None:
    location["speed"] = speed
if course is not None:
    location["course"] = course
```

**Traccar Plugin Example** - Extracting speed and course:

```python
# Traccar provides speed in knots and course in degrees
def transform_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    transformed = []
    for position in raw_data:
        location = {
            "name": device_name,
            "lat": position["latitude"],
            "lon": position["longitude"],
            "uid": f"TRACCAR-{position['deviceId']}"
        }

        # Add speed and course as top-level fields
        if position.get("speed") is not None:
            location["speed"] = float(position["speed"])  # Already in correct units
        if position.get("course") is not None:
            location["course"] = float(position["course"])

        transformed.append(location)
    return transformed
```

## Deployment and Distribution

## Internal Plugin Registration

```python
# Add to config/settings/plugins.yaml 
# Allows plugin to load
- external_plugins.my_plugin
```


### External Plugin Distribution
```bash
# Copy plugin to ./plugins
cp my_plugin.py ./plugins

# Configure external plugin loading
echo "  - external_plugins.my_plugin" >> ./config/plugins.yaml

# Restart Container
docker compose --profiles postgres --porfiles nginx down
docker compose --profiles postgres --porfiles nginx up -d
```
## Best Practices

### Code Quality
- **Type Hints**: Use comprehensive type annotations
- **Documentation**: Include detailed docstrings and comments
- **Error Handling**: Implement comprehensive error handling and logging
- **Testing**: Maintain high test coverage (>90%)
- **Security**: Follow secure coding practices throughout

### Performance Optimization
- **Async Operations**: Use async/await for I/O operations
- **Connection Pooling**: Reuse HTTP connections when possible
- **Data Streaming**: Process data in chunks for large datasets
- **Memory Management**: Minimize memory footprint and prevent leaks
- **Rate Limiting**: Respect API rate limits and implement backoff

### Security Best Practices
- **Input Validation**: Validate all external input
- **Output Encoding**: Properly encode output data
- **Credential Management**: Never log or expose credentials
- **SSL/TLS**: Always use encrypted connections
- **Error Information**: Avoid exposing sensitive data in error messages

### Maintainability
- **Modular Design**: Keep plugins focused and modular
- **Configuration Management**: Use clear configuration patterns
- **Logging**: Implement comprehensive logging for troubleshooting
- **Version Compatibility**: Maintain backward compatibility when possible
- **Documentation**: Keep documentation current with code changes

## Support and Resources

### Development Resources
- **Base Plugin Source**: `plugins/base_plugin.py` - Reference implementation
- **Example Plugins**: Study existing plugins for patterns and best practices
- **Plugin Manager**: `plugins/plugin_manager.py` - Plugin loading and management
- **Testing Utilities**: `plugins/tests/` - Testing helpers and fixtures

### Community Support
- **GitHub Issues**: Report bugs and request features
- **Documentation**: Comprehensive guides and API references
- **Code Reviews**: Community code review and feedback
- **Best Practices**: Shared knowledge and implementation patterns

---

**Plugin Development Guide Version**: 1.3.0
**Last Updated**: 2025-11-08
**Compatible with**: TrakBridge v1.1.0+