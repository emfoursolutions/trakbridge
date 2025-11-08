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

## PluginConfigField Reference

### Overview

`PluginConfigField` is the primary class for defining plugin configuration options. Each field represents a user-configurable setting that appears in the TrakBridge UI and is validated by the plugin framework.

### Constructor Parameters

```python
PluginConfigField(
    name: str,                              # Required - Internal field identifier
    label: str,                             # Required - User-facing label
    field_type: str = "text",              # Field type (see types below)
    required: bool = False,                 # Whether field is mandatory
    placeholder: str = "",                  # Placeholder text for input
    help_text: str = "",                   # Help text displayed to user
    default_value: Any = None,              # Default value for field
    options: Optional[List[Dict[str, str]]] = None,  # For select fields
    min_value: Optional[int] = None,        # Minimum value for number fields
    max_value: Optional[int] = None,        # Maximum value for number fields
    sensitive: bool = False                 # Marks field for encryption
)
```

### Available Field Types

#### 1. Text Field (`"text"`)

**Purpose**: Standard text input for usernames, identifiers, filters, etc.

**Validation**: None by default (plugins can implement custom validation)

**Example - Username Field**:
```python
PluginConfigField(
    name="username",
    label="Garmin Username",
    field_type="text",
    required=True,
    help_text="Your Garmin Connect account username"
)
```

**Example - Optional Text with Placeholder**:
```python
PluginConfigField(
    name="device_filter",
    label="Device Name Filter",
    field_type="text",
    required=False,
    placeholder="vehicle,tracker",
    help_text="Comma-separated list of device names to include (leave empty for all devices)"
)
```

**Example - Text with Default Value**:
```python
PluginConfigField(
    name="feed_id",
    label="SPOT Feed ID",
    field_type="text",
    required=True,
    placeholder="0abcdef1234567890abcdef123456789",
    help_text="Your SPOT device feed ID from your SPOT account shared page"
)
```

#### 2. Password Field (`"password"`)

**Purpose**: Masked input for passwords, API keys, and sensitive credentials

**Validation**: None by default

**Security**: MUST be combined with `sensitive=True` for automatic encryption

**Example - Password with Encryption**:
```python
PluginConfigField(
    name="password",
    label="Garmin Password",
    field_type="password",
    required=True,
    sensitive=True,  # CRITICAL: Enables automatic encryption
    help_text="Your Garmin Connect account password"
)
```

**Example - Optional Password**:
```python
PluginConfigField(
    name="feed_password",
    label="Feed Password",
    field_type="password",
    required=False,
    sensitive=True,
    help_text="Password if your SPOT feed is password protected (leave blank if not protected)"
)
```

#### 3. URL Field (`"url"`)

**Purpose**: Input for API endpoints, server URLs, feed URLs

**Validation**: Automatically validates that value starts with `http://` or `https://`

**Example - Required URL**:
```python
PluginConfigField(
    name="url",
    label="Garmin InReach KML Feed URL",
    field_type="url",
    required=True,
    placeholder="https://share.garmin.com/Feed/Share/...",
    help_text="Complete URL to your Garmin InReach KML feed from MapShare"
)
```

**Example - URL with Default**:
```python
PluginConfigField(
    name="api_url",
    label="Deepstate API URL",
    field_type="url",
    required=True,
    default_value="https://deepstatemap.live/api/history/last",
    placeholder="https://deepstatemap.live/api/history/last",
    help_text="URL to the Deepstate API endpoint (default is latest history)"
)
```

**Example - Server URL**:
```python
PluginConfigField(
    name="server_url",
    label="Traccar Server URL",
    field_type="url",
    required=True,
    placeholder="http://localhost:8082",
    help_text="Complete URL to your Traccar server (including port if needed)"
)
```

#### 4. Number Field (`"number"`)

**Purpose**: Numeric input with optional min/max constraints

**Validation**:
- Validates that value is a valid number
- Validates min_value constraint if specified
- Validates max_value constraint if specified

**Example - Number with Min/Max Constraints**:
```python
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
```

**Example - Timeout Field**:
```python
PluginConfigField(
    name="timeout",
    label="Request Timeout (seconds)",
    field_type="number",
    required=False,
    default_value=30,
    min_value=5,
    max_value=120,
    help_text="HTTP request timeout in seconds"
)
```

