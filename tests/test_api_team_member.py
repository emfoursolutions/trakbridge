"""
ABOUTME: Comprehensive API tests for team member callsign mapping functionality
ABOUTME: Tests extended API endpoints to support team member configuration through callsign mappings
"""

import pytest
import json
import uuid
from unittest.mock import patch, MagicMock, Mock
from models.callsign_mapping import CallsignMapping
from models.stream import Stream
from models.user import User, UserRole, AuthProvider
from models.tak_server import TakServer
from database import db


@pytest.fixture
def sample_stream(db_session):
    """Create a sample stream for testing"""
    unique_id = uuid.uuid4().hex[:8]

    # Create test TAK server
    tak_server = TakServer(
        name=f"Test TAK Server {unique_id}",
        host="test.example.com",
        port=8087,
        protocol="tls",
        verify_ssl=True,
    )
    db_session.add(tak_server)
    db_session.commit()

    # Create test stream
    stream = Stream(
        name=f"Test Stream {unique_id}",
        plugin_type="garmin_plugin",
        enable_callsign_mapping=True,
        callsign_identifier_field="device_name",
        callsign_error_handling="fallback",
        enable_per_callsign_cot_types=True,
    )
    stream.tak_servers = [tak_server]
    db_session.add(stream)
    db_session.commit()

    return stream


class TestDiscoverTrackersTeamMemberAPI:
    """Test discover-trackers endpoint with team member CoT type options"""

    @patch('services.auth.require_permission')
    @patch('services.connection_test_service.ConnectionTestService.discover_plugin_trackers_sync')
    @patch('utils.app_helpers.get_plugin_manager')
    def test_discover_trackers_includes_cot_type_options(self, mock_plugin_mgr, mock_discover, mock_auth, client):
        """Test that discover-trackers response includes CoT type options"""
        mock_auth.return_value = None  # Allow access

        # Mock plugin manager
        mock_plugin = Mock()
        mock_plugin_mgr.return_value.plugins = {"garmin_plugin": mock_plugin}

        mock_discover.return_value = {
            "success": True,
            "tracker_data": [
                {"identifier": "TEST123", "name": "Test Device"}
            ]
        }

        payload = {
            "plugin_type": "garmin_plugin",
            "plugin_config": {
                "username": "test@example.com",
                "password": "testpass"
            }
        }

        response = client.post("/api/streams/discover-trackers", json=payload)

        assert response.status_code == 200
        data = response.get_json()

        # Test that response includes CoT type options - THIS WILL FAIL INITIALLY
        assert "cot_type_options" in data
        assert "Default" in data["cot_type_options"]
        assert "Standard Point" in data["cot_type_options"]
        assert "Team Member" in data["cot_type_options"]

    @patch('services.auth.require_permission')
    @patch('services.connection_test_service.ConnectionTestService.discover_plugin_trackers_sync')
    @patch('utils.app_helpers.get_plugin_manager')
    def test_discover_trackers_includes_team_member_options(self, mock_plugin_mgr, mock_discover, mock_auth, client):
        """Test that discover-trackers response includes team member role and color options"""
        mock_auth.return_value = None  # Allow access

        # Mock plugin manager
        mock_plugin = Mock()
        mock_plugin_mgr.return_value.plugins = {"garmin_plugin": mock_plugin}

        mock_discover.return_value = {
            "success": True,
            "tracker_data": [
                {"identifier": "TEST123", "name": "Test Device"}
            ]
        }

        payload = {
            "plugin_type": "garmin_plugin",
            "plugin_config": {
                "username": "test@example.com",
                "password": "testpass"
            }
        }

        response = client.post("/api/streams/discover-trackers", json=payload)

        assert response.status_code == 200
        data = response.get_json()

        # Test that response includes team member role options - THIS WILL FAIL INITIALLY
        assert "team_role_options" in data
        expected_roles = [
            "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
            "Forward Observer", "RTO", "K9"
        ]
        for role in expected_roles:
            assert role in data["team_role_options"]

        # Test that response includes team member color options - THIS WILL FAIL INITIALLY
        assert "team_color_options" in data
        expected_colors = [
            "Teal", "Green", "Dark Green", "Brown", "White", "Yellow",
            "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue",
            "Blue", "Cyan"
        ]
        for color in expected_colors:
            assert color in data["team_color_options"]


