# Docker Plugin Management

## Overview

TrakBridge supports loading external plugins from volume-mounted directories in Docker containers. This allows you to add custom GPS tracking plugins without rebuilding the container image.

## External Plugin Directory

Mount your custom plugins to: `/app/external_plugins`

This directory is specifically designed for external plugins and won't conflict with the built-in plugins directory.

## Docker Compose Example

```yaml
services:
  trakbridge:
    image: trakbridge:latest
    volumes:
      # Mount external plugins directory
      - ./plugins:/app/external_plugins:ro
      # Mount configuration directory
      - ./config:/app/external_config:ro
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
```

## Directory Structure

```
plugins/                    # Your host directory
├── my_custom_tracker.py       # Custom plugin file
├── enterprise_gps.py          # Another custom plugin
└── requirements.txt           # Plugin dependencies (optional)

config/                        # Configuration directory
└── settings/
    └── plugins.yaml          # Plugin allowlist configuration
```

## Plugin Configuration

Add your external plugins to `./config/plugins.yaml`:

```yaml
allowed_plugin_modules:
  # Allow your external plugins
  - external_plugins.my_custom_tracker
  - external_plugins.enterprise_gps
```

## Example External Plugin

Create `plugins/my_custom_tracker.py`:

```python
"""
Custom GPS Tracker Plugin for TrakBridge
"""

from typing import List, Dict, Any
import logging
import aiohttp
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField

logger = logging.getLogger(__name__)


class MyCustomTrackerPlugin(BaseGPSPlugin):
    """Custom GPS tracker integration"""

    @property
    def plugin_name(self) -> str:
        return "my_custom_tracker"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "My Custom Tracker",
            "description": "Integration with custom GPS tracking service",
            "icon": "fas fa-map-marker-alt",
            "category": "tracker",
            "config_fields": [
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,
                    help_text="Your custom tracker API key"
                ),
                PluginConfigField(
                    name="server_url",
                    label="Server URL",
                    field_type="url",
                    required=True,
                    placeholder="https://api.mycustomtracker.com",
                    help_text="Base URL for the tracking API"
                )
            ]
        }

    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch and transform locations from custom tracker API.

        Returns location dictionaries in TrakBridge standard format with
        required fields: uid, name, lat, lon
        """
        # Get decrypted configuration
        config = self.get_decrypted_config()

        try:
            headers = {"Authorization": f"Bearer {config['api_key']}"}
            url = f"{config['server_url']}/locations"

            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                api_data = await response.json()

            # Transform API data to TrakBridge format
            locations = []
            for item in api_data.get('devices', []):
                device_id = item.get('device_id')
                if not device_id:
                    continue

                location = {
                    # Required fields
                    'uid': f"CUSTOM-{device_id}",
                    'name': item.get('name', f'Device {device_id}'),
                    'lat': float(item.get('latitude', 0)),
                    'lon': float(item.get('longitude', 0)),

                    # Optional fields
                    'timestamp': item.get('timestamp'),

                    # Additional metadata
                    'additional_data': {
                        'status': item.get('status', ''),
                        'device_id': device_id
                    }
                }

                # Add speed/course as top-level fields if available
                if item.get('speed') is not None:
                    location['speed'] = float(item['speed'])
                if item.get('heading') is not None:
                    location['course'] = float(item['heading'])

                locations.append(location)

            logger.info(f"Fetched {len(locations)} locations from custom tracker")
            return locations

        except Exception as e:
            logger.error(f"Error fetching locations: {e}")
            return []
```

## Security Features

### Automatic Validation
- External plugins must be explicitly allowed in configuration
- Module names are validated for security
- Only files in mounted directory are accessible

### Safe Loading
- External plugins are loaded in `external_plugins.*` namespace
- Built-in plugins use `plugins.*` namespace
- No conflicts between external and built-in plugins
- Proper error handling and logging

### Docker Security
- Mount as read-only (`:ro`) for production
- Run container as non-root user
- Use proper file permissions

## Docker Commands

### Development
```bash
# Mount local plugin directory for development
docker run -v $(pwd)/my-plugins:/app/external_plugins:ro \
           -v $(pwd)/config:/app/config:ro \
           -p 5000:5000 \
           trakbridge:latest
```

### Production with Docker Compose
```bash
# Start with external plugins
docker-compose up -d

# Check plugin loading logs
docker-compose logs trakbridge | grep -i plugin

# Reload plugins without restart
docker-compose exec trakbridge python scripts/manage_plugins.py reload
```

## Available External Plugin Paths

The system automatically checks these paths for external plugins:

1. `/app/external_plugins` (primary - for Docker volumes)
2. `/opt/trakbridge/plugins` (system-wide)
3. `~/.trakbridge/plugins` (user-specific)
4. `./external_plugins` (local directory)

## Plugin Dependencies

If your external plugins require additional Python packages:

### Option 1: Custom Docker Image
```dockerfile
FROM trakbridge:latest
COPY requirements.txt /tmp/plugin-requirements.txt
RUN pip install -r /tmp/plugin-requirements.txt
```

### Option 2: Init Container
```yaml
services:
  plugin-installer:
    image: python:3.10
    volumes:
      - plugin-deps:/usr/local/lib/python3.10/site-packages
    command: pip install -t /usr/local/lib/python3.10/site-packages -r /plugins/requirements.txt
    
  trakbridge:
    depends_on:
      - plugin-installer
    volumes:
      - plugin-deps:/usr/local/lib/python3.10/site-packages:ro
      - ./my-plugins:/app/external_plugins:ro
```

## Troubleshooting

### Plugin Not Loading
```bash
# Check if plugin file exists
docker-compose exec trakbridge ls -la /app/external_plugins/

# Check plugin configuration
docker-compose exec trakbridge python scripts/manage_plugins.py list

# Check logs for errors
docker-compose logs trakbridge | grep -i "external_plugins"
```

### Permission Issues
```bash
# Fix file permissions
chmod -R 644 plugins/*.py
chown -R 1000:1000 my-plugins/  # If running as non-root user
```

### Configuration Issues
```bash
# Validate YAML syntax
docker-compose exec trakbridge python -c "import yaml; yaml.safe_load(open('/app/config/settings/plugins.yaml'))"

# Reload configuration
docker-compose exec trakbridge python scripts/manage_plugins.py reload
```

## Best Practices

1. **Version Control**: Keep external plugins in separate Git repository
2. **Testing**: Test plugins thoroughly before production deployment
3. **Security**: Only mount trusted plugin directories
4. **Backup**: Backup working plugin configurations
5. **Documentation**: Document custom plugin APIs and configuration
6. **Monitoring**: Monitor logs for plugin loading and execution errors

## Example Directory Layout

```
project/
├── docker-compose.yml
├── config/
│   └── settings/
│       └── plugins.yaml
├── plugins/
│   ├── README.md
│   ├── requirements.txt
│   ├── my_custom_tracker.py
│   └── enterprise_gps.py
└── data/
    └── logs/
```

This structure keeps your custom plugins organized and separate from the TrakBridge core application.