**Example - Count Field**:
```python
PluginConfigField(
    name="max_results",
    label="Maximum Results",
    field_type="number",
    required=False,
    default_value=50,
    min_value=1,
    max_value=200,
    help_text="Maximum number of location points to fetch per request"
)
```

#### 5. Select Field (`"select"`)

**Purpose**: Dropdown selection from predefined options

**Validation**: Validates that selected value exists in options list

**Required Parameter**: `options` - List of dictionaries with `"value"` and `"label"` keys

**Example - Mode Selection**:
```python
PluginConfigField(
    name="cot_type_mode",
    label="COT Type Mode",
    field_type="select",
    required=False,
    default_value="per_point",
    options=[
        {
            "value": "stream",
            "label": "Use stream COT type for all points"
        },
        {
            "value": "per_point",
            "label": "Determine COT type per point"
        }
    ],
    help_text="Choose whether to use the stream's COT type for all points or determine COT type individually for each point"
)
```

**Example - API Version Selection**:
```python
PluginConfigField(
    name="api_version",
    label="API Version",
    field_type="select",
    required=True,
    default_value="v2",
    options=[
        {"value": "v1", "label": "API v1 (Legacy)"},
        {"value": "v2", "label": "API v2 (Current)"},
        {"value": "v3", "label": "API v3 (Beta)"}
    ],
    help_text="Select the API version to use for requests"
)
```

#### 6. Email Field (`"email"`)

**Purpose**: Email address input

**Validation**: Validates that value contains `@` character

**Note**: Not currently used in built-in plugins, but available for custom plugins

**Example - Email Contact**:
```python
PluginConfigField(
    name="contact_email",
    label="Contact Email",
    field_type="email",
    required=False,
    placeholder="admin@example.com",
    help_text="Email address for emergency notifications"
)
```

#### 7. Checkbox Field (`"checkbox"`)

**Purpose**: Boolean true/false selection

**Validation**: None (coerced to boolean)

**Example - Feature Toggle**:
```python
PluginConfigField(
    name="hide_inactive_devices",
    label="Hide Inactive Devices",
    field_type="checkbox",
    required=False,
    default_value=True,
    help_text="Hide devices that have tracking turned off"
)
```

**Example - Optional Feature**:
```python
PluginConfigField(
    name="enable_debug_logging",
    label="Enable Debug Logging",
    field_type="checkbox",
    required=False,
    default_value=False,
    help_text="Log detailed debugging information for troubleshooting"
)
```

### Parameter Details

#### `name` (Required)

**Type**: `str`

**Purpose**: Internal identifier for the configuration field. Used as the key in config dictionaries.

**Best Practices**:
- Use lowercase with underscores (snake_case)
- Be descriptive and specific
- Avoid conflicts with reserved Python keywords
- Keep consistent across plugin versions

**Examples**:
```python
name="api_key"          # Good
name="server_url"       # Good
name="max_results"      # Good
name="key"              # Too vague
name="URL"              # Don't use uppercase
```

#### `label` (Required)

**Type**: `str`

**Purpose**: User-facing display name shown in the UI

**Best Practices**:
- Use title case
- Be clear and concise
- Include units in parentheses if applicable
- Avoid technical jargon when possible

**Examples**:
```python
label="API Key"                          # Good
label="Request Timeout (seconds)"        # Good - includes units
label="Maximum Results"                  # Good
label="srv_url"                          # Too technical
label="THE API KEY FOR THE SERVICE"      # Too verbose
```

#### `field_type`

**Type**: `str`

**Default**: `"text"`

**Valid Values**: `"text"`, `"password"`, `"url"`, `"number"`, `"select"`, `"email"`, `"checkbox"`

**Purpose**: Determines input type and validation behavior

#### `required`

**Type**: `bool`

**Default**: `False`

**Purpose**: Whether field must have a value before plugin can be saved/used

**Validation**: Checked during `validate_config()` - returns `False` if required field is missing or empty

**Examples**:
```python
required=True   # User must provide a value
required=False  # Field is optional
```

#### `placeholder`

**Type**: `str`

**Default**: `""`

**Purpose**: Placeholder text displayed in empty input fields

**Best Practices**:
- Show example format or value
- Don't duplicate the label
- Keep it concise

