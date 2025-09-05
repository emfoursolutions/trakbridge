"""
ABOUTME: Common database operation patterns and utilities to reduce boilerplate code
ABOUTME: Provides standardized database access with consistent error handling and retry logic

File: utils/database_helpers.py

Description:
    Common database operation patterns and utilities to reduce the repetitive try/catch 
    patterns found in 24+ files throughout TrakBridge. Provides convenient wrappers
    around the DatabaseManager and standardized database operation patterns.

Key features:
    - Common database operation patterns (create, update, delete, find)
    - Consistent error handling and retry logic
    - Context managers for database transactions
    - Query building utilities
    - Bulk operation helpers

Author: Emfour Solutions
Created: 2025-09-02
Last Modified: 2025-09-02
Version: 1.0.0
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Type, TypeVar, Union

from flask import current_app, has_app_context
from sqlalchemy.exc import SQLAlchemyError

from database import db
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

T = TypeVar("T")


@contextmanager
def database_transaction():
    """
    Context manager for database transactions with automatic rollback on error.

    Usage:
        with database_transaction():
            # Database operations here
            db.session.add(new_record)
            # Automatic commit on success, rollback on exception
    """
    try:
        yield db.session
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Database transaction failed: {e}")
        raise


def safe_database_operation(operation_func, *args, **kwargs):
    """
    Execute database operation with error handling and retry logic.

    Args:
        operation_func: Function to execute
        *args: Arguments for the function
        **kwargs: Keyword arguments for the function

    Returns:
        Result of operation_func or None if failed

    Usage:
        def create_stream(name, config):
            stream = Stream(name=name, config=config)
            db.session.add(stream)
            return stream

        result = safe_database_operation(create_stream, "Test Stream", {})
    """
    max_retries = 3
    retry_delay = 0.5

    for attempt in range(max_retries):
        try:
            with database_transaction():
                return operation_func(*args, **kwargs)
        except SQLAlchemyError as e:
            logger.warning(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                logger.error(f"Database operation failed after {max_retries} attempts")
                return None

            import time

            time.sleep(retry_delay * (attempt + 1))
        except Exception as e:
            logger.error(f"Unexpected error in database operation: {e}")
            return None

    return None


def find_by_id(model_class: Type[T], record_id: int) -> Optional[T]:
    """
    Find record by ID with error handling.

    Args:
        model_class: SQLAlchemy model class
        record_id: ID of the record to find

    Returns:
        Model instance or None if not found

    Usage:
        stream = find_by_id(Stream, 123)
    """
    try:
        return model_class.query.get(record_id)
    except SQLAlchemyError as e:
        logger.error(f"Failed to find {model_class.__name__} with ID {record_id}: {e}")
        return None


def find_by_field(model_class: Type[T], field_name: str, value: Any) -> Optional[T]:
    """
    Find record by field value with error handling.

    Args:
        model_class: SQLAlchemy model class
        field_name: Name of the field to search
        value: Value to search for

    Returns:
        Model instance or None if not found

    Usage:
        user = find_by_field(User, 'username', 'admin')
    """
    try:
        return model_class.query.filter(getattr(model_class, field_name) == value).first()
    except (SQLAlchemyError, AttributeError) as e:
        logger.error(f"Failed to find {model_class.__name__} by {field_name}={value}: {e}")
        return None


def find_all_by_field(model_class: Type[T], field_name: str, value: Any) -> List[T]:
    """
    Find all records by field value with error handling.

    Args:
        model_class: SQLAlchemy model class
        field_name: Name of the field to search
        value: Value to search for

    Returns:
        List of model instances (empty list if none found or error)

    Usage:
        active_streams = find_all_by_field(Stream, 'enabled', True)
    """
    try:
        return model_class.query.filter(getattr(model_class, field_name) == value).all()
    except (SQLAlchemyError, AttributeError) as e:
        logger.error(f"Failed to find {model_class.__name__} records by {field_name}={value}: {e}")
        return []


def create_record(model_class: Type[T], **kwargs) -> Optional[T]:
    """
    Create new record with error handling.

    Args:
        model_class: SQLAlchemy model class
        **kwargs: Field values for the new record

    Returns:
        Created model instance or None if failed

    Usage:
        stream = create_record(Stream, name="Test", enabled=True)
    """

    def _create():
        record = model_class(**kwargs)
        db.session.add(record)
        db.session.flush()  # Flush to get ID without committing
        return record

    return safe_database_operation(_create)


def update_record(record: T, **kwargs) -> Optional[T]:
    """
    Update existing record with error handling.

    Args:
        record: Model instance to update
        **kwargs: Field values to update

    Returns:
        Updated model instance or None if failed

    Usage:
        updated_stream = update_record(stream, enabled=False, name="Updated Name")
    """

    def _update():
        for field, value in kwargs.items():
            if hasattr(record, field):
                setattr(record, field, value)
            else:
                logger.warning(f"Field {field} not found on {record.__class__.__name__}")

        db.session.flush()  # Flush to validate changes
        return record

    return safe_database_operation(_update)


def delete_record(record: T) -> bool:
    """
    Delete record with error handling.

    Args:
        record: Model instance to delete

    Returns:
        True if deleted successfully, False otherwise

    Usage:
        success = delete_record(stream)
    """

    def _delete():
        db.session.delete(record)
        return True

    result = safe_database_operation(_delete)
    return result is not None


def bulk_create(model_class: Type[T], records_data: List[Dict[str, Any]]) -> List[T]:
    """
    Create multiple records efficiently with error handling.

    Args:
        model_class: SQLAlchemy model class
        records_data: List of dictionaries with field values

    Returns:
        List of created model instances

    Usage:
        streams = bulk_create(Stream, [
            {'name': 'Stream 1', 'enabled': True},
            {'name': 'Stream 2', 'enabled': False}
        ])
    """

    def _bulk_create():
        records = []
        for data in records_data:
            record = model_class(**data)
            records.append(record)
            db.session.add(record)

        db.session.flush()  # Flush to get IDs
        return records

    result = safe_database_operation(_bulk_create)
    return result if result is not None else []


def count_records(model_class: Type[T], **filters) -> int:
    """
    Count records with optional filters and error handling.

    Args:
        model_class: SQLAlchemy model class
        **filters: Field filters (field_name=value)

    Returns:
        Count of matching records (0 if error)

    Usage:
        active_count = count_records(Stream, enabled=True)
        total_count = count_records(Stream)
    """
    try:
        query = model_class.query

        for field, value in filters.items():
            if hasattr(model_class, field):
                query = query.filter(getattr(model_class, field) == value)
            else:
                logger.warning(f"Field {field} not found on {model_class.__name__}")

        return query.count()
    except SQLAlchemyError as e:
        logger.error(f"Failed to count {model_class.__name__} records: {e}")
        return 0


def record_exists(model_class: Type[T], **filters) -> bool:
    """
    Check if record exists with given filters.

    Args:
        model_class: SQLAlchemy model class
        **filters: Field filters (field_name=value)

    Returns:
        True if record exists, False otherwise

    Usage:
        exists = record_exists(User, username='admin')
    """
    return count_records(model_class, **filters) > 0


class DatabaseHelper:
    """
    Database helper class for easier database operations within a specific model.

    Usage:
        stream_db = DatabaseHelper(Stream)
        stream = stream_db.find_by_id(123)
        new_stream = stream_db.create(name="Test", enabled=True)
    """

    def __init__(self, model_class: Type[T]):
        self.model_class = model_class

    def find_by_id(self, record_id: int) -> Optional[T]:
        """Find record by ID."""
        return find_by_id(self.model_class, record_id)

    def find_by_field(self, field_name: str, value: Any) -> Optional[T]:
        """Find record by field value."""
        return find_by_field(self.model_class, field_name, value)

    def find_all_by_field(self, field_name: str, value: Any) -> List[T]:
        """Find all records by field value."""
        return find_all_by_field(self.model_class, field_name, value)

    def create(self, **kwargs) -> Optional[T]:
        """Create new record."""
        return create_record(self.model_class, **kwargs)

    def update(self, record: T, **kwargs) -> Optional[T]:
        """Update existing record."""
        return update_record(record, **kwargs)

    def delete(self, record: T) -> bool:
        """Delete record."""
        return delete_record(record)

    def bulk_create(self, records_data: List[Dict[str, Any]]) -> List[T]:
        """Create multiple records."""
        return bulk_create(self.model_class, records_data)

    def count(self, **filters) -> int:
        """Count records with filters."""
        return count_records(self.model_class, **filters)

    def exists(self, **filters) -> bool:
        """Check if record exists."""
        return record_exists(self.model_class, **filters)

    def get_all(self) -> List[T]:
        """Get all records."""
        try:
            return self.model_class.query.all()
        except SQLAlchemyError as e:
            logger.error(f"Failed to get all {self.model_class.__name__} records: {e}")
            return []


# Common database patterns
def get_or_create(
    model_class: Type[T], defaults: Optional[Dict[str, Any]] = None, **kwargs
) -> tuple[T, bool]:
    """
    Get existing record or create new one.

    Args:
        model_class: SQLAlchemy model class
        defaults: Default values for new record creation
        **kwargs: Search criteria and field values

    Returns:
        Tuple of (record, created) where created is True if record was created

    Usage:
        user, created = get_or_create(User, username='admin', defaults={'role': 'admin'})
    """
    record = find_by_field(model_class, list(kwargs.keys())[0], list(kwargs.values())[0])

    if record:
        return record, False

    # Merge defaults with kwargs for creation
    create_data = kwargs.copy()
    if defaults:
        create_data.update(defaults)

    new_record = create_record(model_class, **create_data)
    if new_record:
        return new_record, True
    else:
        # Fallback: try to find again in case of race condition
        record = find_by_field(model_class, list(kwargs.keys())[0], list(kwargs.values())[0])
        return record, False if record else (None, False)


# Convenience functions for common models (can be extended as needed)
def get_stream_helper():
    """Get DatabaseHelper for Stream model."""
    from models.stream import Stream

    return DatabaseHelper(Stream)


def get_user_helper():
    """Get DatabaseHelper for User model."""
    from models.user import User

    return DatabaseHelper(User)


def get_tak_server_helper():
    """Get DatabaseHelper for TakServer model."""
    from models.tak_server import TakServer

    return DatabaseHelper(TakServer)
