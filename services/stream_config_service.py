# services/stream_config_service.py
import logging
from datetime import datetime, timezone
from models.stream import Stream

logger = logging.getLogger(__name__)


class StreamConfigService:
    def __init__(self, plugin_manager):
        self.plugin_manager = plugin_manager

    def validate_plugin_config_security(self, plugin_type, config):
        """Validate that sensitive fields are properly handled"""
        metadata = self.plugin_manager.get_plugin_metadata(plugin_type)
        if not metadata:
            return True, []

        warnings = []

        # Check for sensitive fields that might be exposed
        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, dict) and field_data.get("sensitive"):
                field_name = field_data["name"]
                if field_name in config:
                    value = config[field_name]
                    # Warn if sensitive data doesn't appear to be encrypted
                    if value and not str(value).startswith("ENC:"):
                        warnings.append(f"Sensitive field '{field_name}' may not be encrypted")

        return len(warnings) == 0, warnings

    def extract_plugin_config_from_request(self, data):
        """Extract plugin configuration from request data by removing plugin_ prefix"""
        plugin_config = {}
        for key, value in data.items():
            if key.startswith('plugin_'):
                plugin_config[key[7:]] = value  # Remove 'plugin_' prefix
        return plugin_config

    def export_stream_config(self, stream_id, include_sensitive=False):
        """Export stream configuration with optional sensitive field masking"""
        try:
            stream = Stream.query.get_or_404(stream_id)

            # Export with sensitive fields optionally masked
            export_data = {
                'name': stream.name,
                'plugin_type': stream.plugin_type,
                'plugin_config': stream.to_dict(include_sensitive=include_sensitive)['plugin_config'],
                'poll_interval': stream.poll_interval,
                'cot_type': stream.cot_type,
                'cot_stale_time': stream.cot_stale_time,
                'exported_at': datetime.now(timezone.utc).isoformat(),
                'note': 'Sensitive fields have been masked for security' if not include_sensitive else 'Full configuration export'
            }

            return export_data

        except Exception as e:
            logger.error(f"Error exporting stream config {stream_id}: {e}")
            raise

    def get_security_status(self):
        """Get security status of all streams"""
        try:
            streams = Stream.query.all()
            status = {
                'total_streams': len(streams),
                'encrypted_streams': 0,
                'warnings': []
            }

            for stream in streams:
                config = stream.get_raw_plugin_config()
                is_secure, warnings = self.validate_plugin_config_security(stream.plugin_type, config)

                if is_secure:
                    status['encrypted_streams'] += 1
                else:
                    status['warnings'].extend([
                        f"Stream '{stream.name}': {warning}" for warning in warnings
                    ])

            status['encryption_percentage'] = (
                (status['encrypted_streams'] / status['total_streams'] * 100)
                if status['total_streams'] > 0 else 100
            )

            return status

        except Exception as e:
            logger.error(f"Error getting security status: {e}")
            raise

    def get_plugin_metadata(self, plugin_name):
        """Get metadata for a specific plugin"""
        try:
            plugin_class = self.plugin_manager.plugins.get(plugin_name)
            if plugin_class:
                # Create temporary instance to get metadata
                temp_instance = plugin_class({})
                return self.serialize_plugin_metadata(temp_instance.plugin_metadata)
            return None

        except Exception as e:
            logger.error(f"Error getting plugin metadata for {plugin_name}: {e}")
            return None

    def get_all_plugin_metadata(self):
        """Get metadata for all available plugins"""
        try:
            available_plugins = self.plugin_manager.list_plugins()
            plugin_metadata = {}

            for plugin_name in available_plugins:
                metadata = self.get_plugin_metadata(plugin_name)
                if metadata:
                    plugin_metadata[plugin_name] = metadata

            return plugin_metadata

        except Exception as e:
            logger.error(f"Error getting all plugin metadata: {e}")
            return {}

    def serialize_plugin_metadata(self, metadata):
        """Convert plugin metadata to JSON-serializable format"""
        if isinstance(metadata, dict):
            result = {}
            for key, value in metadata.items():
                result[key] = self.serialize_plugin_metadata(value)
            return result
        elif isinstance(metadata, list):
            return [self.serialize_plugin_metadata(item) for item in metadata]
        elif hasattr(metadata, '__dict__'):
            # This is likely a PluginConfigField or similar object
            # Convert to dictionary
            result = {}
            for attr_name in dir(metadata):
                if not attr_name.startswith('_'):  # Skip private attributes
                    try:
                        attr_value = getattr(metadata, attr_name)
                        # Skip methods
                        if not callable(attr_value):
                            result[attr_name] = self.serialize_plugin_metadata(attr_value)
                    except:
                        pass  # Skip attributes that can't be accessed
            return result
        else:
            # Return as-is for basic types (str, int, bool, etc.)
            return metadata

    def prepare_stream_for_display(self, stream):
        """Prepare stream data for display, masking sensitive fields"""
        # Get plugin metadata to identify sensitive fields
        plugin_class = self.plugin_manager.plugins.get(stream.plugin_type)
        if not plugin_class:
            return stream

        try:
            temp_instance = plugin_class({})
            metadata = self.serialize_plugin_metadata(temp_instance.plugin_metadata)

            # Use the stream's to_dict method that masks sensitive data
            stream.display_config = stream.to_dict(include_sensitive=False)['plugin_config']
            stream.plugin_metadata = metadata

            return stream

        except Exception as e:
            logger.warning(f"Could not prepare stream {stream.id} for display: {e}")
            return stream