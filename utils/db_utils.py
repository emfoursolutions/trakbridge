# =============================================================================
# utils/db_utils.py - Database Session Management Utilities
# =============================================================================

import logging
from contextlib import contextmanager
from functools import wraps
from flask import current_app
import threading

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thread-safe database operations manager"""

    _local = threading.local()

    @classmethod
    def get_app(cls):
        """Get current app instance safely"""
        try:
            return current_app._get_current_object()
        except RuntimeError:
            # Fallback to app import
            from app import app
            return app

    @classmethod
    @contextmanager
    def get_session(cls):
        """Get a thread-safe database session"""
        app = cls.get_app()

        with app.app_context():
            from app import db

            try:
                # Create a new session for this thread if needed
                session = db.session
                yield session
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Database session error: {e}")
                raise
            finally:
                # Remove session to prevent leaks
                session.remove()

    @classmethod
    def safe_get(cls, model_class, id_value):
        """Safely get a model instance by ID"""
        with cls.get_session() as session:
            return session.get(model_class, id_value)

    @classmethod
    def safe_query(cls, model_class, **filters):
        """Safely query model instances"""
        with cls.get_session() as session:
            query = session.query(model_class)
            for key, value in filters.items():
                query = query.filter(getattr(model_class, key) == value)
            return query.all()

    @classmethod
    def safe_create(cls, model_instance):
        """Safely create a model instance"""
        with cls.get_session() as session:
            session.add(model_instance)
            session.flush()  # Get ID without committing
            session.refresh(model_instance)
            return model_instance

    @classmethod
    def safe_update(cls, model_class, id_value, **updates):
        """Safely update a model instance"""
        with cls.get_session() as session:
            instance = session.get(model_class, id_value)
            if instance:
                for key, value in updates.items():
                    setattr(instance, key, value)
                session.flush()
                session.refresh(instance)
                return instance
            return None

    @classmethod
    def safe_delete(cls, model_class, id_value):
        """Safely delete a model instance"""
        with cls.get_session() as session:
            instance = session.get(model_class, id_value)
            if instance:
                session.delete(instance)
                return True
            return False


def with_db_session(func):
    """Decorator to provide database session to function"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        with DatabaseManager.get_session() as session:
            return func(session, *args, **kwargs)

    return wrapper


def async_db_operation(func):
    """Decorator for async functions that need database access"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        app = DatabaseManager.get_app()

        with app.app_context():
            return await func(*args, **kwargs)

    return wrapper


class StreamDataManager:
    """Specialized manager for stream-related database operations"""

    @staticmethod
    def get_stream_config(stream_id):
        """Get stream configuration in a thread-safe way"""
        from models.stream import Stream

        stream = DatabaseManager.safe_get(Stream, stream_id)
        if not stream:
            return None

        return {
            'id': stream.id,
            'name': stream.name,
            'plugin_type': stream.plugin_type,
            'plugin_config': stream.get_plugin_config() if hasattr(stream, 'get_plugin_config') else {},
            'poll_interval': stream.poll_interval,
            'cot_type': stream.cot_type,
            'cot_stale_time': stream.cot_stale_time,
            'tak_server_id': stream.tak_server_id,
            'is_active': stream.is_active,
            'last_error': stream.last_error,
            'total_messages_sent': stream.total_messages_sent or 0
        }

    @staticmethod
    def update_stream_status(stream_id, **updates):
        """Update stream status safely"""
        from models.stream import Stream

        try:
            result = DatabaseManager.safe_update(Stream, stream_id, **updates)
            if result:
                logger.debug(f"Updated stream {stream_id} status: {updates}")
                return True
            else:
                logger.warning(f"Stream {stream_id} not found for status update")
                return False
        except Exception as e:
            logger.error(f"Error updating stream {stream_id} status: {e}")
            return False

    @staticmethod
    def get_tak_server_config(server_id):
        """Get TAK server configuration safely"""
        from models.tak_server import TakServer

        server = DatabaseManager.safe_get(TakServer, server_id)
        if not server:
            return None

        return {
            'id': server.id,
            'name': server.name,
            'host': server.host,
            'port': server.port,
            'protocol': server.protocol,
            'cert_file': server.cert_file,
            'key_file': server.key_file,
            'ca_file': server.ca_file,
            'verify_ssl': server.verify_ssl
        }


# Convenience functions for common operations
def get_stream_safely(stream_id):
    """Get stream data safely across threads"""
    return StreamDataManager.get_stream_config(stream_id)


def update_stream_safely(stream_id, **updates):
    """Update stream safely across threads"""
    return StreamDataManager.update_stream_status(stream_id, **updates)


def get_tak_server_safely(server_id):
    """Get TAK server config safely across threads"""
    return StreamDataManager.get_tak_server_config(server_id)