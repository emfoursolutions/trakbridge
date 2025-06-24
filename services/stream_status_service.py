# =============================================================================
# services/stream_status_service.py
# Stream Status Service - Handles all stream status operations
# Extracted from routes/streams.py for better separation of concerns
# =============================================================================

import logging
from datetime import datetime
from models.stream import Stream
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


class StreamStatusService:
    """Service for handling stream status operations"""

    def __init__(self, stream_manager):
        self.stream_manager = stream_manager

    def get_safe_stream_status(self, stream_id):
        """Safely get stream status with error handling"""
        try:
            status = self.stream_manager.get_stream_status(stream_id)
            # Ensure status is always a dictionary
            if not isinstance(status, dict):
                logger.warning(f"Stream status for {stream_id} is not a dict: {type(status)} - {status}")
                # If it's a datetime object, it might be last_poll time - convert appropriately
                if isinstance(status, datetime):
                    return {
                        'running': False,
                        'last_poll': status.isoformat(),
                        'error': None
                    }
                else:
                    return {'running': False, 'error': 'Invalid status format'}
            return status
        except Exception as e:
            logger.error(f"Error getting status for stream {stream_id}: {e}")
            return {'running': False, 'error': str(e)}

    def get_all_streams_status(self):
        """Get status for all streams with error handling"""
        try:
            # Get all stream status from stream manager
            running_status = self.stream_manager.get_all_stream_status()
        except Exception as e:
            logger.error(f"Error getting stream manager status: {e}")
            running_status = {}

        # Safely handle the running_status which might contain non-dict values
        safe_running_status = {}
        if isinstance(running_status, dict):
            for stream_id, status in running_status.items():
                if isinstance(status, dict):
                    safe_running_status[stream_id] = status
                elif isinstance(status, datetime):
                    # Handle datetime objects (might be last_poll time)
                    safe_running_status[stream_id] = {
                        'running': False,
                        'last_poll': status.isoformat(),
                        'error': None
                    }
                else:
                    logger.warning(f"Invalid status format for stream {stream_id}: {type(status)}")
                    safe_running_status[stream_id] = {'running': False}
        else:
            logger.warning(f"Invalid running_status format: {type(running_status)}")
            safe_running_status = {}

        return safe_running_status

    def get_stream_statistics(self):
        """Calculate comprehensive stream statistics"""
        try:
            # Get all streams with eager loading
            streams = Stream.query.options(joinedload(Stream.tak_server)).all()

            # Get running status with error handling
            safe_running_status = self.get_all_streams_status()

            stats = {
                'total_streams': len(streams),
                'active_streams': len([s for s in streams if s.is_active]),
                'running_streams': len([s for s in safe_running_status.values() if s.get('running', False)]),
                'error_streams': len([s for s in streams if s.last_error]),
                'total_messages': sum(s.total_messages_sent or 0 for s in streams),
                'by_plugin': {}
            }

            # Group by plugin type
            for stream in streams:
                plugin_type = stream.plugin_type
                if plugin_type not in stats['by_plugin']:
                    stats['by_plugin'][plugin_type] = {
                        'count': 0,
                        'active': 0,
                        'running': 0,
                        'messages': 0
                    }
                stats['by_plugin'][plugin_type]['count'] += 1
                if stream.is_active:
                    stats['by_plugin'][plugin_type]['active'] += 1
                if safe_running_status.get(stream.id, {}).get('running', False):
                    stats['by_plugin'][plugin_type]['running'] += 1
                stats['by_plugin'][plugin_type]['messages'] += stream.total_messages_sent or 0

            return stats

        except Exception as e:
            logger.error(f"Error getting stream statistics: {e}")
            return {
                'total_streams': 0,
                'active_streams': 0,
                'running_streams': 0,
                'error_streams': 0,
                'total_messages': 0,
                'by_plugin': {},
                'error': str(e)
            }

    def get_detailed_stream_status(self):
        """Get detailed status of all streams"""
        try:
            # Get all streams with eager loading
            streams = Stream.query.options(joinedload(Stream.tak_server)).all()

            # Get all stream status from stream manager
            safe_running_status = self.get_all_streams_status()

            status_data = []
            for stream in streams:
                stream_status = safe_running_status.get(stream.id, {'running': False})

                # Handle last_poll datetime safely
                last_poll_iso = None
                if stream.last_poll:
                    try:
                        if isinstance(stream.last_poll, datetime):
                            last_poll_iso = stream.last_poll.isoformat()
                        else:
                            last_poll_iso = str(stream.last_poll)
                    except Exception as e:
                        logger.warning(f"Error formatting last_poll for stream {stream.id}: {e}")
                        last_poll_iso = None

                status_data.append({
                    'id': stream.id,
                    'name': stream.name,
                    'plugin_type': stream.plugin_type,
                    'is_active': stream.is_active,
                    'running': stream_status.get('running', False),
                    'last_poll': last_poll_iso,
                    'last_error': stream.last_error,
                    'total_messages_sent': stream.total_messages_sent or 0,
                    'tak_server': stream.tak_server.name if stream.tak_server else None
                })

            return {'streams': status_data}

        except Exception as e:
            logger.error(f"Error getting detailed status: {e}")
            return {'streams': [], 'error': str(e)}

    def get_running_stream_ids(self):
        """Get list of currently running stream IDs"""
        try:
            safe_running_status = self.get_all_streams_status()

            running_streams = []
            for stream_id, status in safe_running_status.items():
                if isinstance(status, dict) and status.get('running', False):
                    running_streams.append(stream_id)

            return running_streams

        except Exception as e:
            logger.error(f"Error getting running stream IDs: {e}")
            return []

    @staticmethod
    def format_stream_last_poll(stream):
        """Format stream's last_poll datetime for display"""
        try:
            if stream.last_poll and isinstance(stream.last_poll, datetime):
                return {
                    'last_poll_date': stream.last_poll.strftime('%Y-%m-%d'),
                    'last_poll_time': stream.last_poll.strftime('%H:%M:%S'),
                    'last_poll_iso': stream.last_poll.isoformat()
                }
            else:
                return {
                    'last_poll_date': None,
                    'last_poll_time': None,
                    'last_poll_iso': None
                }
        except Exception as e:
            logger.warning(f"Error formatting last_poll for stream {stream.id}: {e}")
            return {
                'last_poll_date': None,
                'last_poll_time': None,
                'last_poll_iso': None
            }

    @staticmethod
    def validate_stream_status_format(status, stream_id):
        """Validate and normalize stream status format"""
        if isinstance(status, dict):
            return status
        elif isinstance(status, datetime):
            logger.info(f"Converting datetime status for stream {stream_id}")
            return {
                'running': False,
                'last_poll': status.isoformat(),
                'error': None
            }
        else:
            logger.warning(f"Invalid status format for stream {stream_id}: {type(status)}")
            return {
                'running': False,
                'error': f'Invalid status format: {type(status)}'
            }
