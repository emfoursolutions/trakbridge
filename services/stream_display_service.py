# =============================================================================
# services/stream_display_service.py - Stream Display and Presentation Logic
# Handles formatting and preparation of stream data for UI display
# =============================================================================

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from models.stream import Stream
from sqlalchemy.orm import joinedload
from services.stream_status_service import StreamStatusService
from services.cot_type_service import cot_type_service

logger = logging.getLogger(__name__)


class StreamDisplayService:
    """Service for handling stream display and presentation logic"""

    def __init__(self, plugin_manager, status_service: Optional[StreamStatusService] = None):
        self.plugin_manager = plugin_manager
        self.status_service = status_service

    def get_streams_for_listing(self) -> List[Stream]:
        """Get all streams prepared for listing display"""
        try:
            # Use joinedload to eagerly load the tak_server relationship
            streams = Stream.query.options(joinedload(Stream.tak_server)).all()

            # Prepare each stream for display
            for stream in streams:
                self._prepare_stream_for_listing(stream)

            return streams

        except Exception as e:
            logger.error(f"Error getting streams for listing: {e}")
            return []

    def get_stream_for_detail_view(self, stream_id: int) -> Stream:
        """Get a single stream prepared for detail view"""
        # Use joinedload to eagerly load the tak_server relationship
        stream = Stream.query.options(joinedload(Stream.tak_server)).filter_by(id=stream_id).first_or_404()

        # Prepare stream for detail display
        self._prepare_stream_for_detail(stream)

        return stream

    def get_stream_for_edit_form(self, stream_id: int) -> Stream:
        """Get a stream prepared for the edit form"""
        # Use joinedload to eagerly load the tak_server relationship
        stream = Stream.query.options(joinedload(Stream.tak_server)).filter_by(id=stream_id).first_or_404()

        # No special preparation needed for edit form beyond basic loading
        return stream

    def _prepare_stream_for_listing(self, stream: Stream) -> None:
        """Prepare a stream for listing display"""
        # Add plugin metadata
        self._add_plugin_metadata(stream)

        # Add running status
        self._add_running_status(stream)

        # Format datetime fields
        self._format_datetime_fields(stream)

        # Add COT type information
        self._add_cot_type_info(stream)

    def _prepare_stream_for_detail(self, stream: Stream) -> None:
        """Prepare a stream for detail view display"""
        # Add plugin metadata
        self._add_plugin_metadata(stream)

        # Add running status
        self._add_running_status(stream)

        # Format datetime fields
        self._format_datetime_fields(stream)

        # Add display config (masked sensitive fields)
        self._add_display_config(stream)

        # Add COT type information
        self._add_cot_type_info(stream)

    def _add_plugin_metadata(self, stream: Stream) -> None:
        """Add plugin metadata to stream"""
        try:
            plugin_class = self.plugin_manager.plugins.get(stream.plugin_type)
            if plugin_class:
                temp_instance = plugin_class({})
                stream.plugin_metadata = self._serialize_plugin_metadata(temp_instance.plugin_metadata)
            else:
                stream.plugin_metadata = None
        except Exception as e:
            logger.warning(f"Could not load metadata for plugin {stream.plugin_type}: {e}")
            stream.plugin_metadata = None

    def _add_running_status(self, stream: Stream) -> None:
        """Add running status to stream"""
        if self.status_service:
            stream.running_status = self.status_service.get_safe_stream_status(stream.id)
        else:
            # Fallback if no status service provided
            stream.running_status = {'running': False, 'error': 'Status service not available'}

    def _add_cot_type_info(self, stream: Stream) -> None:
        """Add COT type information including icon data"""
        try:
            cot_type = cot_type_service.get_cot_type_by_value(stream.cot_type)
            if cot_type:
                # Store the CotType object for potential future use
                stream.cot_type_info = cot_type
                # Add individual fields for easy template access
                stream.cot_type_label = cot_type.label
                stream.cot_type_description = cot_type.description
                stream.cot_type_sidc = cot_type.sidc
                stream.cot_type_category = cot_type.category
            else:
                # Fallback for unknown COT types
                stream.cot_type_info = None
                stream.cot_type_label = stream.cot_type
                stream.cot_type_description = 'Unknown COT type'
                stream.cot_type_sidc = ''
                stream.cot_type_category = 'unknown'
                logger.warning(f"Unknown COT type: {stream.cot_type} for stream {stream.id}")
        except Exception as e:
            logger.error(f"Error adding COT type info for stream {stream.id}: {e}")
            # Set safe defaults
            stream.cot_type_info = None
            stream.cot_type_label = stream.cot_type
            stream.cot_type_description = 'Error loading COT type info'
            stream.cot_type_sidc = ''
            stream.cot_type_category = 'unknown'

    def _format_datetime_fields(self, stream: Stream) -> None:
        """Format datetime fields for template display"""
        if stream.last_poll and isinstance(stream.last_poll, datetime):
            try:
                stream.last_poll_date = stream.last_poll.strftime('%Y-%m-%d')
                stream.last_poll_time = stream.last_poll.strftime('%H:%M:%S')
                stream.last_poll_iso = stream.last_poll.isoformat()
            except Exception as e:
                logger.warning(f"Error formatting last_poll for stream {stream.id}: {e}")
                stream.last_poll_date = None
                stream.last_poll_time = None
                stream.last_poll_iso = None
        else:
            stream.last_poll_date = None
            stream.last_poll_time = None
            stream.last_poll_iso = None

    def _add_display_config(self, stream: Stream) -> None:
        """Add display configuration with sensitive fields masked"""
        try:
            # Get plugin metadata to identify sensitive fields
            plugin_class = self.plugin_manager.plugins.get(stream.plugin_type)
            if not plugin_class:
                stream.display_config = stream.get_plugin_config()
                return

            # Use the stream's to_dict method that masks sensitive data
            stream.display_config = stream.to_dict(include_sensitive=False)['plugin_config']

        except Exception as e:
            logger.warning(f"Could not prepare display config for stream {stream.id}: {e}")
            stream.display_config = {}

    def calculate_plugin_statistics(self, streams: List[Stream]) -> Tuple[Dict[str, int], Dict[str, Any]]:
        """Calculate plugin statistics and metadata"""
        plugin_stats = {}
        plugin_metadata = {}

        for stream in streams:
            plugin_type = stream.plugin_type

            # Count plugin usage
            plugin_stats[plugin_type] = plugin_stats.get(plugin_type, 0) + 1

            # Collect plugin metadata (only need one instance per plugin type)
            if plugin_type not in plugin_metadata and hasattr(stream, 'plugin_metadata') and stream.plugin_metadata:
                plugin_metadata[plugin_type] = stream.plugin_metadata

        return plugin_stats, plugin_metadata

    def prepare_stream_for_display(self, stream: Stream) -> Stream:
        """Legacy method - prepare stream data for display, masking sensitive fields"""
        # This method maintains compatibility with existing code
        self._prepare_stream_for_detail(stream)
        return stream

    def _serialize_plugin_metadata(self, metadata: Any) -> Any:
        """Convert plugin metadata to JSON-serializable format"""
        if isinstance(metadata, dict):
            result = {}
            for key, value in metadata.items():
                result[key] = self._serialize_plugin_metadata(value)
            return result
        elif isinstance(metadata, list):
            return [self._serialize_plugin_metadata(item) for item in metadata]
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
                            result[attr_name] = self._serialize_plugin_metadata(attr_value)
                    except:
                        pass  # Skip attributes that can't be accessed
            return result
        else:
            # Return as-is for basic types (str, int, bool, etc.)
            return metadata

    def format_stream_list_for_api(self, streams: List[Stream]) -> List[Dict[str, Any]]:
        """Format stream list for API responses"""
        formatted_streams = []

        for stream in streams:
            # Ensure stream is prepared for display
            if not hasattr(stream, 'running_status'):
                self._add_running_status(stream)

            if not hasattr(stream, 'last_poll_iso'):
                self._format_datetime_fields(stream)

            if not hasattr(stream, 'cot_type_info'):
                self._add_cot_type_info(stream)

            formatted_stream = {
                'id': stream.id,
                'name': stream.name,
                'plugin_type': stream.plugin_type,
                'is_active': stream.is_active,
                'running': getattr(stream, 'running_status', {}).get('running', False),
                'last_poll': getattr(stream, 'last_poll_iso', None),
                'last_error': stream.last_error,
                'total_messages_sent': stream.total_messages_sent or 0,
                'tak_server': stream.tak_server.name if stream.tak_server else None,
                'poll_interval': stream.poll_interval,
                'cot_type': stream.cot_type,
                'cot_type_label': getattr(stream, 'cot_type_label', stream.cot_type),
                'cot_type_sidc': getattr(stream, 'cot_type_sidc', ''),
                'cot_stale_time': stream.cot_stale_time
            }

            formatted_streams.append(formatted_stream)

        return formatted_streams

    def get_stream_summary(self, stream: Stream) -> Dict[str, Any]:
        """Get a summary of stream information for quick display"""
        self._add_running_status(stream)
        self._format_datetime_fields(stream)
        self._add_cot_type_info(stream)

        return {
            'id': stream.id,
            'name': stream.name,
            'plugin_type': stream.plugin_type,
            'is_active': stream.is_active,
            'running': getattr(stream, 'running_status', {}).get('running', False),
            'last_poll': getattr(stream, 'last_poll_iso', None),
            'message_count': stream.total_messages_sent or 0,
            'has_error': bool(stream.last_error),
            'tak_server_name': stream.tak_server.name if stream.tak_server else None,
            'cot_type_label': getattr(stream, 'cot_type_label', stream.cot_type),
            'cot_type_sidc': getattr(stream, 'cot_type_sidc', '')
        }

    def get_plugin_usage_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get summary of plugin usage across all streams"""
        try:
            streams = Stream.query.options(joinedload(Stream.tak_server)).all()

            # Add running status to all streams
            for stream in streams:
                self._add_running_status(stream)

            plugin_summary = {}

            for stream in streams:
                plugin_type = stream.plugin_type

                if plugin_type not in plugin_summary:
                    plugin_summary[plugin_type] = {
                        'total_streams': 0,
                        'active_streams': 0,
                        'running_streams': 0,
                        'total_messages': 0,
                        'error_streams': 0
                    }

                summary = plugin_summary[plugin_type]
                summary['total_streams'] += 1

                if stream.is_active:
                    summary['active_streams'] += 1

                if getattr(stream, 'running_status', {}).get('running', False):
                    summary['running_streams'] += 1

                if stream.last_error:
                    summary['error_streams'] += 1

                summary['total_messages'] += stream.total_messages_sent or 0

            return plugin_summary

        except Exception as e:
            logger.error(f"Error getting plugin usage summary: {e}")
            return {}