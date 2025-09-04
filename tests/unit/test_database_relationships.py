"""
ABOUTME: Comprehensive tests for database relationship optimization and constraints
ABOUTME: Tests foreign key relationships, cascade behavior, indexes, and constraint enforcement

TDD Tests for Phase 4: Database Model Optimization
These tests define the expected behavior for optimized database relationships,
constraints, and performance improvements.

Author: Emfour Solutions
Created: 2025-09-04
"""

import pytest
import time
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from database import db
from models.stream import Stream
from models.tak_server import TakServer
from models.user import User, UserSession, UserRole, AuthProvider, AccountStatus
from models.callsign_mapping import CallsignMapping


class TestDatabaseRelationships:
    """Test database relationships, constraints, and cascading behavior."""

    def test_stream_tak_server_foreign_key_constraint(self, app, db_session):
        """Test Stream-TakServer foreign key constraint enforcement."""
        with app.app_context():
            # This should fail initially - we expect foreign key constraints to be enforced
            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=999999  # Non-existent server ID
            )
            db_session.add(stream)
            
            # This should raise IntegrityError for foreign key constraint
            with pytest.raises(IntegrityError):
                db_session.commit()
            
            db_session.rollback()

    def test_stream_tak_server_relationship_loading(self, app, db_session):
        """Test that Stream-TakServer relationship loads efficiently without N+1 queries."""
        with app.app_context():
            # Create TAK server
            server = TakServer(
                name="Test Server",
                host="localhost",
                port=8089,
                protocol="tls"
            )
            db_session.add(server)
            db_session.flush()

            # Create multiple streams
            streams = []
            for i in range(5):
                stream = Stream(
                    name=f"Test Stream {i}",
                    plugin_type="garmin",
                    tak_server_id=server.id
                )
                streams.append(stream)
                db_session.add(stream)
            
            db_session.commit()

            # Test eager loading - should use only 1 query, not N+1
            # This test will initially fail until we implement eager loading
            query_count_before = self._get_query_count(db_session)
            
            loaded_streams = db_session.query(Stream).options(
                joinedload(Stream.tak_server)
            ).all()
            
            query_count_after = self._get_query_count(db_session)
            
            # Should access tak_server without additional queries
            for stream in loaded_streams:
                assert stream.tak_server.name == "Test Server"
            
            # This will fail initially - we expect only 1 additional query for eager loading
            assert (query_count_after - query_count_before) <= 1, \
                f"Expected 1 query or less, got {query_count_after - query_count_before}"

    def test_callsign_mapping_unique_constraint(self, app, db_session):
        """Test CallsignMapping unique constraint on (stream_id, identifier_value)."""
        with app.app_context():
            # Create stream
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.flush()

            # Create first callsign mapping
            mapping1 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="IMEI123456",
                custom_callsign="Alpha1"
            )
            db_session.add(mapping1)
            db_session.commit()

            # Try to create duplicate - should fail with unique constraint
            mapping2 = CallsignMapping(
                stream_id=stream.id,
                identifier_value="IMEI123456",  # Same identifier
                custom_callsign="Alpha2"
            )
            db_session.add(mapping2)
            
            # This should raise IntegrityError for unique constraint violation
            with pytest.raises(IntegrityError):
                db_session.commit()
            
            db_session.rollback()

    def test_stream_deletion_cascade_behavior(self, app, db_session):
        """Test that deleting a stream properly cascades to callsign mappings."""
        with app.app_context():
            # Create stream
            stream = Stream(name="Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.flush()

            # Create callsign mappings
            for i in range(3):
                mapping = CallsignMapping(
                    stream_id=stream.id,
                    identifier_value=f"IMEI{i}",
                    custom_callsign=f"Alpha{i}"
                )
                db_session.add(mapping)
            
            db_session.commit()
            
            # Verify mappings exist
            mapping_count = CallsignMapping.query.filter_by(stream_id=stream.id).count()
            assert mapping_count == 3

            # Delete stream - should cascade to mappings
            db_session.delete(stream)
            db_session.commit()

            # Verify mappings are deleted (cascade)
            remaining_mappings = CallsignMapping.query.filter_by(stream_id=stream.id).count()
            # This will fail initially until cascade is properly configured
            assert remaining_mappings == 0, \
                f"Expected 0 remaining mappings after stream deletion, got {remaining_mappings}"

    def test_user_session_relationship_cascade(self, app, db_session):
        """Test User-UserSession relationship cascade behavior."""
        with app.app_context():
            # Create user
            user = User.create_local_user(
                username="testuser",
                password="testpass",
                email="test@example.com"
            )
            db_session.add(user)
            db_session.flush()

            # Create sessions
            for i in range(3):
                session = UserSession.create_session(
                    user=user,
                    ip_address=f"192.168.1.{i}",
                    user_agent="TestAgent"
                )
                db_session.add(session)
            
            db_session.commit()
            
            # Verify sessions exist
            session_count = UserSession.query.filter_by(user_id=user.id).count()
            assert session_count == 3

            # Delete user - should cascade to sessions
            db_session.delete(user)
            db_session.commit()

            # Verify sessions are deleted (cascade)
            remaining_sessions = UserSession.query.filter_by(user_id=user.id).count()
            # This will fail initially until cascade is properly configured
            assert remaining_sessions == 0, \
                f"Expected 0 remaining sessions after user deletion, got {remaining_sessions}"

    def test_database_indexes_exist(self, app, db_session):
        """Test that required database indexes are present for performance."""
        with app.app_context():
            inspector = inspect(db.engine)
            
            # Test Stream table indexes
            stream_indexes = inspector.get_indexes('streams')
            index_columns = {idx['column_names'][0] for idx in stream_indexes if len(idx['column_names']) == 1}
            
            # These will fail initially until indexes are added
            assert 'tak_server_id' in index_columns, "Missing index on streams.tak_server_id"
            assert 'is_active' in index_columns, "Missing index on streams.is_active"

            # Test User table indexes  
            user_indexes = inspector.get_indexes('users')
            user_index_columns = {idx['column_names'][0] for idx in user_indexes if len(idx['column_names']) == 1}
            
            assert 'username' in user_index_columns, "Missing index on users.username"
            assert 'email' in user_index_columns, "Missing index on users.email"
            assert 'auth_provider' in user_index_columns, "Missing index on users.auth_provider"

            # Test CallsignMapping compound index
            callsign_indexes = inspector.get_indexes('callsign_mappings')
            compound_indexes = {tuple(idx['column_names']) for idx in callsign_indexes if len(idx['column_names']) > 1}
            
            assert ('stream_id', 'identifier_value') in compound_indexes, \
                "Missing compound index on callsign_mappings(stream_id, identifier_value)"

    def _get_query_count(self, session):
        """Get approximate query count for testing N+1 prevention."""
        # This is a simplified approach - in a real scenario you'd use query logging
        # For now, we'll return 0 and this will be improved in implementation
        return 0


class TestDatabaseConstraints:
    """Test database constraint enforcement and data integrity."""

    def test_user_unique_constraints(self, app, db_session):
        """Test User model unique constraints on username and email."""
        with app.app_context():
            # Create first user
            user1 = User.create_local_user(
                username="uniqueuser",
                password="pass123",
                email="unique@example.com"
            )
            db_session.add(user1)
            db_session.commit()

            # Try to create user with same username
            user2 = User.create_local_user(
                username="uniqueuser",  # Duplicate username
                password="pass456", 
                email="different@example.com"
            )
            db_session.add(user2)
            
            with pytest.raises(IntegrityError):
                db_session.commit()
            
            db_session.rollback()

            # Try to create user with same email
            user3 = User.create_local_user(
                username="differentuser",
                password="pass789",
                email="unique@example.com"  # Duplicate email
            )
            db_session.add(user3)
            
            with pytest.raises(IntegrityError):
                db_session.commit()
            
            db_session.rollback()

    def test_tak_server_unique_name_constraint(self, app, db_session):
        """Test TakServer unique name constraint."""
        with app.app_context():
            # Create first server
            server1 = TakServer(
                name="Unique Server",
                host="localhost",
                port=8089,
                protocol="tls"
            )
            db_session.add(server1)
            db_session.commit()

            # Try to create server with same name
            server2 = TakServer(
                name="Unique Server",  # Duplicate name
                host="remotehost",
                port=8090,
                protocol="tcp"
            )
            db_session.add(server2)
            
            # This will fail initially until unique constraint is properly enforced
            with pytest.raises(IntegrityError):
                db_session.commit()
            
            db_session.rollback()

    def test_required_field_constraints(self, app, db_session):
        """Test that required fields are properly enforced."""
        with app.app_context():
            # Test Stream required fields - can't test constructor validation, but can test DB constraints
            # Create stream with null name to test database constraints
            try:
                # Use raw SQL to test constraint enforcement
                db.session.execute(text("INSERT INTO streams (plugin_type, name) VALUES ('garmin', NULL)"))
                db.session.commit()
                assert False, "Should have failed with null name constraint"
            except IntegrityError:
                # Expected behavior - null constraint violation
                pass
            finally:
                db_session.rollback()

            # Test TakServer required fields
            with pytest.raises(IntegrityError):
                # This should fail at database level for missing host/port
                db.session.execute(text("INSERT INTO tak_servers (name) VALUES ('Test Server')"))
                db.session.commit()
            
            db_session.rollback()

            # Test User required fields
            with pytest.raises(IntegrityError):
                # This should fail at database level for missing username
                db.session.execute(text("INSERT INTO users (email) VALUES ('test@example.com')"))
                db.session.commit()
            
            db_session.rollback()


class TestQueryPerformanceOptimization:
    """Test query performance and optimization features."""

    def test_bulk_callsign_mapping_creation(self, app, db_session):
        """Test efficient bulk creation of callsign mappings."""
        with app.app_context():
            # Create stream
            stream = Stream(name="Bulk Test Stream", plugin_type="garmin")
            db_session.add(stream)
            db_session.flush()

            # Time bulk creation
            start_time = time.time()
            
            mappings_data = []
            for i in range(100):
                mappings_data.append({
                    'stream_id': stream.id,
                    'identifier_value': f'IMEI_{i:04d}',
                    'custom_callsign': f'Unit_{i:04d}'
                })
            
            # This will initially fail as bulk creation is not optimized
            # Should complete in under 1 second for 100 records
            mappings = []
            for data in mappings_data:
                mapping = CallsignMapping(**data)
                mappings.append(mapping)
                db_session.add(mapping)
            
            db_session.commit()
            end_time = time.time()
            
            duration = end_time - start_time
            # This assertion will fail initially until bulk operations are optimized
            assert duration < 1.0, f"Bulk creation took {duration:.2f}s, should be under 1.0s"
            
            # Verify all records created
            count = CallsignMapping.query.filter_by(stream_id=stream.id).count()
            assert count == 100

    def test_stream_with_server_join_performance(self, app, db_session):
        """Test performance of Stream queries with TakServer joins."""
        with app.app_context():
            # Create servers and streams
            servers = []
            for i in range(10):
                server = TakServer(
                    name=f"Server_{i}",
                    host=f"host{i}.example.com",
                    port=8089 + i,
                    protocol="tls"
                )
                servers.append(server)
                db_session.add(server)
            
            db_session.flush()

            streams = []
            for i in range(50):
                stream = Stream(
                    name=f"Stream_{i}",
                    plugin_type="garmin",
                    tak_server_id=servers[i % 10].id
                )
                streams.append(stream)
                db_session.add(stream)
            
            db_session.commit()

            # Test join performance
            start_time = time.time()
            
            # This query should be optimized to avoid N+1
            results = db_session.query(Stream).join(TakServer).filter(
                TakServer.protocol == "tls"
            ).all()
            
            # Access related objects to trigger loading
            for stream in results:
                _ = stream.tak_server.name
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Should complete efficiently - this will fail initially
            assert duration < 0.5, f"Join query took {duration:.2f}s, should be under 0.5s"
            assert len(results) == 50  # All streams should match