**Examples**:
```python
placeholder="https://api.example.com/v1"        # Good - shows format
placeholder="device1,device2,device3"           # Good - shows format
placeholder="Enter your API key here"           # Redundant with label
```

#### `help_text`

**Type**: `str`

**Default**: `""`

**Purpose**: Additional context and instructions for users

**Best Practices**:
- Explain where to find the value
- Clarify purpose or impact
- Include warnings or important notes
- Keep to 1-2 sentences

**Examples**:
```python
help_text="Your Garmin Connect account username"
help_text="Complete URL to your Traccar server (including port if needed)"
help_text="Delay between retry attempts on connection failure"
```

#### `default_value`

**Type**: `Any`

**Default**: `None`

**Purpose**: Pre-populated value when field is first displayed

**Best Practices**:
- Use sensible defaults for optional fields
- Match type to field_type (bool for checkbox, int for number, etc.)
- Don't set defaults for required sensitive fields

**Examples**:
```python
default_value=30                                          # Number field
default_value=True                                        # Checkbox field
default_value="https://api.example.com/v1"               # URL field
default_value="per_point"                                # Select field
```

#### `options`

**Type**: `Optional[List[Dict[str, str]]]`

**Default**: `None`

**Purpose**: List of selectable options for `select` field type

**Required For**: `select` field types only

**Format**: Each option must be a dictionary with `"value"` and `"label"` keys
- `"value"`: Internal value stored in config
- `"label"`: User-facing display text

**Example**:
```python
options=[
    {"value": "v1", "label": "API v1 (Legacy)"},
    {"value": "v2", "label": "API v2 (Current)"},
    {"value": "v3", "label": "API v3 (Beta)"}
]
```

#### `min_value`

**Type**: `Optional[int]`

**Default**: `None`

**Purpose**: Minimum allowed value for `number` field type

**Validation**: Checked during `validate_config()` - returns `False` if value is below minimum

**Example**:
```python
min_value=5     # Value must be >= 5
min_value=1     # Value must be >= 1
```

#### `max_value`

**Type**: `Optional[int]`

**Default**: `None`

**Purpose**: Maximum allowed value for `number` field type

**Validation**: Checked during `validate_config()` - returns `False` if value exceeds maximum

**Example**:
```python
max_value=120   # Value must be <= 120
max_value=3600  # Value must be <= 3600
```

#### `sensitive`

**Type**: `bool`

**Default**: `False`

**Purpose**: Marks field for automatic encryption in database

**Security Implications**:
- Fields marked `sensitive=True` are automatically encrypted before storage
- Decrypted automatically when plugin config is loaded
- CRITICAL for passwords, API keys, tokens, and secrets

**Best Practices**:
- ALWAYS set `sensitive=True` for `password` field types
- Set `sensitive=True` for API keys, tokens, secrets
- Don't set for non-sensitive data (wastes processing)

**Examples**:
```python
# Password field - MUST be sensitive
PluginConfigField(
    name="password",
    field_type="password",
    sensitive=True      # CRITICAL
)

# API key - Should be sensitive
PluginConfigField(
    name="api_key",
    field_type="password",
    sensitive=True
)

# Username - Not sensitive
PluginConfigField(
    name="username",
    field_type="text",
    sensitive=False     # Default, not needed
)
```

### Complete Real-World Examples

#### Example 1: Traccar Plugin Configuration

```python
"config_fields": [
    # URL field with placeholder
    PluginConfigField(
        name="server_url",
        label="Traccar Server URL",
        field_type="url",
        required=True,
        placeholder="http://localhost:8082",
        help_text="Complete URL to your Traccar server (including port if needed)"
    ),
    # Required text field
    PluginConfigField(
        name="username",
        label="Username",
        field_type="text",
        required=True,
        help_text="Traccar username with device access permissions"
    ),
    # Sensitive password field
    PluginConfigField(
        name="password",
        label="Password",
        field_type="password",
        required=True,
        sensitive=True,
        help_text="Traccar user password"
    ),
    # Number field with constraints
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
    # Optional text field with placeholder
    PluginConfigField(
        name="device_filter",
        label="Device Name Filter",
        field_type="text",
        required=False,
        placeholder="vehicle,tracker",
        help_text="Comma-separated list of device names to include (leave empty for all devices)"
    )
]
```

