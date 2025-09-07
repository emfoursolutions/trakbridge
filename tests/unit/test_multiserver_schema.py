"""
ABOUTME: Unit tests for multi-server database schema relationships in Phase 2A  
ABOUTME: Tests follow TDD principles - all tests initially FAIL until schema is implemented
"""

import pytest
import sys
import os
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from database import db
from models.stream import Stream
from models.tak_server import TakServer


class TestMultiServerSchema:
    """
    Phase 2A: Multi-Server Database Schema Tests
    All tests should FAIL initially until many-to-many relationships are implemented
    """
    
    @pytest.fixture
    def app_context(self):
        """Set up Flask application context for database operations"""
        from app import create_app
        app = create_app()
        
        with app.app_context():
            # Create all tables for testing
            db.create_all()
            yield app
            # Clean up after test
            db.session.rollback()
            db.drop_all()
    
    @pytest.fixture
    def sample_tak_servers(self, app_context):
        """Create sample TAK servers for testing"""
        servers = [
            TakServer(
                name="Primary TAK Server",
                host="tak1.example.com",
                port=8089,
                protocol="tls"
            ),
            TakServer(
                name="Backup TAK Server", 
                host="tak2.example.com",
                port=8089,
                protocol="tls"
            ),
            TakServer(
                name="Training TAK Server",
                host="tak-training.example.com", 
                port=8088,
                protocol="tcp"
            )
        ]
        
        for server in servers:
            db.session.add(server)
        db.session.commit()
        
        return servers
    
    @pytest.fixture
    def sample_stream(self, app_context, sample_tak_servers):
        """Create sample stream for testing"""
        stream = Stream(
            name="Test Stream",
            plugin_type="garmin",
            poll_interval=120,
            cot_type="a-f-G-U-C",
            cot_stale_time=300,
            tak_server_id=sample_tak_servers[0].id  # Legacy single server relationship
        )
        db.session.add(stream)
        db.session.commit()
        
        return stream

    def test_stream_can_have_multiple_tak_servers(self, app_context, sample_tak_servers, sample_stream):
        """
        Test that a stream can be associated with multiple TAK servers
        REQUIREMENT: Many-to-many relationship between streams and TAK servers
        STATUS: WILL FAIL - many-to-many relationship doesn't exist
        """
        # Attempt to associate stream with multiple servers
        # This should work with the new schema
        
        # Check that stream has tak_servers relationship (many-to-many)
        assert hasattr(sample_stream, 'tak_servers'), "Stream should have tak_servers relationship"
        
        # Add multiple servers to the stream
        sample_stream.tak_servers.append(sample_tak_servers[0])  # Primary
        sample_stream.tak_servers.append(sample_tak_servers[1])  # Backup
        sample_stream.tak_servers.append(sample_tak_servers[2])  # Training
        db.session.commit()
        
        # Verify the stream is associated with all three servers
        assert len(sample_stream.tak_servers) == 3, "Stream should be associated with 3 TAK servers"
        
        # Verify specific servers are present
        server_names = [server.name for server in sample_stream.tak_servers]
        assert "Primary TAK Server" in server_names
        assert "Backup TAK Server" in server_names 
        assert "Training TAK Server" in server_names

    def test_tak_server_can_have_multiple_streams(self, app_context, sample_tak_servers):
        """
        Test that a TAK server can be associated with multiple streams
        REQUIREMENT: Reverse many-to-many relationship
        STATUS: WILL FAIL - reverse relationship doesn't exist
        """
        # Create multiple streams
        streams = [
            Stream(name="Stream 1", plugin_type="garmin", tak_server_id=sample_tak_servers[0].id),
            Stream(name="Stream 2", plugin_type="spot", tak_server_id=sample_tak_servers[0].id),
            Stream(name="Stream 3", plugin_type="traccar", tak_server_id=sample_tak_servers[0].id)
        ]
        
        for stream in streams:
            db.session.add(stream)
        db.session.commit()
        
        # Use new many-to-many relationship to associate streams with server
        server = sample_tak_servers[0]
        
        # Check that TAK server has streams_many relationship
        assert hasattr(server, 'streams_many'), "TakServer should have streams_many relationship"
        
        # Add streams to server via many-to-many relationship
        for stream in streams:
            server.streams_many.append(stream)
        db.session.commit()
        
        # Verify server is associated with all streams
        assert server.streams_many.count() == 3, "TAK server should be associated with 3 streams"
        
        # Verify specific streams are present
        stream_names = [stream.name for stream in server.streams_many]
        assert "Stream 1" in stream_names
        assert "Stream 2" in stream_names
        assert "Stream 3" in stream_names

    def test_junction_table_exists_and_has_correct_structure(self, app_context):
        """
        Test that the stream_tak_servers junction table exists with proper structure
        STATUS: WILL FAIL - junction table doesn't exist yet
        """
        # Check if junction table exists in database metadata
        from sqlalchemy import inspect
        
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        
        assert 'stream_tak_servers' in tables, "Junction table 'stream_tak_servers' should exist"
        
        # Check junction table structure
        columns = inspector.get_columns('stream_tak_servers')
        column_names = [col['name'] for col in columns]
        
        # Should have foreign keys to both tables
        assert 'stream_id' in column_names, "Junction table should have stream_id column"
        assert 'tak_server_id' in column_names, "Junction table should have tak_server_id column"
        
        # Check foreign key constraints
        foreign_keys = inspector.get_foreign_keys('stream_tak_servers')
        fk_tables = [fk['referred_table'] for fk in foreign_keys]
        
        assert 'streams' in fk_tables, "Junction table should have FK to streams table"
        assert 'tak_servers' in fk_tables, "Junction table should have FK to tak_servers table"

    def test_backward_compatibility_maintained(self, app_context, sample_tak_servers):
        """
        Test that existing single-server relationships continue to work
        REQUIREMENT: Zero impact on existing functionality during Phase 2A
        STATUS: WILL FAIL - need to ensure old relationships still work
        """
        # Create stream using legacy single-server relationship
        stream = Stream(
            name="Legacy Stream",
            plugin_type="garmin",
            tak_server_id=sample_tak_servers[0].id  # Old single-server FK
        )
        db.session.add(stream)
        db.session.commit()
        
        # Legacy relationship should still work
        assert stream.tak_server is not None, "Legacy tak_server relationship should still work"
        assert stream.tak_server.name == "Primary TAK Server"
        assert stream.tak_server_id == sample_tak_servers[0].id
        
        # Legacy reverse relationship should still work
        server = sample_tak_servers[0]
        assert len(server.streams) >= 1, "Legacy streams relationship should still work"
        legacy_stream_names = [s.name for s in server.streams]
        assert "Legacy Stream" in legacy_stream_names

    def test_migration_preserves_existing_data(self, app_context, sample_tak_servers):
        """
        Test that existing stream-to-server relationships are preserved during migration
        REQUIREMENT: Migration safety - no data loss
        STATUS: WILL FAIL - migration logic doesn't exist
        """
        # Create stream with legacy relationship first
        stream = Stream(
            name="Pre-Migration Stream",
            plugin_type="garmin", 
            tak_server_id=sample_tak_servers[0].id
        )
        db.session.add(stream)
        db.session.commit()
        
        original_server_id = stream.tak_server_id
        
        # After migration, the stream should:
        # 1. Still have the legacy relationship intact
        assert stream.tak_server_id == original_server_id, "Legacy tak_server_id should be preserved"
        assert stream.tak_server is not None, "Legacy tak_server relationship should work"
        
        # 2. Also be available via new many-to-many relationship  
        # (This will be populated by migration script)
        assert hasattr(stream, 'tak_servers'), "New tak_servers relationship should exist"

    def test_cascade_behavior_for_multi_server_relationships(self, app_context, sample_tak_servers):
        """
        Test cascade behavior when deleting streams or servers with many-to-many relationships
        STATUS: WILL FAIL - cascade behavior not configured
        """
        # Create stream associated with multiple servers
        stream = Stream(name="Multi-Server Stream", plugin_type="garmin")
        db.session.add(stream)
        db.session.commit()
        
        # Associate with multiple servers
        stream.tak_servers.append(sample_tak_servers[0])
        stream.tak_servers.append(sample_tak_servers[1]) 
        db.session.commit()
        
        stream_id = stream.id
        
        # Delete the stream
        db.session.delete(stream)
        db.session.commit()
        
        # Junction table entries should be cleaned up
        # Check that no orphaned junction table entries exist
        result = db.session.execute(
            db.text("SELECT COUNT(*) FROM stream_tak_servers WHERE stream_id = :stream_id"),
            {"stream_id": stream_id}
        ).scalar()
        
        assert result == 0, "Junction table entries should be deleted when stream is deleted"
        
        # TAK servers should still exist (no cascade delete to servers)
        remaining_servers = db.session.query(TakServer).count()
        assert remaining_servers == 3, "TAK servers should not be deleted when stream is deleted"

    def test_unique_constraints_on_junction_table(self, app_context, sample_tak_servers, sample_stream):
        """
        Test that junction table prevents duplicate stream-server associations
        STATUS: WILL FAIL - unique constraints not configured
        """
        # Associate stream with a server
        sample_stream.tak_servers.append(sample_tak_servers[0])
        db.session.commit()
        
        # Attempting to add the same association should not create duplicates
        sample_stream.tak_servers.append(sample_tak_servers[0])
        
        # This should either prevent the duplicate or handle it gracefully
        try:
            db.session.commit()
            # If commit succeeds, verify no duplicates exist
            associations = db.session.execute(
                db.text("""
                    SELECT COUNT(*) FROM stream_tak_servers 
                    WHERE stream_id = :stream_id AND tak_server_id = :server_id
                """),
                {"stream_id": sample_stream.id, "server_id": sample_tak_servers[0].id}
            ).scalar()
            
            assert associations == 1, "Should not create duplicate stream-server associations"
            
        except Exception:
            # If commit fails due to unique constraint, that's also acceptable
            db.session.rollback()
            # Verify the original association still exists
            sample_stream = db.session.query(Stream).get(sample_stream.id)
            assert len(sample_stream.tak_servers) == 1, "Original association should be preserved"

    def test_query_performance_with_many_to_many(self, app_context, sample_tak_servers):
        """
        Test that queries work efficiently with many-to-many relationships
        STATUS: WILL FAIL - relationships and indexes don't exist
        """
        # Create multiple streams with various server associations
        streams_data = [
            ("Stream A", ["Primary TAK Server", "Backup TAK Server"]),
            ("Stream B", ["Primary TAK Server"]),
            ("Stream C", ["Backup TAK Server", "Training TAK Server"]),
            ("Stream D", ["Primary TAK Server", "Backup TAK Server", "Training TAK Server"])
        ]
        
        created_streams = []
        for stream_name, server_names in streams_data:
            stream = Stream(name=stream_name, plugin_type="garmin")
            db.session.add(stream)
            db.session.flush()  # Get ID without committing
            
            # Associate with specified servers
            for server_name in server_names:
                server = next(s for s in sample_tak_servers if s.name == server_name)
                stream.tak_servers.append(server)
            
            created_streams.append(stream)
        
        db.session.commit()
        
        # Test efficient querying: Find all streams using "Primary TAK Server"
        primary_server = next(s for s in sample_tak_servers if s.name == "Primary TAK Server")
        
        streams_using_primary = db.session.query(Stream).join(
            Stream.tak_servers
        ).filter(TakServer.name == "Primary TAK Server").all()
        
        assert len(streams_using_primary) == 3, "Should find 3 streams using Primary TAK Server"
        
        stream_names = [s.name for s in streams_using_primary]
        assert "Stream A" in stream_names
        assert "Stream B" in stream_names  
        assert "Stream D" in stream_names

    def test_database_indexes_for_junction_table(self, app_context):
        """
        Test that proper indexes exist on junction table for performance
        STATUS: WILL FAIL - indexes don't exist yet
        """
        from sqlalchemy import inspect
        
        inspector = inspect(db.engine)
        indexes = inspector.get_indexes('stream_tak_servers')
        
        # Should have indexes on foreign key columns for query performance
        index_columns = []
        for index in indexes:
            index_columns.extend(index['column_names'])
        
        assert 'stream_id' in index_columns, "Junction table should have index on stream_id"
        assert 'tak_server_id' in index_columns, "Junction table should have index on tak_server_id"


if __name__ == "__main__":
    # Run tests to verify they all FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])