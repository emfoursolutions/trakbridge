"""
ABOUTME: Test backend handling of enabled field in callsign mappings
ABOUTME: Verifies that disabled trackers are saved with enabled=False, not deleted

This test module verifies the backend fix for Phase 3 where disabled trackers
should be saved with enabled=False rather than being deleted from the database.

Author: TrakBridge Implementation Team
Created: 2025-12-13 (Phase 3 Backend Fix)
"""

import pytest
from unittest.mock import Mock, patch

from services.stream_operations_service import StreamOperationsService
from models.callsign_mapping import CallsignMapping


class TestCallsignEnabledBackend:
    """Test that backend correctly handles enabled field for callsign mappings"""

    @pytest.fixture
    def operations_service(self, app, db_session):
        """Create StreamOperationsService instance"""
        with app.app_context():
            from services.stream_manager import StreamManager
            from database import db
            mock_stream_manager = Mock(spec=StreamManager)
            mock_stream_manager.refresh_stream_tak_workers.return_value = True
            
            service = StreamOperationsService(mock_stream_manager, db)
            return service

    @pytest.fixture
    def mock_session(self):
        """Create mock database session"""
        session = Mock()
        return session

    @pytest.fixture
    def mock_stream(self):
        """Create mock stream object"""
        stream = Mock()
        stream.id = 1
        stream.enable_callsign_mapping = True
        return stream

    def test_create_callsign_mappings_handles_enabled_true(self, operations_service, mock_session, mock_stream):
        """Test that enabled trackers are saved with enabled=True"""
        # Form data with enabled tracker (checkbox checked)
        form_data = {
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "ALPHA",
            "callsign_mapping_0_enabled": "on",  # HTML checkbox checked value
            "callsign_mapping_0_cot_type": "a-f-G-U-C"
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        # Verify that CallsignMapping was created with enabled=True
        mock_session.add.assert_called_once()
        created_mapping = mock_session.add.call_args[0][0]
        
        assert isinstance(created_mapping, CallsignMapping)
        assert created_mapping.identifier_value == "TRACKER001"
        assert created_mapping.custom_callsign == "ALPHA"
        assert created_mapping.enabled is True
        assert created_mapping.cot_type == "a-f-G-U-C"

    def test_create_callsign_mappings_handles_enabled_false(self, operations_service, mock_session, mock_stream):
        """Test that disabled trackers are saved with enabled=False"""
        # Form data with disabled tracker (checkbox unchecked - field missing)
        form_data = {
            "callsign_mapping_0_identifier": "TRACKER002",
            "callsign_mapping_0_callsign": "BRAVO",
            # Note: no "callsign_mapping_0_enabled" key means checkbox was unchecked
            "callsign_mapping_0_cot_type": ""
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        # Verify that CallsignMapping was created with enabled=False
        mock_session.add.assert_called_once()
        created_mapping = mock_session.add.call_args[0][0]
        
        assert isinstance(created_mapping, CallsignMapping)
        assert created_mapping.identifier_value == "TRACKER002"
        assert created_mapping.custom_callsign == "BRAVO"
        assert created_mapping.enabled is False  # This is the key fix
        assert created_mapping.cot_type is None

    def test_create_callsign_mappings_handles_mixed_enabled_states(self, operations_service, mock_session, mock_stream):
        """Test mixed enabled/disabled trackers in same form"""
        form_data = {
            # Enabled tracker
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "ALPHA", 
            "callsign_mapping_0_enabled": "on",
            
            # Disabled tracker
            "callsign_mapping_1_identifier": "TRACKER002",
            "callsign_mapping_1_callsign": "BRAVO",
            # No enabled field = disabled
            
            # Another enabled tracker
            "callsign_mapping_2_identifier": "TRACKER003",
            "callsign_mapping_2_callsign": "CHARLIE",
            "callsign_mapping_2_enabled": "true",  # Alternative true value
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        # Verify 3 mappings were created
        assert mock_session.add.call_count == 3
        
        # Check each mapping
        created_mappings = [call[0][0] for call in mock_session.add.call_args_list]
        
        # First mapping - enabled
        assert created_mappings[0].identifier_value == "TRACKER001"
        assert created_mappings[0].enabled is True
        
        # Second mapping - disabled
        assert created_mappings[1].identifier_value == "TRACKER002"
        assert created_mappings[1].enabled is False
        
        # Third mapping - enabled
        assert created_mappings[2].identifier_value == "TRACKER003"
        assert created_mappings[2].enabled is True

    def test_create_callsign_mappings_handles_json_boolean(self, operations_service, mock_session, mock_stream):
        """Test that JSON boolean values are handled correctly"""
        # JSON data with boolean values
        json_data = {
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "ALPHA",
            "callsign_mapping_0_enabled": True,  # JSON boolean true
            
            "callsign_mapping_1_identifier": "TRACKER002", 
            "callsign_mapping_1_callsign": "BRAVO",
            "callsign_mapping_1_enabled": False,  # JSON boolean false
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, json_data)

        # Verify 2 mappings were created
        assert mock_session.add.call_count == 2
        
        created_mappings = [call[0][0] for call in mock_session.add.call_args_list]
        
        # First mapping - enabled
        assert created_mappings[0].enabled is True
        
        # Second mapping - disabled  
        assert created_mappings[1].enabled is False

    def test_create_callsign_mappings_allows_empty_callsign_for_disabled(self, operations_service, mock_session, mock_stream):
        """Test that disabled trackers can have empty callsigns"""
        form_data = {
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "",  # Empty callsign
            # No enabled field = disabled
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        # Verify mapping was still created (even with empty callsign)
        mock_session.add.assert_called_once()
        created_mapping = mock_session.add.call_args[0][0]
        
        assert created_mapping.identifier_value == "TRACKER001"
        assert created_mapping.custom_callsign == ""
        assert created_mapping.enabled is False

    def test_create_callsign_mappings_skips_missing_identifier(self, operations_service, mock_session, mock_stream):
        """Test that mappings without identifiers are skipped"""
        form_data = {
            # Missing identifier - should be skipped
            "callsign_mapping_0_callsign": "ALPHA",
            "callsign_mapping_0_enabled": "on",
            
            # Valid mapping - should be created
            "callsign_mapping_1_identifier": "TRACKER002",
            "callsign_mapping_1_callsign": "BRAVO",
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        # Only one mapping should be created (the one with identifier)
        mock_session.add.assert_called_once()
        created_mapping = mock_session.add.call_args[0][0]
        assert created_mapping.identifier_value == "TRACKER002"

    def test_update_callsign_mappings_preserves_enabled_field(self, operations_service, mock_session, mock_stream):
        """Test that update method properly handles enabled field via create method"""
        form_data = {
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "ALPHA",
            "callsign_mapping_0_enabled": "on",
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            with patch('models.callsign_mapping.CallsignMapping.query') as mock_query:
                mock_query.filter_by.return_value.delete.return_value = None
                
                operations_service._update_callsign_mappings(mock_stream, form_data)

        # Verify old mappings were deleted
        mock_query.filter_by.assert_called_with(stream_id=mock_stream.id)
        mock_query.filter_by.return_value.delete.assert_called_once()
        
        # Verify new mapping was created with enabled field
        mock_session.add.assert_called_once()
        created_mapping = mock_session.add.call_args[0][0]
        assert created_mapping.enabled is True


class TestEnabledFieldValidation:
    """Test various enabled field value formats"""

    @pytest.fixture
    def operations_service(self, app, db_session):
        """Create StreamOperationsService instance"""
        with app.app_context():
            from services.stream_manager import StreamManager
            from database import db
            mock_stream_manager = Mock(spec=StreamManager)
            service = StreamOperationsService(mock_stream_manager, db)
            return service

    @pytest.fixture
    def mock_session(self):
        """Create mock database session"""
        return Mock()

    @pytest.fixture
    def mock_stream(self):
        """Create mock stream object"""
        stream = Mock()
        stream.id = 1
        return stream

    def test_enabled_field_string_variations(self, operations_service, mock_session, mock_stream):
        """Test different string representations of enabled field"""
        test_cases = [
            ("on", True),      # HTML checkbox checked
            ("true", True),    # String true
            ("True", True),    # Capitalized true
            ("1", True),       # String 1
            ("off", False),    # HTML checkbox unchecked (rare)
            ("false", False),  # String false
            ("0", False),      # String 0
            ("", False),       # Empty string
        ]

        for enabled_value, expected_result in test_cases:
            with patch.object(operations_service, '_get_session', return_value=mock_session):
                form_data = {
                    "callsign_mapping_0_identifier": "TRACKER001",
                    "callsign_mapping_0_callsign": "TEST",
                    "callsign_mapping_0_enabled": enabled_value,
                }
                
                operations_service._create_callsign_mappings(mock_stream, form_data)
                
                # Get the created mapping
                created_mapping = mock_session.add.call_args[0][0]
                assert created_mapping.enabled is expected_result, f"Failed for value '{enabled_value}'"
                
                # Reset for next iteration
                mock_session.reset_mock()

    def test_enabled_field_none_defaults_to_false(self, operations_service, mock_session, mock_stream):
        """Test that None/missing enabled field defaults to False (unchecked checkbox)"""
        form_data = {
            "callsign_mapping_0_identifier": "TRACKER001",
            "callsign_mapping_0_callsign": "TEST",
            # No enabled field = None from data.get()
        }

        with patch.object(operations_service, '_get_session', return_value=mock_session):
            operations_service._create_callsign_mappings(mock_stream, form_data)

        created_mapping = mock_session.add.call_args[0][0]
        assert created_mapping.enabled is False