#### Example 2: Deepstate Plugin Configuration

```python
"config_fields": [
    # URL with default value
    PluginConfigField(
        name="api_url",
        label="Deepstate API URL",
        field_type="url",
        required=True,
        default_value="https://deepstatemap.live/api/history/last",
        placeholder="https://deepstatemap.live/api/history/last",
        help_text="URL to the Deepstate API endpoint (default is latest history)"
    ),
    # Select field with options
    PluginConfigField(
        name="cot_type_mode",
        label="COT Type Mode",
        field_type="select",
        required=False,
        default_value="per_point",
        options=[
            {
                "value": "stream",
                "label": "Use stream COT type for all points"
            },
            {
                "value": "per_point",
                "label": "Determine COT type per point"
            }
        ],
        help_text="Choose whether to use the stream's COT type for all points or determine COT type individually for each point"
    ),
    # Number with range
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
    # Number with different range
    PluginConfigField(
        name="max_events",
        label="Maximum Events",
        field_type="number",
        required=False,
        default_value=100,
        min_value=1,
        max_value=1000,
        help_text="Maximum number of events to fetch and process"
    )
]
```

#### Example 3: Garmin Plugin Configuration

```python
"config_fields": [
    # Required URL
    PluginConfigField(
        name="url",
        label="Garmin InReach KML Feed URL",
        field_type="url",
        required=True,
        placeholder="https://share.garmin.com/Feed/Share/...",
        help_text="Complete URL to your Garmin InReach KML feed from MapShare"
    ),
    # Required text
    PluginConfigField(
        name="username",
        label="Garmin Username",
        field_type="text",
        required=True,
        help_text="Your Garmin Connect account username"
    ),
    # Required sensitive password
    PluginConfigField(
        name="password",
        label="Garmin Password",
        field_type="password",
        required=True,
        sensitive=True,
        help_text="Your Garmin Connect account password"
    ),
    # Checkbox with default
    PluginConfigField(
        name="hide_inactive_devices",
        label="Hide Inactive Devices",
        field_type="checkbox",
        required=False,
        default_value=True,
        help_text="Hide devices that have tracking turned off"
    ),
    # Number with range
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
```

### Validation Behavior

The `BaseGPSPlugin.validate_config()` method automatically validates all fields:

#### Required Field Validation
```python
# Checks if required fields have values
if field.required and (field_value is None or field_value == ""):
    logger.error(f"Missing required configuration field: {field_name}")
    return False
```

#### Type-Specific Validation

**URL Fields**:
```python
# Must start with http:// or https://
if field.field_type in ["url"] and not str(field_value).startswith(("http://", "https://")):
    logger.error(f"Field '{field_name}' must be a valid URL")
    return False
```

**Number Fields**:
```python
# Must be valid number within min/max range
if field.field_type == "number":
    try:
        num_value = float(field_value)
        if field.min_value is not None and num_value < field.min_value:
            logger.error(f"Field '{field_name}' must be at least {field.min_value}")
            return False
        if field.max_value is not None and num_value > field.max_value:
            logger.error(f"Field '{field_name}' must be at most {field.max_value}")
            return False
    except (ValueError, TypeError):
        logger.error(f"Field '{field_name}' must be a valid number")
        return False
```

**Email Fields**:
```python
# Must contain @ symbol
if field.field_type == "email" and "@" not in str(field_value):
    logger.error(f"Field '{field_name}' must be a valid email address")
    return False
```

### Best Practices

#### Security
1. **ALWAYS** set `sensitive=True` for passwords, API keys, tokens, and secrets
2. Use `password` field type for any sensitive credential
3. Never log or display sensitive field values
4. Avoid storing unnecessary sensitive data

#### User Experience
1. Provide clear, concise labels
2. Include helpful `help_text` for complex fields
3. Use appropriate placeholders to show expected format
4. Set sensible defaults for optional fields
5. Use constraints (min/max) to guide users

#### Validation
1. Mark critical fields as `required=True`
2. Use appropriate field types for automatic validation
3. Add custom validation in plugin's `validate_config()` if needed
4. Provide clear error messages for validation failures

#### Performance
1. Don't mark non-sensitive fields as `sensitive` (wastes encryption cycles)
2. Use appropriate ranges for number fields to prevent abuse
3. Provide defaults to reduce configuration burden

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