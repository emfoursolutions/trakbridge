# Plugin Security and Management

## Overview

TrakBridge implements a secure plugin system that allows administrators to add new GPS tracking plugins without modifying core application code, while maintaining security against arbitrary code execution.

## Security Architecture

### Built-in Security Features

1. **Module Whitelist**: Only pre-approved plugin modules can be loaded
2. **Path Validation**: Prevents path traversal attacks (no `../` allowed)
3. **Namespace Restriction**: All plugins must be under the `plugins.` namespace
4. **Character Filtering**: Only alphanumeric, dots, and underscores allowed in module names
5. **Configuration-based**: Plugin approval is done through configuration files, not code

### Default Allowed Plugins

The following plugins are built-in and always allowed:
- `plugins.garmin_plugin`
- `plugins.spot_plugin`
- `plugins.traccar_plugin`
- `plugins.deepstate_plugin`

## Adding New Plugins Securely

### Method 1: Configuration File (Recommended)

Add new plugins to `config/settings/plugins.yaml`:

```yaml
allowed_plugin_modules:
  - plugins.custom_gps_plugin
  - plugins.enterprise_tracker
  - plugins.third_party.special_tracker
```

### Method 2: Admin CLI Tool

Use the management script for temporary additions:

```bash
# List currently allowed modules
python scripts/manage_plugins.py list

# Add a new plugin module (temporary - until restart)
python scripts/manage_plugins.py add plugins.my_custom_plugin

# Reload configuration from files
python scripts/manage_plugins.py reload
```

### Method 3: Programmatic API

For administrative interfaces:

```python
from plugins.plugin_manager import get_plugin_manager

manager = get_plugin_manager()

# Add a module (temporary)
success = manager.add_allowed_plugin_module('plugins.new_plugin')

# Get current allowed modules
allowed = manager.get_allowed_plugin_modules()

# Reload from config files
manager.reload_plugin_config()
```

## Plugin Development Guidelines

### Security Requirements

1. **Namespace**: All plugins must be in the `plugins.` namespace
2. **Inheritance**: Must inherit from `BaseGPSPlugin`
3. **Validation**: Implement proper input validation
4. **No System Calls**: Avoid shell commands or system calls
5. **Safe Dependencies**: Only use approved third-party libraries

### Example Plugin Structure

```python
# plugins/my_custom_plugin.py
from plugins.base_plugin import BaseGPSPlugin, PluginConfigField

class MyCustomPlugin(BaseGPSPlugin):
    PLUGIN_NAME = "my_custom"
    
    @classmethod
    def get_plugin_name(cls) -> str:
        return cls.PLUGIN_NAME
    
    # ... implement required methods
```

## Configuration File Locations

The system checks these locations in order:

1. `config/settings/plugins.yaml` (recommended)
2. `/etc/trakbridge/plugins.yaml` (system-wide)
3. `~/.trakbridge/plugins.yaml` (user-specific)
4. `plugins.yaml` (current directory)

## Security Considerations

### What This Prevents

- **Arbitrary Code Execution**: Only whitelisted modules can be loaded
- **Path Traversal**: Cannot load modules outside the plugins namespace
- **Injection Attacks**: Module names are strictly validated
- **Privilege Escalation**: Plugins run with same permissions as main app

### What Administrators Must Ensure

- **Trust**: Only add plugins from trusted sources
- **Review**: Review plugin code before adding to whitelist
- **Updates**: Keep plugin dependencies updated
- **Monitoring**: Monitor logs for unauthorized loading attempts

### Security Logging

The system logs:
- Successful plugin module additions
- Rejected unsafe module names
- Unauthorized loading attempts
- Configuration reload events

Example log entries:
```
INFO: Added allowed plugin module from config: plugins.custom_tracker
WARNING: Rejected unsafe plugin module name: ../../../etc/passwd
WARNING: Attempted to load unauthorized plugin module: malicious.plugin
```

## Troubleshooting

### Plugin Not Loading

1. Check if module is in allowed list: `python scripts/manage_plugins.py list`
2. Verify module name follows security requirements
3. Check application logs for security warnings
4. Ensure YAML configuration is valid

### Permission Denied

1. Verify file permissions on config files
2. Check that PyYAML is installed for config file parsing
3. Ensure plugin file is readable by application user

### Development Mode

For development, you can temporarily add modules programmatically, but they won't persist across restarts. Use configuration files for permanent additions.

## Best Practices

1. **Minimal Permissions**: Only add plugins you actually need
2. **Regular Audits**: Periodically review allowed plugin list
3. **Version Control**: Keep plugin configurations in version control
4. **Testing**: Test new plugins in development before production
5. **Documentation**: Document why each plugin was added
6. **Backup**: Backup working configurations before changes