# External Plugins Example

This directory contains example external plugins that can be mounted into a TrakBridge Docker container.

## Usage

1. **Copy this directory** to your Docker host
2. **Configure plugin allowlist** in `config/settings/plugins.yaml`:

   ```yaml
   allowed_plugin_modules:
     - external_plugins.sample_custom_tracker
     - external_plugins.sample_custom_handler
   ```

3. **Mount as Docker volume**:

   ```bash
   docker run -v $(pwd)/example_external_plugins:/app/external_plugins:ro trakbridge:latest
   ```

## Files

- `sample_custom_tracker.py` - Example custom GPS tracker plugin (input)
- `sample_custom_handler.py` - Example custom CoT handler plugin (output)
- `README.md` - This file

## Plugin Types

### Input Plugins (GPS Trackers)

Input plugins fetch location data from external sources and send it to TAK servers as CoT messages.

**Example: `sample_custom_tracker.py`**

- Inherits from `BaseGPSPlugin`
- Implements `fetch_locations()` to retrieve GPS data
- Periodically polls external API
- Converts data to TrakBridge location format

### Output Plugins (CoT Handlers)

Output plugins receive CoT messages from TAK servers and process them (send alerts, log, store, etc.).

**Example: `sample_custom_handler.py`**

- Inherits from `BaseOutputPlugin`
- Implements `handle_cot_message()` to process incoming CoT
- Filters messages by type, UID, location, etc.
- Sends formatted alerts to external webhook

## Development Guide

### Creating an Input Plugin (GPS Tracker)

1. Copy `sample_custom_tracker.py` as a template
2. Modify the class name and `plugin_name` property
3. Implement your API calls in `fetch_locations()`
4. Update the configuration fields in `plugin_metadata`
5. Test your plugin before deployment

**Key Methods:**

- `fetch_locations(session)` - Fetch GPS data from external API
- `plugin_metadata` - Define configuration fields for UI
- `test_connection()` - Verify API connectivity

### Creating an Output Plugin (CoT Handler)

1. Copy `sample_custom_handler.py` as a template
2. Modify the class name and `plugin_name` property
3. Implement your message processing in `handle_cot_message()`
4. Add filtering logic in `_should_handle()`
5. Update the configuration fields in `plugin_metadata`
6. Test your plugin before deployment

**Key Methods:**

- `handle_cot_message(cot_xml, tak_server_id)` - Process incoming CoT messages
- `_should_handle()` - Filter messages by type, UID, location, etc.
- `_extract_template_variables()` - Extract data from CoT XML
- `test_connection()` - Verify webhook connectivity
- `start()` - Initialize connections when stream starts (optional)
- `cleanup()` - Close connections when stream stops (optional)

**Best Practices:**

- Use `defusedxml` for XML parsing (NEVER use standard `xml.etree`)
- NEVER raise exceptions from `handle_cot_message()` - always catch and log
- Use async I/O for all network operations
- Set timeouts on all external API calls
- Implement deduplication to prevent duplicate messages
- Mark sensitive fields with `sensitive=True` for automatic encryption
- Add comprehensive help sections in `plugin_metadata`

### Sample Handler Features Demonstrated

The `sample_custom_handler.py` demonstrates:

1. **Configuration Management**
   - Required and optional fields
   - Sensitive field encryption
   - Field validation

2. **CoT Message Parsing**
   - Safe XML parsing with defusedxml
   - Extracting CoT type, UID, coordinates
   - Extracting detail elements (callsign, remarks, battery, etc.)

3. **Multi-Level Filtering**
   - CoT type filtering with wildcard support
   - UID regex pattern matching
   - Geographic filtering (commented examples)
   - Time-based filtering (commented examples)

4. **Message Formatting**
   - Template-based formatting with variables
   - User-customizable templates
   - Error handling for missing variables

5. **Deduplication**
   - Tracking recently seen messages
   - Preventing duplicate processing
   - Automatic cleanup of old entries

6. **Performance Optimization**
   - Batch processing option
   - Connection pooling
   - Metrics tracking

7. **Error Handling**
   - Timeout protection on external calls
   - Graceful degradation
   - Comprehensive logging

8. **Lifecycle Management**
   - `start()` for initialization
   - `cleanup()` for resource release
   - `test_connection()` for validation

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
