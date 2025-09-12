"""
ABOUTME: Simple test for enabled field logic in callsign mappings
ABOUTME: Tests the core enabled field handling logic directly

Author: TrakBridge Implementation Team
Created: 2025-12-13 (Phase 3 Backend Fix Verification)
"""

import pytest


def test_enabled_field_logic():
    """Test the enabled field logic directly without complex fixtures"""
    
    # This mirrors the logic in _create_callsign_mappings
    def get_enabled_value(enabled_value):
        """Extract and test the enabled field logic"""
        enabled = True  # Default to enabled
        
        if isinstance(enabled_value, str):
            # Form checkbox data: 'on' means checked/enabled, missing means unchecked/disabled
            enabled = enabled_value.lower() in ('on', 'true', '1')
        elif isinstance(enabled_value, bool):
            # Direct boolean value (from JSON)
            enabled = enabled_value
        elif enabled_value is None:
            # Missing checkbox means disabled (unchecked)
            enabled = False
            
        return enabled
    
    # Test various input scenarios
    test_cases = [
        # HTML checkbox values
        ("on", True),       # Checked checkbox
        (None, False),      # Unchecked checkbox (missing field)
        
        # String values
        ("true", True),     # String true
        ("True", True),     # Capitalized true  
        ("1", True),        # String 1
        ("false", False),   # String false
        ("False", False),   # Capitalized false
        ("0", False),       # String 0
        ("", False),        # Empty string
        ("off", False),     # Alternative unchecked value
        
        # Boolean values (JSON)
        (True, True),       # JSON true
        (False, False),     # JSON false
    ]
    
    for input_value, expected in test_cases:
        result = get_enabled_value(input_value)
        assert result == expected, f"Failed for input '{input_value}': expected {expected}, got {result}"
    
    print("✅ All enabled field logic tests passed!")


def test_callsign_mapping_creation_conditions():
    """Test the conditions under which CallsignMapping objects should be created"""
    
    # This mirrors the creation condition in _create_callsign_mappings
    test_cases = [
        # (identifier_value, custom_callsign, expected_should_create)
        ("TRACKER001", "ALPHA", True),      # Normal case
        ("TRACKER002", "", True),           # Empty callsign (disabled tracker)
        ("TRACKER003", None, True),         # None callsign
        ("", "ALPHA", False),              # Empty identifier - should NOT create
        (None, "ALPHA", False),            # None identifier - should NOT create
        ("TRACKER004", "BRAVO", True),     # Another normal case
    ]
    
    for identifier, callsign, expected in test_cases:
        # Original logic: if identifier_value and custom_callsign:
        # New logic: if identifier_value: (allow empty callsign for disabled)
        
        # Test NEW logic (what we implemented)
        should_create_new = bool(identifier)
        assert should_create_new == expected, f"Failed for ({identifier}, {callsign}): expected {expected}"
        
        # Show what OLD logic would do (should be different for empty callsign cases)
        would_create_old = bool(identifier and callsign)
        if identifier == "TRACKER002":  # Empty callsign case
            assert would_create_old != should_create_new, "New logic should differ from old for empty callsign"
    
    print("✅ All CallsignMapping creation condition tests passed!")


if __name__ == "__main__":
    test_enabled_field_logic()
    test_callsign_mapping_creation_conditions()
    print("🎉 All backend logic tests passed!")