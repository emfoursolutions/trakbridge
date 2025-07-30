"""
ABOUTME: Tests for authentication CLI commands and management utilities
ABOUTME: Validates CLI tools for user management, testing, and administration

File: tests/test_auth_cli.py

Description:
    Test suite for authentication-related CLI commands including:
    - User creation and management commands
    - Authentication provider testing utilities
    - Configuration validation tools
    - Health check commands
    - Administrative utilities

Author: Emfour Solutions
Created: 2025-07-27
Last Modified: 2025-07-27
Version: 1.0.0
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from flask.testing import FlaskCliRunner
from click.testing import CliRunner

from models.user import User, UserRole
from database import db


class TestAuthCLICommands:
    """Test authentication CLI commands"""

    def test_create_user_command(self, app):
        """Test CLI command to create user"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            # Test creating a new user
            result = runner.invoke(
                args=[
                    "auth",
                    "create-user",
                    "--username",
                    "newuser",
                    "--email",
                    "newuser@test.com",
                    "--role",
                    "user",
                    "--password",
                    "NewUserPass123",
                ]
            )

            assert result.exit_code == 0
            assert "User created successfully" in result.output

            # Verify user was created
            user = User.query.filter_by(username="newuser").first()
            assert user is not None
            assert user.email == "newuser@test.com"
            assert user.role == UserRole.USER

    def test_create_admin_command(self, app):
        """Test CLI command to create admin user"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(
                args=[
                    "auth",
                    "create-admin",
                    "--username",
                    "newadmin",
                    "--email",
                    "admin@test.com",
                ],
                input="AdminPass123\nAdminPass123\n",
            )

            assert result.exit_code == 0
            assert "Admin user created successfully" in result.output

            # Verify admin was created
            user = User.query.filter_by(username="newadmin").first()
            assert user is not None
            assert user.role == UserRole.ADMIN

    def test_list_users_command(self, app, test_users):
        """Test CLI command to list users"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "list-users"])

            assert result.exit_code == 0
            assert "admin" in result.output
            assert "operator" in result.output
            assert "user" in result.output

    def test_disable_user_command(self, app, test_users):
        """Test CLI command to disable user"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "disable-user", "--username", "user"])

            assert result.exit_code == 0
            assert "User disabled successfully" in result.output

            # Verify user was disabled
            user = User.query.filter_by(username="user").first()
            assert user.is_active is False

    def test_enable_user_command(self, app, test_users):
        """Test CLI command to enable user"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            # First disable the user
            user = test_users["user"]
            user.is_active = False
            db.session.commit()

            # Then enable via CLI
            result = runner.invoke(args=["auth", "enable-user", "--username", "user"])

            assert result.exit_code == 0
            assert "User enabled successfully" in result.output

            # Verify user was enabled
            user = User.query.filter_by(username="user").first()
            assert user.is_active is True

    @patch("services.auth.providers.ldap_provider.LDAPAuthProvider.test_connection")
    def test_ldap_test_command(self, mock_test_connection, app):
        """Test CLI command to test LDAP connection"""
        runner = FlaskCliRunner(app)
        mock_test_connection.return_value = True

        with app.app_context():
            result = runner.invoke(args=["auth", "test-ldap", "--username", "testuser"])

            assert result.exit_code == 0
            mock_test_connection.assert_called_once()

    @patch("services.auth.providers.oidc_provider.OIDCAuthProvider.test_configuration")
    def test_oidc_test_command(self, mock_test_config, app):
        """Test CLI command to test OIDC configuration"""
        runner = FlaskCliRunner(app)
        mock_test_config.return_value = True

        with app.app_context():
            result = runner.invoke(args=["auth", "test-oidc", "--verbose"])

            assert result.exit_code == 0
            mock_test_config.assert_called_once()

    def test_reset_password_command(self, app, test_users):
        """Test CLI command to reset user password"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(
                args=["auth", "reset-password", "--username", "user"],
                input="NewPassword123\nNewPassword123\n",
            )

            assert result.exit_code == 0
            assert "Password reset successfully" in result.output

            # Verify password was changed
            user = User.query.filter_by(username="user").first()
            assert user.check_password("NewPassword123") is True

    def test_health_check_command(self, app, auth_manager):
        """Test CLI command for authentication health check"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "health-check"])

            assert result.exit_code == 0
            assert "Authentication System Health" in result.output


class TestAuthConfigValidation:
    """Test authentication configuration validation"""

    def test_validate_config_command(self, app, sample_auth_config):
        """Test CLI command to validate auth configuration"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(
                args=["auth", "validate-config", "--config-file", sample_auth_config]
            )

            assert result.exit_code == 0
            assert "Configuration is valid" in result.output

    def test_validate_invalid_config(self, app, temp_config_dir):
        """Test validation of invalid configuration"""
        runner = FlaskCliRunner(app)

        # Create invalid config file
        invalid_config = os.path.join(temp_config_dir, "invalid_auth.yaml")
        with open(invalid_config, "w") as f:
            f.write(
                """
authentication:
  session:
    lifetime_hours: -1  # Invalid negative value
  providers:
    local:
      enabled: "not_boolean"  # Invalid type
