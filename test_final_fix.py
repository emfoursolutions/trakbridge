#!/usr/bin/env python3
"""
Test the final checkbox array fix
"""

from werkzeug.datastructures import ImmutableMultiDict

def test_final_checkbox_fix():
    """Test the exact fix that was applied"""
    
    # Simulate the exact form data from our HTML templates
    form_data = [
        ('name', 'Test Stream'),
        ('plugin_type', 'garmin_plugin'),
        ('tak_servers[]', '1'),  # HTML: name="tak_servers[]"
        ('tak_servers[]', '2'),  # Multiple checkboxes selected
        ('tak_servers[]', '3'),
        ('poll_interval', '120'),
        ('cot_type', 'a-f-G-U-C')
    ]
    
    print("=== Testing Final Checkbox Fix ===")
    request_form = ImmutableMultiDict(form_data)
    
    # Apply the exact logic from our fixed routes
    data = dict(request_form)
    if "tak_servers[]" in request_form:
        data["tak_servers"] = request_form.getlist("tak_servers[]")
    
    print(f"Raw form data: {list(request_form.items())}")
    print(f"Dict conversion: {dict(request_form)}")
    print(f"'tak_servers[]' in form: {'tak_servers[]' in request_form}")
    print(f"Final data['tak_servers']: {data.get('tak_servers')}")
    
    # Verify the fix works correctly
    expected = ['1', '2', '3']
    actual = data.get('tak_servers', [])
    
    if actual == expected:
        print("✅ SUCCESS: Multiple server selection fix is working!")
        print(f"✓ Expected: {expected}")
        print(f"✓ Received: {actual}")
        return True
    else:
        print("❌ FAILED: Fix is not working correctly")
        print(f"✗ Expected: {expected}")
        print(f"✗ Received: {actual}")
        return False

if __name__ == "__main__":
    test_final_checkbox_fix()