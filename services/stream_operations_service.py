# =============================================================================
# services/stream_operations_service.py
# Stream Operations Service - Handles all stream lifecycle operations
# Extracted from routes/streams.py for better separation of concerns
# =============================================================================

import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Union
from models.stream import Stream
from services.exceptions import (
    StreamManagerError, StreamNotFoundError, StreamConfigurationError,
    StreamStartupError, StreamTimeoutError, DatabaseError
)

logger = logging.getLogger(__name__)


class StreamOperationsService:
    """Service for handling stream lifecycle operations"""

    def __init__(self, stream_manager: Any, db: Any) -> None:
        self.stream_manager = stream_manager
        self.db = db

    def create_stream(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new stream with the provided data"""
        try:
            stream = Stream(
                name=data['name'],
                plugin_type=data['plugin_type'],
                poll_interval=int(data.get('poll_interval', 120)),
                cot_type=data.get('cot_type', 'a-f-G-U-C'),
                cot_stale_time=int(data.get('cot_stale_time', 300)),
                tak_server_id=int(data['tak_server_id'])
            )

            # Set plugin configuration
            plugin_config: Dict[str, Any] = {}
            for key, value in data.items():
                if key.startswith('plugin_'):
                    plugin_config[key[7:]] = value  # Remove 'plugin_' prefix

            stream.set_plugin_config(plugin_config)

            self.db.session.add(stream)
            self.db.session.commit()

            # Auto-start if requested
            if data.get('auto_start'):
                try:
                    success = self.stream_manager.start_stream_sync(stream.id)
                    if success:
                        message = 'Stream created and started successfully'
                    else:
                        message = 'Stream created but failed to start automatically'
                except Exception as e:
                    logger.error(f"Error auto-starting stream: {e}")
                    message = 'Stream created but failed to start automatically'
            else:
                message = 'Stream created successfully'

            return {
                'success': True,
                'stream_id': stream.id,
                'message': message
            }

        except (ValueError, TypeError) as e:
            logger.error(f"Configuration error creating stream: {e}")
            return {'success': False, 'error': f'Invalid configuration: {e}'}
        except StreamConfigurationError as e:
            logger.error(f"Stream configuration error: {e}")
            return {'success': False, 'error': f'Configuration error: {e}'}
        except DatabaseError as e:
            logger.error(f"Database error creating stream: {e}")
            return {'success': False, 'error': f'Database error: {e}'}
        except (OSError, RuntimeError) as e:
            logger.error(f"System error creating stream: {e}", exc_info=True)
            return {'success': False, 'error': f'System error: {e}'}
        except Exception as e:
            logger.error(f"Unexpected error creating stream: {e}", exc_info=True)
            return {'success': False, 'error': f'Unexpected error: {e}'}

    def start_stream_with_enable(self, stream_id: int) -> Dict[str, Any]:
        """Enable and start a stream"""
        try:
            # First, ensure the stream is enabled in the database
            stream = Stream.query.get_or_404(stream_id)

            # Enable the stream if it's not already enabled
            if not stream.is_active:
                stream.is_active = True
                self.db.session.commit()
                logger.info(f"Enabled stream {stream_id} ({stream.name})")

            # Now start the stream through StreamManager using the sync wrapper
            success = self.stream_manager.start_stream_sync(stream_id)

            if success:
                logger.info(f"Stream {stream_id} started successfully")
                return {
                    'success': True,
                    'message': 'Stream started successfully'
                }
            else:
                logger.error(f"Failed to start stream {stream_id}")
                return {
                    'success': False,
                    'error': 'Failed to start stream'
                }

        except Exception as e:
            logger.error(f"Error starting stream {stream_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def stop_stream_with_disable(self, stream_id: int) -> Dict[str, Any]:
        """Stop and disable a stream"""
        try:
            # Update database status
            stream = Stream.query.get_or_404(stream_id)
            stream.is_active = False
            self.db.session.commit()
            logger.info(f"Disabled stream {stream_id} ({stream.name})")

            # Stop the stream through StreamManager using the sync wrapper
            success = self.stream_manager.stop_stream_sync(stream_id)

            if success:
                logger.info(f"Stream {stream_id} stopped successfully")
                return {
                    'success': True,
                    'message': 'Stream stopped successfully'
                }
            else:
                logger.error(f"Failed to stop stream {stream_id}")
                return {
                    'success': False,
                    'error': 'Failed to stop stream'
                }

        except Exception as e:
            logger.error(f"Error stopping stream {stream_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def restart_stream(self, stream_id: int) -> Dict[str, Any]:
        """Restart a stream"""
        try:
            # Use the stream manager's sync wrapper for restart
            success = self.stream_manager.restart_stream_sync(stream_id)

            if success:
                logger.info(f"Stream {stream_id} restarted successfully")
                return {
                    'success': True,
                    'message': 'Stream restarted successfully'
                }
            else:
                logger.error(f"Failed to restart stream {stream_id}")
                return {
                    'success': False,
                    'error': 'Failed to restart stream'
                }

        except Exception as e:
            logger.error(f"Error restarting stream {stream_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def delete_stream(self, stream_id: int) -> Dict[str, Any]:
        """Delete a stream"""
        try:
            stream = Stream.query.get_or_404(stream_id)

            # Stop the stream if it's running
            if stream.is_active:
                try:
                    self.stream_manager.stop_stream_sync(stream_id)
                except Exception as e:
                    logger.warning(f"Error stopping stream before deletion: {e}")

            # Delete from database
            self.db.session.delete(stream)
            self.db.session.commit()

            logger.info(f"Stream {stream_id} deleted successfully")
            return {
                'success': True,
                'message': 'Stream deleted successfully'
            }

        except Exception as e:
            logger.error(f"Error deleting stream {stream_id}: {e}")
            self.db.session.rollback()
            return {
                'success': False,
                'error': str(e)
            }

    def update_stream_safely(self, stream_id: int, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update stream with proper stop/restart handling"""
        try:
            from sqlalchemy.orm import joinedload

            # Get stream with eager loading
            stream = Stream.query.options(joinedload(Stream.tak_server)).filter_by(id=stream_id).first_or_404()

            # Check if the stream is currently running
            stream_status = self._safe_get_stream_status(stream_id)
            was_running = stream_status.get('running', False)

            # Stop the stream if it's running (we'll restart it after update)
            if was_running:
                self.stream_manager.stop_stream_sync(stream_id)

            # Update stream properties
            stream.name = data['name']
            stream.plugin_type = data['plugin_type']
            stream.poll_interval = int(data.get('poll_interval', 120))
            stream.cot_type = data.get('cot_type', 'a-f-G-U-C')
            stream.cot_stale_time = int(data.get('cot_stale_time', 300))
            stream.tak_server_id = int(data['tak_server_id'])

            # Update plugin configuration
            plugin_config: Dict[str, Any] = {}
            for key, value in data.items():
                if key.startswith('plugin_'):
                    plugin_config[key[7:]] = value  # Remove 'plugin_' prefix

            # Handle missing checkbox fields for all plugins
            from plugins.plugin_manager import get_plugin_manager
            plugin_manager = get_plugin_manager()
            plugin_type = data.get('plugin_type')
            if plugin_type:
                metadata = plugin_manager.get_plugin_metadata(plugin_type)
                if metadata:
                    for field in metadata.get("config_fields", []):
                        # Handle both dict and object (e.g., PluginConfigField)
                        if (isinstance(field, dict) and field.get("field_type") == "checkbox") or \
                                (hasattr(field, "field_type") and getattr(field, "field_type") == "checkbox"):
                            field_name = field["name"] if isinstance(field, dict) else getattr(field, "name")
                            if field_name not in plugin_config:
                                plugin_config[field_name] = False

            stream.set_plugin_config(plugin_config)

            self.db.session.commit()

            # Restart the stream if it was running before
            if was_running:
                self.stream_manager.start_stream_sync(stream_id)

            return {
                'success': True,
                'stream_id': stream.id,
                'message': 'Stream updated successfully'
            }

        except Exception as e:
            self.db.session.rollback()
            logger.error(f"Error updating stream {stream_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def run_health_check(self) -> Dict[str, Any]:
        """Trigger a health check on all streams"""
        try:
            # Run health check in the background event loop
            future = asyncio.run_coroutine_threadsafe(
                self.stream_manager.health_check(),
                self.stream_manager.loop
            )
            future.result(timeout=30)

            return {
                'success': True,
                'message': 'Health check completed'
            }

        except Exception as e:
            logger.error(f"Error during health check: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def bulk_start_streams(self) -> Dict[str, Any]:
        """Start all active streams"""
        try:
            active_streams = Stream.query.filter_by(is_active=True).all()
            started_count = 0
            failed_count = 0

            for stream in active_streams:
                try:
                    success = self.stream_manager.start_stream_sync(stream.id)
                    if success:
                        started_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error starting stream {stream.id}: {e}")
                    failed_count += 1

            return {
                'success': True,
                'message': f'Started {started_count} streams, {failed_count} failed',
                'started': started_count,
                'failed': failed_count
            }

        except Exception as e:
            logger.error(f"Error starting all streams: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def bulk_stop_streams(self) -> Dict[str, Any]:
        """Stop all running streams"""
        try:
            # Get running status with error handling
            try:
                running_status = self.stream_manager.get_all_stream_status()
            except Exception as e:
                logger.error(f"Error getting stream manager status: {e}")
                running_status = {}

            # Find running streams with improved error handling
            running_streams = []
            if isinstance(running_status, dict):
                for stream_id, status in running_status.items():
                    if isinstance(status, dict) and status.get('running', False):
                        running_streams.append(stream_id)
                    # Skip non-dict status values as they're likely not running

            stopped_count = 0
            failed_count = 0

            for stream_id in running_streams:
                try:
                    success = self.stream_manager.stop_stream_sync(stream_id)
                    if success:
                        stopped_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error stopping stream {stream_id}: {e}")
                    failed_count += 1

            return {
                'success': True,
                'message': f'Stopped {stopped_count} streams, {failed_count} failed',
                'stopped': stopped_count,
                'failed': failed_count
            }

        except Exception as e:
            logger.error(f"Error stopping all streams: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _safe_get_stream_status(self, stream_id: int) -> Optional[Dict[str, Any]]:
        """Safely get stream status, ensuring it returns a dict"""
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
