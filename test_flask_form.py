#!/usr/bin/env python3
"""
Test Flask form handling with checkbox arrays
"""

from werkzeug.datastructures import ImmutableMultiDict

def test_flask_form_handling():
    """Test how Flask handles checkbox arrays"""
    
    # Simulate form data with square brackets in name
    form_data_with_brackets = [
        ('name', 'Test Stream'),
        ('tak_servers[]', '1'),  # Note the [] in the name
        ('tak_servers[]', '2'),
        ('tak_servers[]', '3'),
    ]
    
    # Simulate form data without square brackets
    form_data_without_brackets = [
        ('name', 'Test Stream'),
        ('tak_servers', '1'),  # No [] in the name
        ('tak_servers', '2'),
        ('tak_servers', '3'),
    ]
    
    print("=== Testing Flask form handling ===")
    
    # Test with brackets
    print("\n1. Form data WITH square brackets:")
    request_form_brackets = ImmutableMultiDict(form_data_with_brackets)
    print(f"Raw form: {list(request_form_brackets.items())}")
    print(f"Dict form: {dict(request_form_brackets)}")
    print(f"'tak_servers[]' in form: {'tak_servers[]' in request_form_brackets}")
    print(f"'tak_servers' in form: {'tak_servers' in request_form_brackets}")
    if 'tak_servers[]' in request_form_brackets:
        print(f"getlist('tak_servers[]'): {request_form_brackets.getlist('tak_servers[]')}")
    if 'tak_servers' in request_form_brackets:
        print(f"getlist('tak_servers'): {request_form_brackets.getlist('tak_servers')}")
    
    # Test without brackets  
    print("\n2. Form data WITHOUT square brackets:")
    request_form_no_brackets = ImmutableMultiDict(form_data_without_brackets)
    print(f"Raw form: {list(request_form_no_brackets.items())}")
    print(f"Dict form: {dict(request_form_no_brackets)}")
    print(f"'tak_servers' in form: {'tak_servers' in request_form_no_brackets}")
    if 'tak_servers' in request_form_no_brackets:
        print(f"getlist('tak_servers'): {request_form_no_brackets.getlist('tak_servers')}")

if __name__ == "__main__":
    test_flask_form_handling()