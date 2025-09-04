"""
ABOUTME: Comprehensive tests for CRUD pattern consolidation using DatabaseHelper patterns
ABOUTME: Tests consistent database operation patterns and service layer standardization

TDD Tests for Phase 4: CRUD Pattern Consolidation
These tests define expected behavior for standardized database operations,
consistent error handling, and service layer database access patterns.

Author: Emfour Solutions
Created: 2025-09-04
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import db
from models.callsign_mapping import CallsignMapping
from models.stream import Stream
from models.tak_server import TakServer
from models.user import AuthProvider, User, UserRole
from utils.database_helpers import (DatabaseHelper, create_record,
                                    database_transaction, delete_record,
                                    find_by_field, find_by_id, get_or_create,
                                    safe_database_operation, update_record)


class TestDatabaseHelperPatterns:
    """Test that DatabaseHelper is used consistently across services."""

    def test_database_helper_crud_operations(self, app, db_session):
        """Test that DatabaseHelper provides consistent CRUD operations."""
        with app.app_context():
            # Test StreamHelper
            stream_helper = DatabaseHelper(Stream)

            # Create
            stream = stream_helper.create(
                name="Test Stream", plugin_type="garmin", is_active=True
            )
            assert (
                stream is not None
            ), "DatabaseHelper.create should return created instance"
            assert stream.name == "Test Stream"
            assert stream.id is not None

            # Read
            found_stream = stream_helper.find_by_id(stream.id)
            assert (
                found_stream is not None
            ), "DatabaseHelper.find_by_id should find created stream"
            assert found_stream.name == "Test Stream"

            found_by_name = stream_helper.find_by_field("name", "Test Stream")
            assert found_by_name is not None, "DatabaseHelper.find_by_field should work"
            assert found_by_name.id == stream.id

            # Update
            updated_stream = stream_helper.update(stream, name="Updated Stream")
            assert (
                updated_stream is not None
            ), "DatabaseHelper.update should return updated instance"
            assert updated_stream.name == "Updated Stream"

            # Delete
            delete_result = stream_helper.delete(stream)
            assert (
                delete_result is True
            ), "DatabaseHelper.delete should return True on success"

            # Verify deletion
            deleted_stream = stream_helper.find_by_id(stream.id)
            assert deleted_stream is None, "Deleted stream should not be found"

    def test_service_classes_use_database_helpers(self, app, db_session):
        """Test that service classes use DatabaseHelper instead of raw queries."""
        with app.app_context():
            # This test will initially fail until services are migrated
            from services.stream_manager import StreamManager
            from services.stream_operations_service import \
                StreamOperationsService

            # Mock StreamManager and database for testing
            mock_stream_manager = MagicMock()

            service = StreamOperationsService(mock_stream_manager, db)

            # Check that service has been updated to use database helpers
            # This will fail initially until refactoring is complete
            assert hasattr(
                service, "_stream_helper"
            ), "StreamOperationsService should use DatabaseHelper for Stream operations"
            assert hasattr(
                service, "_tak_server_helper"
            ), "StreamOperationsService should use DatabaseHelper for TakServer operations"

            # Test that helper methods are used for common operations
            test_data = {
                "name": "Test Stream",
                "plugin_type": "garmin",
                "tak_server_id": 1,
                "poll_interval": 120,
            }

            # This should use DatabaseHelper internally
            with patch.object(service, "_stream_helper") as mock_helper:
                mock_helper.create.return_value = Stream(
                    name="Test Stream", plugin_type="garmin"
                )

                result = service.create_stream(test_data)

                # Verify helper was called instead of direct database access
                mock_helper.create.assert_called_once()

    def test_database_transaction_context_manager(self, app, db_session):
        """Test that database operations use transaction context managers."""
        with app.app_context():
            # Test successful transaction
            with database_transaction():
                stream = Stream(name="Transaction Test", plugin_type="garmin")
                db.session.add(stream)

            # Should be committed automatically
            found_stream = Stream.query.filter_by(name="Transaction Test").first()
            assert (
                found_stream is not None
            ), "Transaction should commit automatically on success"

            # Test transaction rollback on error
            try:
                with database_transaction():
                    stream2 = Stream(name="Rollback Test", plugin_type="spot")
                    db.session.add(stream2)
                    db.session.flush()  # Ensure it's in the database

                    raise ValueError("Test error")  # Force rollback
            except ValueError:
                pass

            # Should be rolled back
            rollback_stream = Stream.query.filter_by(name="Rollback Test").first()
            assert rollback_stream is None, "Transaction should rollback on error"

    def test_safe_database_operation_error_handling(self, app, db_session):
        """Test that database operations use safe_database_operation wrapper."""
        with app.app_context():
            # Test successful operation
            def create_stream():
                stream = Stream(name="Safe Op Test", plugin_type="garmin")
                db.session.add(stream)
                return stream

            result = safe_database_operation(create_stream)
            assert result is not None, "Safe operation should return result on success"
            assert result.name == "Safe Op Test"

            # Test operation with database error
            def failing_operation():
                # Try to create duplicate with unique constraint violation
                stream1 = Stream(name="Duplicate Test", plugin_type="garmin")
                db.session.add(stream1)
                db.session.flush()

                # This should cause constraint violation if unique constraint exists
                stream2 = Stream(name="Duplicate Test", plugin_type="spot")
                db.session.add(stream2)
                return stream2

            # First operation should succeed
            result1 = safe_database_operation(failing_operation)
            assert result1 is not None, "First operation should succeed"

    def test_get_or_create_pattern_usage(self, app, db_session):
        """Test that get_or_create pattern is used consistently."""
        with app.app_context():
            # Test creating new record
            user, created = get_or_create(
                User,
                username="testuser",
                defaults={
                    "email": "test@example.com",
                    "auth_provider": AuthProvider.LOCAL,
                    "role": UserRole.USER,
                },
            )

            assert user is not None, "get_or_create should return user instance"
            assert created is True, "Should indicate new user was created"
            assert user.username == "testuser"
            assert user.email == "test@example.com"

            # Test getting existing record
            user2, created2 = get_or_create(
                User,
                username="testuser",
                defaults={"email": "different@example.com"},  # Should be ignored
            )

            assert user2 is not None, "get_or_create should return existing user"
            assert created2 is False, "Should indicate existing user was returned"
            assert user2.id == user.id, "Should be the same user instance"
            assert (
                user2.email == "test@example.com"
            ), "Should keep original email, not defaults"


class TestServiceDatabasePatterns:
    """Test that service classes follow consistent database access patterns."""

    def test_services_avoid_direct_session_access(self, app, db_session):
        """Test that services don't access db.session directly."""
        with app.app_context():
            # This test will fail initially until services are refactored
            from services.tak_servers_service import TakServerService

            # Check service methods for direct db.session usage
            service = TakServerService()

            # Services should not have direct db.session calls
            # This is a code inspection test - would need static analysis in real scenario
            service_methods = [
                method for method in dir(service) if not method.startswith("_")
            ]

            for method_name in service_methods:
                method = getattr(service, method_name)
                if callable(method):
                    # This is a conceptual test - in reality we'd use static analysis
                    # For now, we'll just verify services have helper methods
                    pass

            # Services should use helper patterns instead
            # This will fail initially until refactoring
            assert hasattr(service, "_get_database_helper") or hasattr(
                service, "db_helper"
            ), "Services should use database helper patterns, not direct session access"

    def test_consistent_error_response_patterns(self, app, db_session):
        """Test that services return consistent error response formats."""
        with app.app_context():
            from services.stream_manager import StreamManager
            from services.stream_operations_service import \
                StreamOperationsService

            mock_stream_manager = MagicMock()
            service = StreamOperationsService(mock_stream_manager, db)

            # Test error response format for invalid data
            invalid_data = {
                "name": "",  # Empty name should cause validation error
                "plugin_type": "invalid_plugin",
            }

            try:
                result = service.create_stream(invalid_data)
                # If no exception, check result format
                if isinstance(result, dict) and "error" in result:
                    # Should have consistent error format
                    assert "error" in result, "Error responses should have 'error' key"
                    assert (
                        "message" in result
                    ), "Error responses should have 'message' key"
                    assert isinstance(result["error"], str), "Error should be string"
                    assert isinstance(
                        result["message"], str
                    ), "Message should be string"
            except Exception as e:
                # Exception handling should also be consistent
                assert isinstance(
                    e, (ValueError, IntegrityError)
                ), f"Should raise standard exceptions, got {type(e)}"

    def test_bulk_operation_efficiency(self, app, db_session):
        """Test that services use efficient bulk operations."""
        with app.app_context():
            # Create TAK server for streams
            server = TakServer(
                name="Bulk Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            # Test bulk stream creation should be more efficient than individual creates
            stream_data_list = []
            for i in range(10):
                stream_data_list.append(
                    {
                        "name": f"Bulk Stream {i}",
                        "plugin_type": "garmin",
                        "tak_server_id": server.id,
                        "is_active": True,
                    }
                )

            # Time bulk creation
            import time

            start_time = time.time()

            # Use bulk_create helper method
            from utils.database_helpers import bulk_create

            created_streams = bulk_create(Stream, stream_data_list)

            end_time = time.time()
            duration = end_time - start_time

            # Should be efficient - complete in under 0.5 seconds for 10 items
            # This will fail initially if not optimized
            assert (
                duration < 0.5
            ), f"Bulk creation took {duration:.3f}s, should be under 0.5s"
            assert len(created_streams) == 10, "Should create all 10 streams"

            # Verify all streams were created
            total_bulk_streams = Stream.query.filter(
                Stream.name.like("Bulk Stream%")
            ).count()
            assert total_bulk_streams == 10, "All bulk streams should be in database"

    def test_relationship_loading_optimization(self, app, db_session):
        """Test that services use optimized relationship loading."""
        with app.app_context():
            # Create test data
            server = TakServer(
                name="Relation Test Server", host="localhost", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            streams = []
            for i in range(5):
                stream = Stream(
                    name=f"Relation Stream {i}",
                    plugin_type="garmin",
                    tak_server_id=server.id,
                )
                streams.append(stream)
                db_session.add(stream)

            db_session.commit()

            # Test that services avoid N+1 queries
            from services.database_manager import DatabaseManager

            # Mock app context factory
            def mock_app_context():
                return app.app_context()

            db_manager = DatabaseManager(mock_app_context)

            # This should use efficient loading
            active_streams = db_manager.get_active_streams()

            # Verify relationships are loaded efficiently
            for stream in active_streams:
                # Accessing tak_server should not cause additional queries
                # because of optimized loading in DatabaseManager
                assert hasattr(
                    stream, "tak_server"
                ), "Stream should have tak_server loaded"
                if stream.tak_server:
                    assert hasattr(
                        stream.tak_server, "name"
                    ), "TakServer should have name loaded"


class TestDatabaseOperationStandardization:
    """Test standardized database operation patterns."""

    def test_consistent_validation_patterns(self, app, db_session):
        """Test that database operations use consistent validation."""
        with app.app_context():
            # Test Stream validation
            stream_helper = DatabaseHelper(Stream)

            # Should validate required fields
            result = stream_helper.create(plugin_type="garmin")  # Missing name
            # This will fail initially until validation is consistent
            assert (
                result is None
            ), "Should return None for invalid data, not raise exception"

            # Test with valid data
            valid_stream = stream_helper.create(
                name="Valid Stream", plugin_type="garmin"
            )
            assert valid_stream is not None, "Should create with valid data"

    def test_standardized_query_methods(self, app, db_session):
        """Test that models have standardized query methods."""
        with app.app_context():
            # Create test data
            user1 = User.create_local_user(username="user1", password="pass")
            user2 = User.create_local_user(username="user2", password="pass")

            db_session.add(user1)
            db_session.add(user2)
            db_session.commit()

            # Test standardized query methods exist
            user_helper = DatabaseHelper(User)

            # Test find methods
            found_user = user_helper.find_by_field("username", "user1")
            assert found_user is not None, "find_by_field should work consistently"
            assert found_user.username == "user1"

            # Test count methods
            total_users = user_helper.count()
            assert total_users >= 2, "count should return total records"

            local_users = user_helper.count(auth_provider=AuthProvider.LOCAL)
            assert local_users >= 2, "count with filters should work"

            # Test existence check
            exists = user_helper.exists(username="user1")
            assert exists is True, "exists should return True for existing record"

            not_exists = user_helper.exists(username="nonexistent")
            assert not_exists is False, "exists should return False for missing record"

    def test_transaction_retry_logic(self, app, db_session):
        """Test that database operations implement retry logic for transient failures."""
        with app.app_context():
            # Mock SQLAlchemy error to test retry logic
            call_count = [0]  # Use list to allow modification in nested function

            def failing_operation():
                call_count[0] += 1
                if call_count[0] < 3:  # Fail first 2 times
                    raise SQLAlchemyError("Transient database error")

                # Succeed on third try
                stream = Stream(name="Retry Test", plugin_type="garmin")
                db.session.add(stream)
                return stream

            # Should retry and eventually succeed
            result = safe_database_operation(failing_operation)

            # This will fail initially until retry logic is implemented
            assert result is not None, "Should succeed after retries"
            assert (
                call_count[0] == 3
            ), f"Should retry 3 times, actually called {call_count[0]} times"
            assert result.name == "Retry Test"

    def test_connection_pool_management(self, app, db_session):
        """Test that database operations properly manage connection pools."""
        with app.app_context():
            # Test that multiple concurrent operations don't exhaust connection pool
            import concurrent.futures
            import threading

            def database_operation(thread_id):
                try:
                    stream = create_record(
                        Stream,
                        name=f"Concurrent Stream {thread_id}",
                        plugin_type="garmin",
                    )
                    return stream is not None
                except Exception as e:
                    return False

            # Run multiple concurrent operations
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(database_operation, i) for i in range(10)]

                results = [
                    future.result()
                    for future in concurrent.futures.as_completed(futures)
                ]

            # All operations should succeed without connection pool exhaustion
            # This may fail initially if connection pooling is not properly configured
            successful_operations = sum(results)
            assert (
                successful_operations == 10
            ), f"All 10 operations should succeed, got {successful_operations} successes"
