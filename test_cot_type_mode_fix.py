#!/usr/bin/env python3
"""
Quick test script to verify the CoT Type Mode fix
Tests that cot_type_mode is properly persisted during stream creation
"""

import sys
import os
sys.path.append('.')

# Set up test environment
os.environ['TESTING'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from database import db
from models.stream import Stream
from app import create_app

def test_cot_type_mode_fix():
    """Test that cot_type_mode is properly set during stream creation"""
    
    # Create test app with in-memory database
    app = create_app('testing')
    
    with app.app_context():
        # Create tables
        db.create_all()
        
        # Test 1: Create stream with per_point mode
        print("Test 1: Creating stream with cot_type_mode='per_point'")
        stream = Stream(
            name="Test Stream",
            plugin_type="deepstate",
            cot_type_mode="per_point"
        )
        
        db.session.add(stream)
        db.session.commit()
        
        # Verify the field was set correctly
        assert stream.cot_type_mode == "per_point", f"Expected 'per_point', got '{stream.cot_type_mode}'"
        print(f"✅ Stream created with cot_type_mode: {stream.cot_type_mode}")
        
        # Test 2: Query from database to ensure persistence
        print("\nTest 2: Querying stream from database")
        retrieved_stream = Stream.query.filter_by(name="Test Stream").first()
        assert retrieved_stream is not None, "Stream not found in database"
        assert retrieved_stream.cot_type_mode == "per_point", f"Database value incorrect: {retrieved_stream.cot_type_mode}"
        print(f"✅ Database query returned cot_type_mode: {retrieved_stream.cot_type_mode}")
        
        # Test 3: Default value
        print("\nTest 3: Testing default value")
        default_stream = Stream(
            name="Default Stream",
            plugin_type="deepstate"
            # No cot_type_mode specified - should use default
        )
        
        db.session.add(default_stream)
        db.session.commit()
        
        assert default_stream.cot_type_mode == "stream", f"Expected default 'stream', got '{default_stream.cot_type_mode}'"
        print(f"✅ Default stream created with cot_type_mode: {default_stream.cot_type_mode}")
        
        # Test 4: Stream mode
        print("\nTest 4: Creating stream with cot_type_mode='stream'")
        stream_mode = Stream(
            name="Stream Mode Test",
            plugin_type="deepstate",
            cot_type_mode="stream"
        )
        
        db.session.add(stream_mode)
        db.session.commit()
        
        assert stream_mode.cot_type_mode == "stream", f"Expected 'stream', got '{stream_mode.cot_type_mode}'"
        print(f"✅ Stream created with cot_type_mode: {stream_mode.cot_type_mode}")
        
        print("\n🎉 All tests passed! CoT Type Mode fix is working correctly.")
        
        # Show summary
        all_streams = Stream.query.all()
        print(f"\nSummary: Created {len(all_streams)} streams:")
        for s in all_streams:
            print(f"  - '{s.name}': cot_type_mode='{s.cot_type_mode}'")

if __name__ == "__main__":
    test_cot_type_mode_fix()