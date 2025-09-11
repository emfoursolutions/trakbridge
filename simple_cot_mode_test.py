#!/usr/bin/env python3
"""
Simple test to verify the CoT Type Mode constructor fix
Tests that the Stream.__init__ method accepts and sets cot_type_mode
"""

import sys
import os
sys.path.append('.')

# Import just the model without Flask app context
from models.stream import Stream

def test_constructor_fix():
    """Test that Stream.__init__ properly accepts cot_type_mode parameter"""
    
    print("Testing Stream constructor fix for cot_type_mode...")
    
    # Test 1: Create stream with per_point mode
    print("\nTest 1: Creating stream with cot_type_mode='per_point'")
    try:
        stream = Stream(
            name="Test Stream",
            plugin_type="deepstate",
            cot_type_mode="per_point"
        )
        
        assert hasattr(stream, 'cot_type_mode'), "Stream object missing cot_type_mode attribute"
        assert stream.cot_type_mode == "per_point", f"Expected 'per_point', got '{stream.cot_type_mode}'"
        print(f"SUCCESS: Stream created with cot_type_mode: {stream.cot_type_mode}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False
    
    # Test 2: Default value
    print("\nTest 2: Testing default value")
    try:
        default_stream = Stream(
            name="Default Stream",
            plugin_type="deepstate"
            # No cot_type_mode specified - should use default "stream"
        )
        
        assert hasattr(default_stream, 'cot_type_mode'), "Stream object missing cot_type_mode attribute"
        assert default_stream.cot_type_mode == "stream", f"Expected default 'stream', got '{default_stream.cot_type_mode}'"
        print(f"SUCCESS: Default stream created with cot_type_mode: {default_stream.cot_type_mode}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False
    
    # Test 3: Stream mode explicitly set
    print("\nTest 3: Creating stream with cot_type_mode='stream'")
    try:
        stream_mode = Stream(
            name="Stream Mode Test",
            plugin_type="deepstate",
            cot_type_mode="stream"
        )
        
        assert hasattr(stream_mode, 'cot_type_mode'), "Stream object missing cot_type_mode attribute"
        assert stream_mode.cot_type_mode == "stream", f"Expected 'stream', got '{stream_mode.cot_type_mode}'"
        print(f"SUCCESS: Stream created with cot_type_mode: {stream_mode.cot_type_mode}")
    except Exception as e:
        print(f"❌ FAILED: {e}")
        return False
    
    # Test 4: Verify all other existing parameters still work
    print("\nTest 4: Testing all constructor parameters work")
    try:
        full_stream = Stream(
            name="Full Test Stream",
            plugin_type="deepstate",
            poll_interval=300,
            cot_type="a-h-G",
            cot_stale_time=600,
            tak_server_id=1,
            cot_type_mode="per_point",
            enable_callsign_mapping=True,
            callsign_identifier_field="test_field",
            callsign_error_handling="skip",
            enable_per_callsign_cot_types=True
        )
        
        # Verify all fields are set correctly
        assert full_stream.name == "Full Test Stream"
        assert full_stream.plugin_type == "deepstate"
        assert full_stream.poll_interval == 300
        assert full_stream.cot_type == "a-h-G"
        assert full_stream.cot_stale_time == 600
        assert full_stream.tak_server_id == 1
        assert full_stream.cot_type_mode == "per_point"
        assert full_stream.enable_callsign_mapping == True
        assert full_stream.callsign_identifier_field == "test_field"
        assert full_stream.callsign_error_handling == "skip"
        assert full_stream.enable_per_callsign_cot_types == True
        
        print("SUCCESS: All constructor parameters working correctly")
    except Exception as e:
        print(f"FAILED: {e}")
        return False
    
    print("\nALL TESTS PASSED!")
    print("The CoT Type Mode constructor fix is working correctly.")
    print("The Stream model now properly accepts and sets the cot_type_mode parameter.")
    
    return True

if __name__ == "__main__":
    success = test_constructor_fix()
    sys.exit(0 if success else 1)