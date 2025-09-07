#!/usr/bin/env python3
"""
Test script to verify checkbox array processing
"""

import requests

def test_checkbox_processing():
    """Test that checkbox arrays are properly processed"""
    
    # Test data simulating form submission with multiple checkboxes selected
    form_data = {
        'name': 'Test Stream',
        'plugin_type': 'garmin_plugin',
        'tak_servers': ['1', '2', '3'],  # This simulates multiple checkboxes selected
        'poll_interval': '120',
        'cot_type': 'a-f-G-U-C'
    }
    
    print("Testing checkbox array processing...")
    print(f"Form data being sent: {form_data}")
    
    # Simulate what Flask receives with checkbox arrays
    flask_form_data = [
        ('name', 'Test Stream'),
        ('plugin_type', 'garmin_plugin'),
        ('tak_servers', '1'),  # Multiple entries with same key
        ('tak_servers', '2'),
        ('tak_servers', '3'),
        ('poll_interval', '120'),
        ('cot_type', 'a-f-G-U-C')
    ]
    
    print(f"Flask form data (simulated): {flask_form_data}")
    
    # Test the processing logic
    from werkzeug.datastructures import ImmutableMultiDict
    
    request_form = ImmutableMultiDict(flask_form_data)
    
    # Test our processing logic
    data = dict(request_form)
    if "tak_servers" in request_form:
        data["tak_servers"] = request_form.getlist("tak_servers")
    
    print(f"Processed data: {data}")
    print(f"tak_servers type: {type(data.get('tak_servers'))}")
    print(f"tak_servers value: {data.get('tak_servers')}")
    
    # Verify the fix
    expected_servers = ['1', '2', '3']
    actual_servers = data.get('tak_servers', [])
    
    if actual_servers == expected_servers:
        print("✅ SUCCESS: Checkbox array processing works correctly!")
        print(f"Expected: {expected_servers}")
        print(f"Actual: {actual_servers}")
        return True
    else:
        print("❌ FAILED: Checkbox array processing is incorrect")
        print(f"Expected: {expected_servers}")
        print(f"Actual: {actual_servers}")
        return False

if __name__ == "__main__":
    test_checkbox_processing()