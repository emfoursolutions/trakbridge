"""
ABOUTME: Comprehensive tests for CallsignMapping model with team member functionality
ABOUTME: Tests team member fields, validation, constraints and database operations
"""

import pytest
from models.callsign_mapping import CallsignMapping
from database import db


class TestCallsignMappingTeamMemberFields:
    """Test CallsignMapping model with team member fields"""

    def test_callsign_mapping_has_team_member_fields(self):
        """Test that CallsignMapping model has required team member fields"""
        # This test will fail initially - we need to add these fields
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="TeamTest",
            cot_type_override="team_member",
            team_role="Sniper",
            team_color="Green"
        )

        assert hasattr(mapping, 'cot_type_override')
        assert hasattr(mapping, 'team_role')
        assert hasattr(mapping, 'team_color')
        assert mapping.cot_type_override == "team_member"
        assert mapping.team_role == "Sniper"
        assert mapping.team_color == "Green"

    def test_callsign_mapping_team_member_fields_nullable(self):
        """Test that team member fields can be null for regular mappings"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="RegularTest"
        )

        assert mapping.cot_type_override is None
        assert mapping.team_role is None
        assert mapping.team_color is None

    def test_callsign_mapping_with_team_member_to_dict(self):
        """Test to_dict method includes team member fields"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="TeamTest",
            cot_type_override="team_member",
            team_role="Medic",
            team_color="Red"
        )

        result = mapping.to_dict()
        assert 'cot_type_override' in result
        assert 'team_role' in result
        assert 'team_color' in result
        assert result['cot_type_override'] == "team_member"
        assert result['team_role'] == "Medic"
        assert result['team_color'] == "Red"


class TestCallsignMappingTeamMemberValidation:
    """Test validation for team member fields"""

    @pytest.mark.parametrize("role", [
        "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
        "Forward Observer", "RTO", "K9"
    ])
    def test_valid_team_roles(self, role):
        """Test that all valid team roles are accepted"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="RoleTest",
            cot_type_override="team_member",
            team_role=role,
            team_color="Green"
        )

        # This will fail initially - we need validation
        mapping.validate_team_member_fields()
        assert mapping.team_role == role

    @pytest.mark.parametrize("color", [
        "Teal", "Green", "Dark Green", "Brown", "White", "Yellow",
        "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue",
        "Blue", "Cyan"
    ])
    def test_valid_team_colors(self, color):
        """Test that all valid team colors are accepted"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="ColorTest",
            cot_type_override="team_member",
            team_role="Sniper",
            team_color=color
        )

        # This will fail initially - we need validation
        mapping.validate_team_member_fields()
        assert mapping.team_color == color

    def test_invalid_team_role_raises_error(self):
        """Test that invalid team roles raise validation error"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="InvalidTest",
            cot_type_override="team_member",
            team_role="InvalidRole",
            team_color="Green"
        )

        with pytest.raises(ValueError, match="Invalid team role"):
            mapping.validate_team_member_fields()

    def test_invalid_team_color_raises_error(self):
        """Test that invalid team colors raise validation error"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="InvalidTest",
            cot_type_override="team_member",
            team_role="Sniper",
            team_color="InvalidColor"
        )

        with pytest.raises(ValueError, match="Invalid team color"):
            mapping.validate_team_member_fields()

    def test_team_member_requires_role_and_color(self):
        """Test that team_member cot_type_override requires role and color"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="IncompleteTest",
            cot_type_override="team_member"
            # Missing team_role and team_color
        )

        with pytest.raises(ValueError, match="Team member configuration requires both role and color"):
            mapping.validate_team_member_fields()

    def test_non_team_member_allows_null_role_color(self):
        """Test that non-team_member mappings allow null role/color"""
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="TEST123",
            custom_callsign="RegularTest",
            cot_type_override=None,
            team_role=None,
            team_color=None
        )

        # Should not raise any errors
        mapping.validate_team_member_fields()


class TestCallsignMappingDatabaseConstraints:
    """Test database constraints and relationships for team member fields"""

    def test_team_member_fields_model_compatibility(self):
        """Test that team member fields work with CallsignMapping model"""
        # Test creating mapping with team member fields
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="MODEL_TEST123",
            custom_callsign="ModelTest",
            cot_type_override="team_member",
            team_role="Team Lead",
            team_color="Blue"
        )

        assert mapping.cot_type_override == "team_member"
        assert mapping.team_role == "Team Lead"
        assert mapping.team_color == "Blue"

        # Test serialization
        data = mapping.to_dict()
        assert data['cot_type_override'] == "team_member"
        assert data['team_role'] == "Team Lead"
        assert data['team_color'] == "Blue"

    def test_existing_callsign_mapping_compatibility(self):
        """Test that existing callsign mappings work with new team member fields"""
        # Create mapping without team member fields (like existing data)
        mapping = CallsignMapping(
            stream_id=1,
            identifier_value="COMPAT_TEST123",
            custom_callsign="CompatTest",
            cot_type="a-f-G-E-V-C"  # Existing cot_type field
        )

        # Verify team member fields default to null
        assert mapping.cot_type_override is None
        assert mapping.team_role is None
        assert mapping.team_color is None
        assert mapping.cot_type == "a-f-G-E-V-C"  # Original field preserved

        # Test serialization preserves null values
        data = mapping.to_dict()
        assert data['cot_type_override'] is None
        assert data['team_role'] is None
        assert data['team_color'] is None
        assert data['cot_type'] == "a-f-G-E-V-C"