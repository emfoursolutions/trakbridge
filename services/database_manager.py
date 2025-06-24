# =============================================================================
# services/database_manager.py - Database Management Service
# =============================================================================

import logging
import time
from typing import Optional, List
from sqlalchemy.exc import SQLAlchemyError
from models.stream import Stream
from datetime import timezone, datetime
from database import db


class DatabaseManager:
    """Thread-safe database manager for async operations"""

    def __init__(self, app_context_factory=None):
        self.logger = logging.getLogger('DatabaseManager')
        self._app_context_factory = app_context_factory

    def get_app_context(self):
        """Get Flask app context for database operations"""
        if self._app_context_factory:
            return self._app_context_factory()
        # Fallback to direct import (to be removed in later phases)
        try:
            from app import app
            return app
        except Exception as e:
            self.logger.error(f"Failed to get app context: {e}")
            return None

    def execute_db_operation(self, operation_func, *args, **kwargs):
        """Execute database operation with proper error handling and retry logic"""

        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                app = self.get_app_context()
                if not app:
                    self.logger.error("No app context available for database operation")
                    return None

                with app.app_context():
                    # Create a new session for this operation
                    try:
                        result = operation_func(*args, **kwargs)
                        db.session.commit()
                        return result
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        self.logger.error(f"Database error (attempt {attempt + 1}/{max_retries}): {e}")
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(retry_delay * (attempt + 1))
                    except Exception as e:
                        db.session.rollback()
                        self.logger.error(f"Unexpected error in database operation: {e}")
                        raise

            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                    return None
                time.sleep(retry_delay * (attempt + 1))

        return None

    def get_stream(self, stream_id: int) -> Optional[Stream]:
        """Get stream by ID with error handling and proper session management"""

        def _get_stream():
            stream = Stream.query.get(stream_id)
            if stream:
                # Eagerly load relationships to avoid lazy loading issues
                # This ensures all data is loaded while session is active
                _ = stream.tak_server  # Access tak_server to load it
                if stream.tak_server:
                    _ = stream.tak_server.name  # Access name to ensure it's loaded
                    _ = stream.tak_server.host  # Access other commonly used fields
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                # Create a detached copy with all necessary data
                return DatabaseManager._create_detached_stream_copy(stream)
            return None

        return self.execute_db_operation(_get_stream)

    @staticmethod
    def _create_detached_stream_copy(stream):
        """Create a detached copy of stream with all necessary data"""

        # Create a simple object to hold stream data
        from types import SimpleNamespace

        # Copy basic stream attributes
        stream_copy = SimpleNamespace()
        stream_copy.id = stream.id
        stream_copy.name = stream.name
        stream_copy.plugin_type = stream.plugin_type
        stream_copy.is_active = stream.is_active
        stream_copy.last_poll = stream.last_poll
        stream_copy.last_error = stream.last_error
        stream_copy.poll_interval = stream.poll_interval
        stream_copy.cot_type = stream.cot_type
        stream_copy.cot_stale_time = stream.cot_stale_time
        stream_copy.plugin_config = stream.plugin_config
        stream_copy.total_messages_sent = getattr(stream, 'total_messages_sent', 0)

        # Copy TAK server data if it exists
        if stream.tak_server:
            tak_copy = SimpleNamespace()
            tak_copy.id = stream.tak_server.id
            tak_copy.name = stream.tak_server.name
            tak_copy.host = stream.tak_server.host
            tak_copy.port = stream.tak_server.port
            tak_copy.protocol = stream.tak_server.protocol
            tak_copy.verify_ssl = stream.tak_server.verify_ssl
            tak_copy.cert_p12 = stream.tak_server.cert_p12
            tak_copy.cert_password = stream.tak_server.cert_password
            stream_copy.tak_server = tak_copy
        else:
            stream_copy.tak_server = None

        # Add method to get plugin config
        def get_plugin_config():
            return stream_copy.plugin_config or {}

        stream_copy.get_plugin_config = get_plugin_config

        return stream_copy

    def update_stream_status(self, stream_id: int, is_active=None, last_error=None,
                             messages_sent=None, last_poll_time=None):
        """Update stream status with proper error handling"""

        def _update_stream():
            stream = Stream.query.get(stream_id)
            if not stream:
                self.logger.warning(f"Stream {stream_id} not found for status update")
                return False

            if is_active is not None:
                stream.is_active = is_active

            if last_error is not None:
                stream.last_error = last_error

            if last_poll_time is not None:
                stream.last_poll = last_poll_time
            elif is_active:  # Update last_poll when marking active
                stream.last_poll = datetime.now(timezone.utc)

            if messages_sent is not None:
                if not hasattr(stream, 'total_messages_sent') or stream.total_messages_sent is None:
                    stream.total_messages_sent = 0
                stream.total_messages_sent += messages_sent

            return True

        return self.execute_db_operation(_update_stream)

    def get_active_streams(self) -> List[Stream]:
        """Get all active streams with proper session management"""

        def _get_active_streams():
            streams = Stream.query.filter_by(is_active=True).all()
            # Create detached copies of all streams
            detached_streams = []
            for stream in streams:
                # Eagerly load relationships
                _ = stream.tak_server
                if stream.tak_server:
                    _ = stream.tak_server.name
                    _ = stream.tak_server.host
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                detached_streams.append(DatabaseManager._create_detached_stream_copy(stream))

            return detached_streams

        result = self.execute_db_operation(_get_active_streams)
        return result if result is not None else []

    def get_stream_with_relationships(self, stream_id: int):
        """Get stream with all relationships loaded - for use in Flask routes"""

        def _get_stream_with_relationships():
            from sqlalchemy.orm import joinedload

            # Use joinedload to eagerly load the tak_server relationship
            stream = Stream.query.options(
                joinedload(Stream.tak_server)
            ).filter_by(id=stream_id).first()

            if stream:
                return DatabaseManager._create_detached_stream_copy(stream)
            return None

        return self.execute_db_operation(_get_stream_with_relationships)

    def get_all_streams_with_relationships(self):
        """Get all streams with relationships loaded - for use in Flask routes"""

        def _get_all_streams_with_relationships():
            from sqlalchemy.orm import joinedload

            streams = Stream.query.options(
                joinedload(Stream.tak_server)
            ).all()

            detached_streams = []
            for stream in streams:
                detached_streams.append(DatabaseManager._create_detached_stream_copy(stream))

            return detached_streams

        result = self.execute_db_operation(_get_all_streams_with_relationships)
        return result if result is not None else []
