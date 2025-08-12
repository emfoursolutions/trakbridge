"""
ABOUTME: Unit tests for the key rotation service restart_application method
ABOUTME: Tests deployment environment detection and restart instruction generation

Test module for KeyRotationService.restart_application() method.
Validates proper detection of Docker, systemd, supervisor, and manual deployment environments.
Ensures correct restart instructions are returned for each deployment scenario.

Author: Emfour Solutions
Created: 2025-08-12
"""

import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

from services.key_rotation_service import KeyRotationService


class TestKeyRotationRestart:
    """Test class for key rotation restart functionality"""

    def setup_method(self):
        """Set up test fixtures"""
        self.service = KeyRotationService()

    def test_restart_application_docker_environment(self):
        """Test restart application detection in Docker environment"""
        with patch('os.path.exists') as mock_exists:
            # Mock Docker environment file existence
            mock_exists.return_value = True

            result = self.service.restart_application()

            # Verify Docker detection
            mock_exists.assert_called_with("/.dockerenv")
            assert result["success"] is False
            assert result["method"] == "container"
            assert "Docker container" in result["instruction"]

    def test_restart_application_systemd_environment(self):
        """Test restart application detection with systemd"""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker environment
            mock_exists.return_value = False

            # Mock successful systemd detection
            mock_run.return_value = MagicMock(returncode=0)
            
            # Mock secure subprocess runner
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = True
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Verify systemd detection
            assert result["success"] is True
            assert result["method"] == "systemd"
            assert "systemctl restart trakbridge" in result["instruction"]

    def test_restart_application_supervisor_environment(self):
        """Test restart application detection with supervisor"""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker environment
            mock_exists.return_value = False

            # Mock systemd not available, supervisor available
            systemd_run = MagicMock(returncode=1)  # systemd fails
            supervisor_run = MagicMock(returncode=0)  # supervisor succeeds
            mock_run.side_effect = [systemd_run, supervisor_run]

            # Mock secure subprocess runner
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = True
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Verify supervisor detection
            assert result["success"] is True
            assert result["method"] == "supervisor"
            assert "supervisorctl restart trakbridge" in result["instruction"]

    def test_restart_application_manual_fallback(self):
        """Test restart application fallback to manual restart"""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker environment
            mock_exists.return_value = False

            # Mock both systemd and supervisor not available
            mock_run.return_value = MagicMock(returncode=1)

            # Mock secure subprocess runner
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = True
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Verify manual fallback
            assert result["success"] is False
            assert result["method"] == "manual"
            assert "Manually restart the application process" in result["instruction"]

    def test_restart_application_command_validation_failure(self):
        """Test restart application when command validation fails"""
        with patch('os.path.exists') as mock_exists, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker environment
            mock_exists.return_value = False

            # Mock command validation failure
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = False
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Should fall back to manual restart
            assert result["success"] is False
            assert result["method"] == "manual"
            assert "Manually restart the application process" in result["instruction"]

    def test_restart_application_filenotfound_exception(self):
        """Test restart application when subprocess commands are not found"""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker environment
            mock_exists.return_value = False

            # Mock FileNotFoundError for both systemd and supervisor
            mock_run.side_effect = FileNotFoundError()

            # Mock secure subprocess runner
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = True
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Should fall back to manual restart
            assert result["success"] is False
            assert result["method"] == "manual"
            assert "Manually restart the application process" in result["instruction"]

    def test_restart_application_general_exception(self):
        """Test restart application with general exception handling"""
        with patch('os.path.exists') as mock_exists:
            # Mock exception during Docker detection
            mock_exists.side_effect = Exception("Test exception")

            result = self.service.restart_application()

            # Should handle exception gracefully
            assert result["success"] is False
            assert "error" in result
            assert "Test exception" in result["error"]
            assert "Manually restart the application" in result["instruction"]

    def test_restart_application_mixed_environment_detection(self):
        """Test restart application with mixed environment scenarios"""
        with patch('os.path.exists') as mock_exists, \
             patch('subprocess.run') as mock_run, \
             patch('utils.security_helpers.SecureSubprocessRunner') as mock_runner:

            # Mock no Docker but systemd available
            mock_exists.return_value = False
            mock_run.return_value = MagicMock(returncode=0)

            # Mock secure subprocess runner
            mock_runner_instance = MagicMock()
            mock_runner_instance.validate_command.return_value = True
            mock_runner.return_value = mock_runner_instance

            result = self.service.restart_application()

            # Should detect systemd (first successful detection wins)
            assert result["success"] is True
            assert result["method"] == "systemd"

    def test_restart_application_return_types(self):
        """Test restart application return value structure"""
        with patch('os.path.exists') as mock_exists:
            mock_exists.return_value = True  # Docker environment

            result = self.service.restart_application()

            # Verify return structure
            assert isinstance(result, dict)
            assert "success" in result
            assert "method" in result
            assert "instruction" in result
            assert isinstance(result["success"], bool)
            assert isinstance(result["method"], str)
            assert isinstance(result["instruction"], str)

    def test_restart_application_logging_integration(self):
        """Test restart application integrates with logging properly"""
        # This test ensures the method doesn't break logging
        # and can be called without side effects
        
        result = self.service.restart_application()
        
        # Should return a valid result without throwing exceptions
        assert isinstance(result, dict)
        assert "success" in result
        assert "instruction" in result


# Integration test for the admin route
class TestRestartInfoEndpoint:
    """Integration tests for the restart-info endpoint"""

    def test_restart_info_route_exists(self):
        """Test that the restart-info route is properly configured"""
        from routes.admin import bp
        
        # Check that the route exists
        route_found = False
        for rule in bp.url_map.iter_rules():
            if rule.rule.endswith('/key-rotation/restart-info'):
                route_found = True
                break
        
        assert route_found, "restart-info route not found in admin blueprint"

    @patch('routes.admin.get_key_rotation_service')
    def test_restart_info_endpoint_success(self, mock_get_service):
        """Test restart-info endpoint returns success response"""
        from routes.admin import get_restart_info
        
        # Mock the service
        mock_service = MagicMock()
        mock_service.restart_application.return_value = {
            "success": True,
            "method": "docker",
            "instruction": "Restart container"
        }
        mock_get_service.return_value = mock_service
        
        # Test the endpoint
        with patch('routes.admin.jsonify') as mock_jsonify:
            mock_jsonify.return_value = MagicMock()
            
            result = get_restart_info()
            
            # Verify service was called
            mock_service.restart_application.assert_called_once()
            mock_jsonify.assert_called_once()

    @patch('routes.admin.get_key_rotation_service')
    def test_restart_info_endpoint_error_handling(self, mock_get_service):
        """Test restart-info endpoint handles exceptions properly"""
        from routes.admin import get_restart_info
        
        # Mock service to raise exception
        mock_service = MagicMock()
        mock_service.restart_application.side_effect = Exception("Test error")
        mock_get_service.return_value = mock_service
        
        # Test the endpoint
        with patch('routes.admin.jsonify') as mock_jsonify:
            mock_jsonify.return_value = (MagicMock(), 500)
            
            result = get_restart_info()
            
            # Verify error handling
            mock_jsonify.assert_called_once()
            call_args = mock_jsonify.call_args[0][0]
            assert "error" in call_args