"""
            )

        with app.app_context():
            result = runner.invoke(
                args=["auth", "validate-config", "--config-file", invalid_config]
            )

            assert result.exit_code != 0
            assert "Configuration validation failed" in result.output


class TestAuthMigrationCommands:
    """Test authentication migration and setup commands"""

    def test_init_auth_command(self, app):
        """Test CLI command to initialize authentication system"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "init"])

            assert result.exit_code == 0
            assert "Authentication system initialized" in result.output

    def test_migrate_users_command(self, app, test_users):
        """Test CLI command to migrate existing users"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "migrate-users"])

            assert result.exit_code == 0

    def test_cleanup_sessions_command(self, app, test_sessions):
        """Test CLI command to cleanup expired sessions"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "cleanup-sessions"])

            assert result.exit_code == 0
            assert "sessions cleaned up" in result.output


class TestAuthImportExport:
    """Test authentication import/export utilities"""

    def test_export_users_command(self, app, test_users):
        """Test CLI command to export users"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(
                args=[
                    "auth",
                    "export-users",
                    "--format",
                    "json",
                    "--output",
                    "/tmp/test_users.json",
                ]
            )

            assert result.exit_code == 0
            assert "Users exported successfully" in result.output

            # Verify file was created
            assert os.path.exists("/tmp/test_users.json")

            # Cleanup
            os.remove("/tmp/test_users.json")

    def test_import_users_command(self, app, temp_config_dir):
        """Test CLI command to import users"""
        runner = FlaskCliRunner(app)

        # Create test import file
        import_file = os.path.join(temp_config_dir, "import_users.json")
        import_data = """[
  {
    "username": "imported_user",
    "email": "imported@test.com",
    "first_name": "Imported",
    "last_name": "User",
    "role": "user",
    "auth_provider": "local"
  }
]"""
        with open(import_file, "w") as f:
            f.write(import_data)

        with app.app_context():
            result = runner.invoke(
                args=[
                    "auth",
                    "import-users",
                    "--file",
                    import_file,
                    "--dry-run",  # Don't actually import
                ]
            )

            assert result.exit_code == 0
            assert "imported_user" in result.output


class TestAuthMonitoring:
    """Test authentication monitoring and reporting commands"""

    def test_audit_report_command(self, app, test_users):
        """Test CLI command to generate audit report"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "audit-report", "--days", "30"])

            assert result.exit_code == 0
            assert "Authentication Audit Report" in result.output

    def test_session_report_command(self, app, test_sessions):
        """Test CLI command to generate session report"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "session-report"])

            assert result.exit_code == 0
            assert "Active Sessions" in result.output

    def test_security_status_command(self, app):
        """Test CLI command to show security status"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            result = runner.invoke(args=["auth", "security-status"])

            assert result.exit_code == 0
            assert "Security Status" in result.output


# CLI command fixtures and utilities
@pytest.fixture
def cli_runner():
    """Create CLI test runner"""
    return CliRunner()


@pytest.fixture
def mock_auth_config(temp_config_dir):
    """Create mock authentication configuration for CLI tests"""
    config_file = os.path.join(temp_config_dir, "test_auth.yaml")
    config_content = """
authentication:
  session:
    lifetime_hours: 8
  providers:
    local:
      enabled: true
    ldap:
      enabled: false
    oidc:
      enabled: false
"""
    with open(config_file, "w") as f:
        f.write(config_content)

    return config_file


# Integration test for full CLI workflow
class TestAuthCLIWorkflow:
    """Test complete authentication CLI workflow"""

    def test_full_setup_workflow(self, app):
        """Test complete authentication setup workflow"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            # 1. Initialize authentication system
            result = runner.invoke(args=["auth", "init"])
            assert result.exit_code == 0

            # 2. Create admin user
            result = runner.invoke(
                args=[
                    "auth",
                    "create-admin",
                    "--username",
                    "setup_admin",
                    "--email",
                    "setup@test.com",
                ],
                input="SetupPass123\nSetupPass123\n",
            )
            assert result.exit_code == 0

            # 3. Create regular user
            result = runner.invoke(
                args=[
                    "auth",
                    "create-user",
                    "--username",
                    "setup_user",
                    "--email",
                    "user@test.com",
                    "--role",
                    "user",
                    "--password",
                    "UserPass123",
                ]
            )
            assert result.exit_code == 0

            # 4. List all users
            result = runner.invoke(args=["auth", "list-users"])
            assert result.exit_code == 0
            assert "setup_admin" in result.output
            assert "setup_user" in result.output

            # 5. Run health check
            result = runner.invoke(args=["auth", "health-check"])
            assert result.exit_code == 0

    def test_user_lifecycle_workflow(self, app):
        """Test user lifecycle management workflow"""
        runner = FlaskCliRunner(app)

        with app.app_context():
            # Create user
            result = runner.invoke(
                args=[
                    "auth",
                    "create-user",
                    "--username",
                    "lifecycle_user",
                    "--email",
                    "lifecycle@test.com",
                    "--role",
                    "operator",
                    "--password",
                    "LifecyclePass123",
                ]
            )
            assert result.exit_code == 0

            # Disable user
            result = runner.invoke(
                args=["auth", "disable-user", "--username", "lifecycle_user"]
            )
            assert result.exit_code == 0

            # Enable user
            result = runner.invoke(
                args=["auth", "enable-user", "--username", "lifecycle_user"]
            )
            assert result.exit_code == 0

            # Reset password
            result = runner.invoke(
                args=["auth", "reset-password", "--username", "lifecycle_user"],
                input="NewLifecyclePass123\nNewLifecyclePass123\n",
            )
            assert result.exit_code == 0

            # Verify final state
            user = User.query.filter_by(username="lifecycle_user").first()
            assert user is not None
            assert user.is_active is True
            assert user.check_password("NewLifecyclePass123") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
