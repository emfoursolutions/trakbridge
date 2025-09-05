"""
File: services/database_manager.py

Description:
    Thread-safe database manager providing robust database operations with
    proper error handling and session management for the TrakBridge
    application. This service handles database connections, transaction
    management, and entity operations with retry logic and Flask app context
    management.

Key features:
    - Thread-safe database operations with Flask app context management
    - Comprehensive error handling with SQLAlchemy exception management
      and retry logic
    - Stream entity management with relationship loading and detached
      object creation
    - Active stream monitoring and status update capabilities
    - Database session lifecycle management with proper commit/rollback
      handling
    - Detached entity copying to prevent lazy loading issues across
      thread boundaries


Author: Emfour Solutions
Created: 18-Jul-2025
"""

# Standard library imports
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

# Third-party imports
from sqlalchemy.exc import SQLAlchemyError

from services.logging_service import get_module_logger

# Local application imports
if TYPE_CHECKING:
    from models.stream import Stream

# Module-level logger
logger = get_module_logger(__name__)


class DatabaseManager:
    """Thread-safe database manager for async operations"""

    def __init__(self, app_context_factory=None):
        self._app_context_factory = app_context_factory

        # Add debug logging
        import traceback

        logger.info(
            f"DatabaseManager created with factory: "
            f"{app_context_factory is not None}"
        )
        if app_context_factory is None:
            logger.warning(
                "DatabaseManager created WITHOUT app_context_factory!"
            )
            logger.warning("Stack trace:")
            for line in traceback.format_stack():
                logger.warning(line.strip())

    def _is_concurrency_error(self, e: Exception) -> bool:
        """
        Universal concurrency error detection for all database types.

        Detects optimistic locking conflicts, deadlocks, and other
        concurrency issues that can occur when multiple processes
        try to update the same record.
        """
        from sqlalchemy.exc import IntegrityError, OperationalError

        error_str = str(e).lower()

        # MariaDB/MySQL specific errors - including Error 1020
        if (
            "1020" in error_str
            or "record has changed since last read" in error_str
        ):
            return True

        # PostgreSQL specific errors
        if isinstance(e, OperationalError):
            postgres_patterns = [
                "could not serialize access due to concurrent update",
                "deadlock detected",
                "tuple concurrently updated",
                "could not obtain lock on row",
            ]
            if any(pattern in error_str for pattern in postgres_patterns):
                return True

        # SQLite specific errors
        if isinstance(e, OperationalError):
            sqlite_patterns = [
                "database is locked",
                "database table is locked",
                "cannot start a transaction within a transaction",
                "disk i/o error",  # Can indicate lock contention
            ]
            if any(pattern in error_str for pattern in sqlite_patterns):
                return True

        # Generic IntegrityError that might indicate concurrency issues
        if isinstance(e, IntegrityError):
            # Some integrity errors are actually concurrency-related
            concurrency_integrity_patterns = [
                "duplicate key",
                "unique constraint",
                "foreign key constraint",  # Can happen during concurrent deletes
            ]
            if any(
                pattern in error_str
                for pattern in concurrency_integrity_patterns
            ):
                return True

        return False

    def _get_database_type(self) -> str:
        """Get database type for logging purposes"""
        from database import db

        try:
            dialect_name = db.engine.dialect.name.lower()
            if dialect_name in ["mysql", "mariadb"]:
                return "MariaDB/MySQL"
            elif dialect_name == "postgresql":
                return "PostgreSQL"
            elif dialect_name == "sqlite":
                return "SQLite"
            else:
                return dialect_name
        except Exception:
            return "Unknown"

    def get_app_context(self):
        """Get Flask app context for database operations"""
        if self._app_context_factory:
            return self._app_context_factory()
        logger.error("No app context factory provided for DatabaseManager")
        return None

    def execute_db_operation(self, operation_func, *args, **kwargs):
        """Execute database operation with proper error handling and retry."""
        from database import db

        max_retries = 3
        retry_delay = 0.1  # Start with 100ms delay like stream operations
        db_type = self._get_database_type()

        for attempt in range(max_retries):
            try:
                app_ctx = self.get_app_context()
                if not app_ctx:
                    logger.error(
                        "No app context available for database operation"
                    )
                    return None

                with app_ctx:
                    # Create a new session for this operation
                    try:
                        result = operation_func(*args, **kwargs)
                        db.session.commit()
                        return result
                    except SQLAlchemyError as e:
                        db.session.rollback()

                        # Check if this is a concurrency error using detection
                        if self._is_concurrency_error(e):
                            if attempt < max_retries - 1:
                                retry_delay_with_jitter = retry_delay * (
                                    2**attempt
                                ) + (attempt * 0.05)
                                logger.warning(
                                    f"Concurrency conflict on {db_type} in "
                                    f"database operation (attempt "
                                    f"{attempt + 1}/{max_retries}), retrying "
                                    f"in {retry_delay_with_jitter:.2f}s: {e}"
                                )
                                time.sleep(retry_delay_with_jitter)
                                continue
                            else:
                                logger.error(
                                    f"Failed database operation on {db_type} "
                                    f"after {max_retries} attempts due to "
                                    f"concurrency conflicts: {e}"
                                )
                                raise
                        else:
                            # Non-concurrency SQLAlchemy error - log and retry
                            logger.error(
                                f"Database error (attempt "
                                f"{attempt + 1}/{max_retries}) on "
                                f"{db_type}: {e}"
                            )
                            if attempt == max_retries - 1:
                                raise
                            time.sleep(retry_delay * (attempt + 1))
                    except Exception as e:
                        db.session.rollback()
                        logger.error(
                            f"Unexpected error in database operation: {e}"
                        )
                        raise

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(
                        f"Database operation failed after {max_retries} "
                        f"attempts: {e}"
                    )
                    return None
                time.sleep(retry_delay * (attempt + 1))

        return None

    def get_stream(self, stream_id: int) -> Optional["Stream"]:
        """Get stream by ID with error handling and proper session management."""
        from models.stream import Stream

        def _get_stream():
            stream = Stream.query.get(stream_id)
            if stream:
                # Eagerly load relationships to avoid lazy loading issues
                # This ensures all data is loaded while session is active
                _ = stream.tak_server  # Access tak_server to load it
                if stream.tak_server:
                    _ = (
                        stream.tak_server.name
                    )  # Access name to ensure it's loaded
                    _ = (
                        stream.tak_server.host
                    )  # Access other commonly used fields
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
        stream_copy.total_messages_sent = getattr(
            stream, "total_messages_sent", 0
        )

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
                logger.warning(
                    f"Stream {stream_id} not found for status update"
                )
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
                detached_stream = DatabaseManager._create_detached_stream_copy(
                    stream
                )
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

                detached_stream = DatabaseManager._create_detached_stream_copy(
                    stream
                )
                detached_streams.append(detached_stream)

            return detached_streams

        return self.execute_db_operation(_get_all_streams_with_relationships)
