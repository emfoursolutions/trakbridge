"""
File: services/database_manager.py

Description:
    Thread-safe database manager providing robust database operations with proper error
    handling and session management for the TrakBridge application. This service handles
    database connections, transaction management, and entity operations with retry logic
    and Flask app context management.

Key features:
    - Thread-safe database operations with Flask app context management
    - Comprehensive error handling with SQLAlchemy exception management and retry logic
    - Stream entity management with relationship loading and detached object creation
    - Active stream monitoring and status update capabilities
    - Database session lifecycle management with proper commit/rollback handling
    - Detached entity copying to prevent lazy loading issues across thread boundaries


Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import time
from typing import TYPE_CHECKING, Optional, List
from datetime import timezone, datetime

# Third-party imports
from sqlalchemy.exc import SQLAlchemyError

# Local application imports
if TYPE_CHECKING:
    from models.stream import Stream

# Module-level logger
logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thread-safe database manager for async operations"""

    def __init__(self, app_context_factory=None):
        self._app_context_factory = app_context_factory

        # Add debug logging
        import traceback

        logger.info(
            f"DatabaseManager created with factory: {app_context_factory is not None}"
        )
        if app_context_factory is None:
            logger.warning("DatabaseManager created WITHOUT app_context_factory!")
            logger.warning("Stack trace:")
            for line in traceback.format_stack():
                logger.warning(line.strip())

    def get_app_context(self):
        """Get Flask app context for database operations"""
        if self._app_context_factory:
            return self._app_context_factory()
        logger.error("No app context factory provided for DatabaseManager")
        return None

    def execute_db_operation(self, operation_func, *args, **kwargs):
        """Execute database operation with proper error handling and retry logic"""
        from database import db

        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                app_ctx = self.get_app_context()
                if not app_ctx:
                    logger.error("No app context available for database operation")
                    return None

                with app_ctx:
                    # Create a new session for this operation
                    try:
                        result = operation_func(*args, **kwargs)
                        db.session.commit()
                        return result
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        logger.error(
                            f"Database error (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(retry_delay * (attempt + 1))
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Unexpected error in database operation: {e}")
                        raise

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Database operation failed after {max_retries} attempts: {e}"
                    )
                    return None
                time.sleep(retry_delay * (attempt + 1))

        return None

    def get_stream(self, stream_id: int) -> Optional["Stream"]:
        """Get stream by ID with error handling and proper session management"""
        from models.stream import Stream

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
        stream_copy.total_messages_sent = getattr(stream, "total_messages_sent", 0)

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
            tak_copy.cert_password = stream.tak_server.get_cert_password()
            tak_copy.has_cert_password = stream.tak_server.has_cert_password

            # Add method to get cert password (for compatibility)
            def get_cert_password():
                return tak_copy.cert_password

            tak_copy.get_cert_password = get_cert_password
            stream_copy.tak_server = tak_copy
        else:
            stream_copy.tak_server = None

        # Add method to get plugin config
        def get_plugin_config():
            return stream_copy.plugin_config or {}

        stream_copy.get_plugin_config = get_plugin_config

        return stream_copy

    def update_stream_status(
        self,
        stream_id: int,
        is_active=None,
        last_error=None,
        messages_sent=None,
        last_poll_time=None,
    ):
        """Update stream status with proper error handling"""

        from models.stream import Stream

        def _update_stream():
            stream = Stream.query.get(stream_id)
            if not stream:
                logger.warning(f"Stream {stream_id} not found for status update")
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
                if (
                    not hasattr(stream, "total_messages_sent")
                    or stream.total_messages_sent is None
                ):
                    stream.total_messages_sent = 0
                stream.total_messages_sent += messages_sent

            return True

        return self.execute_db_operation(_update_stream)

    def get_active_streams(self) -> List["Stream"]:
        """Get all active streams with proper session management"""

        from models.stream import Stream

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

                # Create detached copy
                detached_stream = DatabaseManager._create_detached_stream_copy(stream)
                detached_streams.append(detached_stream)

            return detached_streams

        result = self.execute_db_operation(_get_active_streams)
        return result if result is not None else []

    def get_stream_with_relationships(self, stream_id: int):
        """Get stream with all relationships loaded"""
        from models.stream import Stream

        def _get_stream_with_relationships():
            stream = Stream.query.get(stream_id)
            if stream:
                # Eagerly load relationships
                _ = stream.tak_server
                if stream.tak_server:
                    _ = stream.tak_server.name
                    _ = stream.tak_server.host
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                return DatabaseManager._create_detached_stream_copy(stream)
            return None

        return self.execute_db_operation(_get_stream_with_relationships)

    def get_all_streams_with_relationships(self):
        """Get all streams with relationships loaded"""
        from models.stream import Stream

        def _get_all_streams_with_relationships():
            streams = Stream.query.all()
            detached_streams = []
            for stream in streams:
                # Eagerly load relationships
                _ = stream.tak_server
                if stream.tak_server:
                    _ = stream.tak_server.name
                    _ = stream.tak_server.host
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                detached_stream = DatabaseManager._create_detached_stream_copy(stream)
                detached_streams.append(detached_stream)

            return detached_streams

        return self.execute_db_operation(_get_all_streams_with_relationships)
