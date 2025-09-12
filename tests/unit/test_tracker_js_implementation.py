"""
ABOUTME: Implementation verification tests for Phase 3 JavaScript functionality
ABOUTME: Tests actual working JavaScript functions in the tracker enable/disable UI

This test module verifies that the Phase 3 implementation actually works
by testing the JavaScript functions and UI behavior that have been implemented.
This runs after the TDD tests to verify the implementation is correct.

Author: TrakBridge Implementation Team  
Created: 2025-12-13 (Phase 3 Implementation Verification)
"""

import pytest
import os
from pathlib import Path


class TestJavaScriptImplementation:
    """Test that JavaScript functions are properly implemented in templates"""
    
    def test_create_template_has_enabled_column_header(self):
        """Verify create_stream.html has Enabled column header"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Enabled column header
        assert '<th>Enabled</th>' in content, "Enabled column header missing from create template"
        
        # Check table structure has correct order
        header_section = content[content.find('<thead>'):content.find('</thead>')]
        enabled_pos = header_section.find('<th>Enabled</th>')
        identifier_pos = header_section.find('<th>Identifier</th>')
        
        assert enabled_pos < identifier_pos, "Enabled column should come before Identifier column"

    def test_edit_template_has_enabled_column_header(self):
        """Verify edit_stream.html has Enabled column header"""  
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Enabled column header
        assert '<th>Enabled</th>' in content, "Enabled column header missing from edit template"
        
        # Check table structure has correct order
        header_section = content[content.find('<thead>'):content.find('</thead>')]
        enabled_pos = header_section.find('<th>Enabled</th>')
        identifier_pos = header_section.find('<th>Identifier</th>')
        
        assert enabled_pos < identifier_pos, "Enabled column should come before Identifier column"

    def test_bulk_operation_buttons_exist_create(self):
        """Verify create template has bulk enable/disable buttons"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Enable All button
        assert 'bulkEnableTrackers(true)' in content, "Enable All button missing"
        assert 'Enable All' in content, "Enable All button text missing"
        
        # Check for Disable All button  
        assert 'bulkEnableTrackers(false)' in content, "Disable All button missing"
        assert 'Disable All' in content, "Disable All button text missing"

    def test_bulk_operation_buttons_exist_edit(self):
        """Verify edit template has bulk enable/disable buttons"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Enable All button
        assert 'bulkEnableTrackers(true)' in content, "Enable All button missing"
        assert 'Enable All' in content, "Enable All button text missing"
        
        # Check for Disable All button
        assert 'bulkEnableTrackers(false)' in content, "Disable All button missing"
        assert 'Disable All' in content, "Disable All button text missing"

    def test_toggle_tracker_enabled_function_exists_create(self):
        """Verify toggleTrackerEnabled function exists in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function toggleTrackerEnabled(checkbox, index)' in content, "toggleTrackerEnabled function missing"
        
        # Check function body contains expected logic
        assert 'callsignInput.readOnly = false' in content, "Enable logic missing"
        assert 'callsignInput.readOnly = true' in content, "Disable logic missing"
        assert 'row.style.opacity' in content, "Visual feedback missing"

    def test_toggle_tracker_enabled_function_exists_edit(self):
        """Verify toggleTrackerEnabled function exists in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function toggleTrackerEnabled(checkbox, index)' in content, "toggleTrackerEnabled function missing"
        
        # Check function body contains expected logic
        assert 'callsignInput.readOnly = false' in content, "Enable logic missing" 
        assert 'callsignInput.readOnly = true' in content, "Disable logic missing"
        assert 'row.style.opacity' in content, "Visual feedback missing"

    def test_bulk_enable_trackers_function_exists_create(self):
        """Verify bulkEnableTrackers function exists in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function bulkEnableTrackers(enabled)' in content, "bulkEnableTrackers function missing"
        
        # Check function logic
        assert 'querySelectorAll(\'input[name*="_enabled"]\')' in content, "Checkbox selection missing"
        assert 'checkbox.onchange()' in content, "Change trigger missing"
        assert 'showAlert(' in content, "Feedback alert missing"

    def test_bulk_enable_trackers_function_exists_edit(self):
        """Verify bulkEnableTrackers function exists in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function bulkEnableTrackers(enabled)' in content, "bulkEnableTrackers function missing"
        
        # Check function logic
        assert 'querySelectorAll(\'input[name*="_enabled"]\')' in content, "Checkbox selection missing"
        assert 'checkbox.onchange()' in content, "Change trigger missing"
        assert 'showAlert(' in content, "Feedback alert missing"

    def test_get_tracker_form_data_function_exists_create(self):
        """Verify getTrackerFormData function exists in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function getTrackerFormData()' in content, "getTrackerFormData function missing"
        
        # Check return structure
        assert 'tracker_mappings:' in content, "tracker_mappings property missing"
        assert 'total_trackers:' in content, "total_trackers property missing"
        assert 'enabled_trackers:' in content, "enabled_trackers property missing"
        assert 'enabled: checkbox.checked' in content, "enabled status missing"

    def test_get_tracker_form_data_function_exists_edit(self):
        """Verify getTrackerFormData function exists in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check function definition
        assert 'function getTrackerFormData()' in content, "getTrackerFormData function missing"
        
        # Check return structure
        assert 'tracker_mappings:' in content, "tracker_mappings property missing"
        assert 'total_trackers:' in content, "total_trackers property missing" 
        assert 'enabled_trackers:' in content, "enabled_trackers property missing"
        assert 'enabled: checkbox.checked' in content, "enabled status missing"

    def test_checkbox_elements_in_table_row_create(self):
        """Verify checkbox elements are properly structured in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check checkbox structure in populateTrackerMappingTable
        populate_func = content[content.find('function populateTrackerMappingTable'):content.find('function extractIdentifierValue')]
        
        assert 'type="checkbox"' in populate_func, "Checkbox input missing"
        assert 'tracker_enabled_${index}' in populate_func, "Checkbox ID missing"
        assert 'callsign_mapping_${index}_enabled' in populate_func, "Checkbox name missing"
        assert 'onchange="toggleTrackerEnabled(this, ${index})"' in populate_func, "Change handler missing"
        assert 'checked' in populate_func, "Default checked state missing"

    def test_checkbox_elements_in_table_row_edit(self):
        """Verify checkbox elements are properly structured in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check checkbox structure in populateTrackerMappingTableWithExisting
        start_pos = content.find('function populateTrackerMappingTableWithExisting')
        # Find the end of the function by looking for the next function or script end
        end_search_start = start_pos + 100  # Skip past the function name
        end_pos = content.find('function ', end_search_start)
        if end_pos == -1:
            end_pos = content.find('</script>', start_pos)
        populate_func = content[start_pos:end_pos]
        
        assert 'type="checkbox"' in populate_func, "Checkbox input missing"
        assert 'tracker_enabled_${index}' in populate_func, "Checkbox ID missing"
        assert 'callsign_mapping_${index}_enabled' in populate_func, "Checkbox name missing"
        assert 'onchange="toggleTrackerEnabled(this, ${index})"' in populate_func, "Change handler missing"
        assert '${enabled ? \'checked\' : \'\'}' in populate_func, "Conditional checked state missing"

    def test_input_field_ids_for_interaction_create(self):
        """Verify input fields have proper IDs for JavaScript interaction in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that input fields have IDs for JavaScript manipulation
        populate_func = content[content.find('function populateTrackerMappingTable'):content.find('function extractIdentifierValue')]
        
        assert 'id="callsign_input_${index}"' in populate_func, "Callsign input ID missing"
        assert 'id="cot_type_${index}"' in populate_func, "CoT type select ID missing"

    def test_input_field_ids_for_interaction_edit(self):
        """Verify input fields have proper IDs for JavaScript interaction in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that input fields have IDs for JavaScript manipulation
        start_pos = content.find('function populateTrackerMappingTableWithExisting')
        # Find the end of the function by looking for the next function or script end
        end_search_start = start_pos + 100  # Skip past the function name
        end_pos = content.find('function ', end_search_start)
        if end_pos == -1:
            end_pos = content.find('</script>', start_pos)
        populate_func = content[start_pos:end_pos]
        
        assert 'id="callsign_input_${index}"' in populate_func, "Callsign input ID missing"
        assert 'id="cot_type_${index}"' in populate_func, "CoT type select ID missing"

    def test_state_persistence_functionality_create(self):
        """Verify state persistence function exists in create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for state persistence function
        assert 'function populateTrackerMappingTableWithState' in content, "State persistence function missing"
        assert 'currentState[identifierInput.value]' in content, "State storage logic missing"
        assert 'toggleTrackerEnabled(checkbox, index)' in content, "State application missing"

    def test_state_persistence_functionality_edit(self):
        """Verify state persistence function exists in edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for state persistence function
        assert 'function populateTrackerMappingTableWithExistingAndState' in content, "State persistence function missing"
        assert 'currentState[identifierInput.value]' in content, "State storage logic missing"
        assert 'toggleTrackerEnabled(checkbox, index)' in content, "State application missing"


class TestTemplateStructureValidation:
    """Validate overall template structure for Phase 3 implementation"""
    
    def test_create_template_has_phase_3_functionality(self):
        """Verify create template has Phase 3 functionality markers"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Phase 3 implementation markers
        assert 'Phase 3: Tracker Enable/Disable Functionality' in content, "Phase 3 marker missing"
        assert 'toggleTrackerEnabled' in content, "Core functionality missing"

    def test_edit_template_has_phase_3_functionality(self):
        """Verify edit template has Phase 3 functionality markers"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for Phase 3 implementation markers
        assert 'Phase 3: Tracker Enable/Disable Functionality' in content, "Phase 3 marker missing"
        assert 'toggleTrackerEnabled' in content, "Core functionality missing"

    def test_javascript_syntax_basic_validation_create(self):
        """Basic JavaScript syntax validation for create template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract JavaScript section
        script_start = content.find('<script>')
        script_end = content.find('</script>', script_start)
        js_content = content[script_start:script_end]
        
        # Basic syntax checks
        assert js_content.count('{') == js_content.count('}'), "Mismatched JavaScript braces"
        assert js_content.count('(') == js_content.count(')'), "Mismatched JavaScript parentheses"

    def test_javascript_syntax_basic_validation_edit(self):
        """Basic JavaScript syntax validation for edit template"""
        template_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract JavaScript section
        script_start = content.find('<script>')
        script_end = content.find('</script>', script_start)
        js_content = content[script_start:script_end]
        
        # Basic syntax checks
        assert js_content.count('{') == js_content.count('}'), "Mismatched JavaScript braces"
        assert js_content.count('(') == js_content.count(')'), "Mismatched JavaScript parentheses"

    def test_required_css_classes_and_styling(self):
        """Verify required CSS classes are referenced in JavaScript"""
        create_path = Path(__file__).parent.parent.parent / "templates" / "create_stream.html"
        edit_path = Path(__file__).parent.parent.parent / "templates" / "edit_stream.html"
        
        for template_path in [create_path, edit_path]:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for CSS classes used in JavaScript
            assert 'text-muted' in content, f"text-muted class missing in {template_path.name}"
            assert 'table-secondary' in content, f"table-secondary class missing in {template_path.name}"
            assert 'form-check' in content, f"form-check class missing in {template_path.name}"
            assert 'form-check-input' in content, f"form-check-input class missing in {template_path.name}"