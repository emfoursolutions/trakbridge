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
from plugins.base_plugin import BaseGPSPlugin
from typing import Dict, Any, List, Optional

class CustomPlugin(BaseGPSPlugin):
    
    @property
    def plugin_name(self) -> str:
        """Return unique plugin identifier"""
        return "custom_tracker"
    
    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """Return plugin metadata for UI generation"""
        return {
            "display_name": "Custom Tracker",
            "description": "Connect to custom GPS tracking system",
            "icon": "fas fa-map-marker-alt",
            "category": "tracker",  # osint, tracker, or ems
            "help_sections": [...],
            "config_fields": self._get_config_fields()
        }
    
    async def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch raw data from external source"""
        # Implementation here
        pass
    
    def transform_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform raw data to TrakBridge format"""
        # Implementation here
        pass
```

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

#### Plugin Class Implementation
```python
# plugins/example_tracker_plugin.py
import asyncio
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
            ]
        }
    
    def _get_config_fields(self) -> List[PluginConfigField]:
        """Define configuration fields for UI generation"""
        return [
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
    
    async def fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch location data from Example Tracker API"""
        try:
            api_key = self.config.get("api_key")
            api_url = self.config.get("api_url", "https://api.example-tracker.com/v1")
            device_ids = self.config.get("device_ids", "")
            
            # Decrypt sensitive fields
            if api_key:
                api_key = self.encryption_service.decrypt_field(api_key)
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "TrakBridge/1.0"
            }
            
            # Build API request URL
            url = f"{api_url}/locations"
            params = {}
            
            if device_ids:
                params["devices"] = device_ids
            
            # Make API request
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                    
                    logger.info(f"Fetched {len(data.get('locations', []))} locations from Example Tracker")
                    return data.get("locations", [])
                    
        except Exception as e:
            logger.error(f"Error fetching Example Tracker data: {e}")
            raise
    
    def transform_data(self, raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transform Example Tracker data to TrakBridge format"""
        transformed = []
        
        for location in raw_data:
            try:
                # Extract required fields
                device_id = location.get("device_id")
                latitude = location.get("lat")
                longitude = location.get("lon")
                timestamp_str = location.get("timestamp")
                
                # Validate required fields
                if not all([device_id, latitude, longitude, timestamp_str]):
                    logger.warning(f"Skipping incomplete location data: {location}")
                    continue
                
                # Parse timestamp
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                
                # Create standardized location data
                transformed_location = {
                    "id": f"EXTRACK_{device_id}",
                    "name": location.get("device_name", f"Device {device_id}"),
                    "lat": float(latitude),
                    "lon": float(longitude), 
                    "timestamp": timestamp.isoformat(),
                    "source": "Example Tracker",
                    "device_id": device_id,
                    "metadata": {
                        "battery_level": location.get("battery"),
                        "signal_strength": location.get("signal"),
                        "speed_kph": location.get("speed"),
                        "altitude_m": location.get("altitude"),
                        "heading": location.get("heading")
                    }
                }
                
                transformed.append(transformed_location)
                
            except Exception as e:
                logger.error(f"Error transforming location data {location}: {e}")
                continue
        
        logger.info(f"Transformed {len(transformed)} valid locations")
        return transformed
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test API connection and credentials"""
        try:
            # Attempt to fetch a small amount of data
            data = await self.fetch_data()
            
            return {
                "success": True,
                "message": f"Successfully connected to Example Tracker API. Retrieved {len(data)} locations.",
                "device_count": len(set(loc.get("device_id") for loc in data))
            }
            
        except aiohttp.ClientResponseError as e:
            return {
                "success": False,
                "message": f"API request failed: HTTP {e.status} - {e.message}",
                "error_type": "api_error"
            }
        except Exception as e:
            return {
                "success": False, 
                "message": f"Connection test failed: {str(e)}",
                "error_type": type(e).__name__
            }
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

**Plugin Development Guide Version**: 1.2.0  
**Last Updated**: 2025-08-08  
**Compatible with**: TrakBridge v1.0.0+