class TestCallsignMappingTeamMemberAPI:
    """Test callsign mapping endpoints with team member configuration"""

    @patch('services.auth.require_permission')
    def test_update_callsign_mappings_with_team_member_data(self, mock_auth, client, sample_stream):
        """Test POST callsign mappings with team member configuration"""
        mock_auth.return_value = None  # Allow access

        payload = {
            "enable_callsign_mapping": True,
            "callsign_identifier_field": "device_name",
            "mappings": [
                {
                    "identifier_value": "TEST123",
                    "custom_callsign": "Alpha1",
                    "cot_type_override": "team_member",
                    "team_role": "Team Lead",
                    "team_color": "Blue",
                    "enabled": True
                }
            ]
        }

        response = client.post(
            f"/api/streams/{sample_stream.id}/callsign-mappings",
            json=payload
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        # Verify the mapping was created correctly
        mapping = CallsignMapping.query.filter_by(stream_id=sample_stream.id).first()
        assert mapping.cot_type_override == "team_member"
        assert mapping.team_role == "Team Lead"
        assert mapping.team_color == "Blue"

    @patch('services.auth.require_permission')
    def test_update_callsign_mappings_team_member_validation(self, mock_auth, client, sample_stream):
        """Test that team member validation is enforced through API"""
        mock_auth.return_value = None  # Allow access

        # Test missing team_role for team_member - THIS SHOULD FAIL VALIDATION
        payload = {
            "enable_callsign_mapping": True,
            "callsign_identifier_field": "device_name",
            "mappings": [
                {
                    "identifier_value": "TEST123",
                    "custom_callsign": "Incomplete",
                    "cot_type_override": "team_member",
                    "team_color": "Green",
                    # Missing team_role
                    "enabled": True
                }
            ]
        }

        response = client.post(
            f"/api/streams/{sample_stream.id}/callsign-mappings",
            json=payload
        )

        # This should fail validation - THIS WILL FAIL INITIALLY UNTIL WE ADD VALIDATION
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "role and color" in data["error"].lower()


class TestTeamMemberAPIValidation:
    """Test API validation for team member fields"""

    @patch('services.auth.require_permission')
    def test_invalid_team_role_validation(self, mock_auth, client, sample_stream):
        """Test API validation rejects invalid team roles"""
        mock_auth.return_value = None  # Allow access

        payload = {
            "enable_callsign_mapping": True,
            "callsign_identifier_field": "device_name",
            "mappings": [
                {
                    "identifier_value": "TEST123",
                    "custom_callsign": "InvalidRole",
                    "cot_type_override": "team_member",
                    "team_role": "InvalidRole",
                    "team_color": "Green",
                    "enabled": True
                }
            ]
        }

        response = client.post(
            f"/api/streams/{sample_stream.id}/callsign-mappings",
            json=payload
        )

        # THIS WILL FAIL INITIALLY UNTIL WE ADD VALIDATION
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "invalid team role" in data["error"].lower()


class TestAPITeamMemberMetadata:
    """Test API endpoints that provide team member metadata"""

    @patch('services.auth.require_permission')
    def test_get_team_member_role_options_endpoint(self, mock_auth, client):
        """Test dedicated endpoint for getting team member role options"""
        mock_auth.return_value = None  # Allow access

        # THIS WILL FAIL INITIALLY - we need to create this endpoint
        response = client.get("/api/team-member/role-options")

        assert response.status_code == 200
        data = response.get_json()

        assert "roles" in data
        expected_roles = [
            "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
            "Forward Observer", "RTO", "K9"
        ]
        assert data["roles"] == expected_roles

    @patch('services.auth.require_permission')
    def test_get_team_member_color_options_endpoint(self, mock_auth, client):
        """Test dedicated endpoint for getting team member color options"""
        mock_auth.return_value = None  # Allow access

        # THIS WILL FAIL INITIALLY - we need to create this endpoint
        response = client.get("/api/team-member/color-options")

        assert response.status_code == 200
        data = response.get_json()

        assert "colors" in data
        expected_colors = [
            "Teal", "Green", "Dark Green", "Brown", "White", "Yellow",
            "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue",
            "Blue", "Cyan"
        ]
        assert data["colors"] == expected_colors