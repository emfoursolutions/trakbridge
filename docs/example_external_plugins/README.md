# External Plugins Example

This directory contains example external plugins that can be mounted into a TrakBridge Docker container.

## Usage

1. **Copy this directory** to your Docker host
2. **Configure plugin allowlist** in `config/settings/plugins.yaml`:
   ```yaml
   allowed_plugin_modules:
     - external_plugins.sample_custom_tracker
   ```
3. **Mount as Docker volume**:
   ```bash
   docker run -v $(pwd)/example_external_plugins:/app/external_plugins:ro trakbridge:latest
   ```

## Files

- `sample_custom_tracker.py` - Example custom GPS tracker plugin
- `README.md` - This file

## Development

To create your own external plugin:

1. Copy `sample_custom_tracker.py` as a template
2. Modify the class name and `PLUGIN_NAME`
3. Implement your API calls in `fetch_locations()`
4. Update the configuration fields in `plugin_metadata`
5. Test your plugin before deployment

## Security

- External plugins run in the `external_plugins.*` namespace
- All plugins must be explicitly allowed in configuration
- Mount directories as read-only (`:ro`) in production
- Only load plugins from trusted sources

## Troubleshooting

Check the TrakBridge logs for plugin loading messages:
```bash
docker logs <container_name> | grep -i external_plugins
```