"""
ABOUTME: Unit tests for the bootstrap service admin user creation and race condition handling
ABOUTME: Tests initial admin creation, race condition prevention, and database-based tracking

Unit tests for TrakBridge bootstrap service focusing on reliability and race condition handling.

This module tests the bootstrap service's critical functionality:
- Initial admin user creation
- Race condition prevention during Docker restarts
- Database-based bootstrap tracking
- Duplicate prevention

Author: Emfour Solutions
Created: 2025-08-12
Version: 1.0.0
"""

import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from database import db
from models.user import User, UserRole, AccountStatus, AuthProvider
from services.auth.bootstrap_service import BootstrapService, get_bootstrap_service


class TestBootstrapServiceCore:
    """Test core bootstrap service functionality."""

    @pytest.fixture
    def clean_database(self, app, db_session):
        """Ensure database is clean for each test."""
        with app.app_context():
            # Remove all users to start fresh
            User.query.delete()
            db_session.commit()
            yield
            # Cleanup after test
            User.query.delete()
            db_session.commit()

    @pytest.fixture
    def bootstrap_service(self):
        """Create a bootstrap service instance for testing."""
        # Create temporary directory for bootstrap file
        temp_dir = tempfile.mkdtemp()
        bootstrap_file_path = os.path.join(temp_dir, ".bootstrap_completed")
        return BootstrapService(bootstrap_file_path=bootstrap_file_path)

    def test_bootstrap_service_creation(self, bootstrap_service):
        """Test creating a bootstrap service instance."""
        assert bootstrap_service is not None
        assert bootstrap_service.default_admin_username == "admin"
        assert bootstrap_service.default_admin_password == "TrakBridge-Setup-2025!"

    def test_get_bootstrap_service_singleton(self):
        """Test that get_bootstrap_service returns the same instance."""
        service1 = get_bootstrap_service()
        service2 = get_bootstrap_service()
        assert service1 is service2

    def test_should_create_initial_admin_clean_database(self, app, clean_database, bootstrap_service):
        """Test should_create_initial_admin with clean database."""
        with app.app_context():
            result = bootstrap_service.should_create_initial_admin()
            assert result is True

    def test_should_create_initial_admin_with_existing_admin(self, app, clean_database, db_session, bootstrap_service):
        """Test should_create_initial_admin when admin users already exist."""
        with app.app_context():
            # Create an admin user
            admin_user = User.create_local_user(
                username="existing_admin",
                password="ExistingPassword123!",
                email="admin@test.com",
                full_name="Existing Admin",
                role=UserRole.ADMIN
            )
            admin_user.status = AccountStatus.ACTIVE
            db_session.add(admin_user)
            db_session.commit()

            result = bootstrap_service.should_create_initial_admin()
            assert result is False

    def test_create_initial_admin_success(self, app, clean_database, db_session, bootstrap_service):
        """Test successful initial admin creation."""
        with app.app_context():
            # Ensure clean state
            assert User.query.filter_by(role=UserRole.ADMIN).count() == 0
            assert bootstrap_service.should_create_initial_admin() is True
            
            admin_user = bootstrap_service.create_initial_admin()
            
            assert admin_user is not None
            assert admin_user.username == bootstrap_service.default_admin_username
            assert admin_user.role == UserRole.ADMIN
            assert admin_user.status == AccountStatus.ACTIVE
            assert admin_user.auth_provider == AuthProvider.LOCAL
            assert admin_user.password_changed_at is None  # Force password change
            
            # Verify user was saved to database
            db_user = User.query.filter_by(username=bootstrap_service.default_admin_username).first()
            assert db_user is not None
            assert db_user.id == admin_user.id

    def test_create_initial_admin_when_exists(self, app, clean_database, db_session, bootstrap_service):
        """Test create_initial_admin when admin already exists."""
        with app.app_context():
            # Create admin user first
            existing_admin = User.create_local_user(
                username=bootstrap_service.default_admin_username,
                password="ExistingPassword123!",
                email="admin@test.com",
                full_name="Existing Admin",
                role=UserRole.ADMIN
            )
            existing_admin.status = AccountStatus.ACTIVE
            db_session.add(existing_admin)
            db_session.commit()

            # Try to create again - should handle gracefully
            admin_user = bootstrap_service.create_initial_admin()
            
            # Should either return None or existing user, but not create duplicate
            if admin_user is not None:
                assert admin_user.id == existing_admin.id

            # Verify only one admin exists
            admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
            assert admin_count == 1

    def test_database_based_bootstrap_detection(self, app, clean_database, db_session, bootstrap_service):
        """Test database-based bootstrap completion detection."""
        with app.app_context():
            # Initially no bootstrap completion detected - ensure clean state first
            assert User.query.filter_by(role=UserRole.ADMIN).count() == 0
            assert bootstrap_service._is_bootstrap_completed() is False

            # Create admin user (simulating existing installation)
            admin_user = User.create_local_user(
                username="database_admin",
                password="Password123!",
                email="admin@test.com",
                full_name="Database Admin",
                role=UserRole.ADMIN
            )
            admin_user.status = AccountStatus.ACTIVE
            db_session.add(admin_user)
            db_session.commit()

            # Should now detect bootstrap completion via database
            assert bootstrap_service._is_bootstrap_completed() is True
            
            # Should not create additional admin
            assert bootstrap_service.should_create_initial_admin() is False

    def test_bootstrap_info_collection(self, app, clean_database, db_session, bootstrap_service):
        """Test comprehensive bootstrap info collection."""
        with app.app_context():
            # Ensure clean state first
            assert User.query.filter_by(role=UserRole.ADMIN).count() == 0
            
            # Test with no admin users
            info = bootstrap_service.get_bootstrap_info()
            
            assert info['admin_count'] == 0
            assert info['default_admin_exists'] is False
            assert info['should_create_admin'] is True
            assert info['bootstrap_completed'] is False
            assert info['tables_exist'] is True
            assert 'timestamp' in info

            # Create admin user
            admin_user = User.create_local_user(
                username=bootstrap_service.default_admin_username,
                password="Password123!",
                email="admin@test.com",
                full_name="Admin User",
                role=UserRole.ADMIN
            )
            admin_user.status = AccountStatus.ACTIVE
            db_session.add(admin_user)
            db_session.commit()

            # Test with admin user
            info = bootstrap_service.get_bootstrap_info()
            
            assert info['admin_count'] == 1
            assert info['default_admin_exists'] is True
            assert info['should_create_admin'] is False
            assert info['bootstrap_completed'] is True

    def test_force_password_change_logic(self, app, clean_database, db_session, bootstrap_service):
        """Test force password change requirement detection."""
        with app.app_context():
            # Create admin user with no password change date (should require change)
            admin_user = User.create_local_user(
                username=bootstrap_service.default_admin_username,
                password=bootstrap_service.default_admin_password,
                email="admin@test.com",
                full_name="Admin User",
                role=UserRole.ADMIN
            )
            admin_user.password_changed_at = None
            admin_user.status = AccountStatus.ACTIVE
            db_session.add(admin_user)
            db_session.commit()

            assert bootstrap_service.force_password_change_required(admin_user) is True

    def test_environment_variable_override(self, app, bootstrap_service):
        """Test environment variable override for bootstrap completion."""
        with app.app_context():
            # Set environment variable
            with patch.dict(os.environ, {bootstrap_service.bootstrap_flag_key: 'true'}):
                assert bootstrap_service._is_bootstrap_completed() is True
                assert bootstrap_service.should_create_initial_admin() is False


class TestBootstrapServiceRaceConditions:
    """Test race condition handling in bootstrap service."""

    @pytest.fixture
    def clean_database(self, app, db_session):
        """Ensure database is clean for each test."""
        with app.app_context():
            User.query.delete()
            db_session.commit()
            yield
            User.query.delete()
            db_session.commit()

    def test_duplicate_prevention_workflow(self, app, clean_database, db_session):
        """Test complete workflow preventing duplicates."""
        with app.app_context():
            # Create a test-specific bootstrap service with temp file path
            temp_dir = tempfile.mkdtemp()
            bootstrap_file_path = os.path.join(temp_dir, ".bootstrap_completed")
            bootstrap_service = BootstrapService(bootstrap_file_path=bootstrap_file_path)
            
            # Step 1: Initial state - no admin users
            assert User.query.filter_by(role=UserRole.ADMIN).count() == 0
            assert bootstrap_service.should_create_initial_admin() is True
            
            # Step 2: Create initial admin
            admin_user = bootstrap_service.create_initial_admin()
            assert admin_user is not None
            assert admin_user.username == "admin"
            
            # Step 3: Verify state after creation
            assert User.query.filter_by(role=UserRole.ADMIN).count() == 1
            assert bootstrap_service.should_create_initial_admin() is False
            assert bootstrap_service._is_bootstrap_completed() is True
            
            # Step 4: Simulate container restart - try to create again
            admin_user_2 = bootstrap_service.create_initial_admin()
            # Should either return None or existing user, but not create duplicate
            
            # Step 5: Verify no duplicates created
            final_count = User.query.filter_by(role=UserRole.ADMIN).count()
            assert final_count == 1

    def test_existing_admin_detection(self, app, clean_database, db_session):
        """Test bootstrap behavior with existing admin users."""
        with app.app_context():
            # Create a test-specific bootstrap service with temp file path
            temp_dir = tempfile.mkdtemp()
            bootstrap_file_path = os.path.join(temp_dir, ".bootstrap_completed")
            bootstrap_service = BootstrapService(bootstrap_file_path=bootstrap_file_path)
            
            # Create admin user with different username
            existing_admin = User.create_local_user(
                username="existing_admin",
                password="ExistingPassword123!",
                email="admin@existing.com",
                full_name="Existing Admin",
                role=UserRole.ADMIN
            )
            existing_admin.status = AccountStatus.ACTIVE
            db_session.add(existing_admin)
            db_session.commit()
            
            # Bootstrap should detect existing admin and not create new one
            assert bootstrap_service.should_create_initial_admin() is False
            admin_user = bootstrap_service.create_initial_admin()
            assert admin_user is None
            
            # Verify no new admin created
            admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
            assert admin_count == 1
            
            # Verify bootstrap is marked complete
            assert bootstrap_service._is_bootstrap_completed() is True

    def test_multiple_bootstrap_attempts(self, app, clean_database, db_session):
        """Test multiple bootstrap attempts handle gracefully."""
        with app.app_context():
            # Create a test-specific bootstrap service with temp file path
            temp_dir = tempfile.mkdtemp()
            bootstrap_file_path = os.path.join(temp_dir, ".bootstrap_completed")
            bootstrap_service = BootstrapService(bootstrap_file_path=bootstrap_file_path)
            
            # Attempt multiple creations
            results = []
            
            for i in range(3):
                try:
                    admin_user = bootstrap_service.create_initial_admin()
                    results.append(admin_user)
                except Exception as e:
                    results.append(None)
            
            # Verify that at most one admin was created
            admin_count = User.query.filter_by(role=UserRole.ADMIN).count()
            assert admin_count <= 1
            
            # Verify final state is consistent
            if admin_count == 1:
                final_admin = User.query.filter_by(role=UserRole.ADMIN).first()
                assert final_admin.username == bootstrap_service.default_admin_username


class TestBootstrapServiceErrorHandling:
    """Test error handling in bootstrap service."""

    @pytest.fixture
    def clean_database(self, app, db_session):
        """Ensure database is clean for each test."""
        with app.app_context():
            User.query.delete()
            db_session.commit()
            yield
            User.query.delete()
            db_session.commit()

    @pytest.fixture
    def bootstrap_service(self):
        """Create a bootstrap service instance for testing."""
        # Create temporary directory for bootstrap file
        temp_dir = tempfile.mkdtemp()
        bootstrap_file_path = os.path.join(temp_dir, ".bootstrap_completed")
        return BootstrapService(bootstrap_file_path=bootstrap_file_path)

    def test_database_error_handling(self, app, bootstrap_service):
        """Test handling of database errors."""
        with app.app_context():
            # Test should_create_initial_admin with database error
            with patch('database.db.inspect', side_effect=Exception("Database error")):
                result = bootstrap_service.should_create_initial_admin()
                assert result is False

    def test_file_system_error_resilience(self, app, clean_database, db_session, bootstrap_service):
        """Test that file system errors don't prevent database-based operation."""
        with app.app_context():
            # Create admin user
            admin_user = User.create_local_user(
                username="resilience_admin",
                password="Password123!",
                email="admin@test.com",
                full_name="Resilience Admin",
                role=UserRole.ADMIN
            )
            admin_user.status = AccountStatus.ACTIVE
            db_session.add(admin_user)
            db_session.commit()

            # Mock file operations to fail
            with patch.object(bootstrap_service, '_mark_bootstrap_completed', side_effect=OSError("File system error")):
                # Should still detect bootstrap completion via database
                assert bootstrap_service._is_bootstrap_completed() is True
                assert bootstrap_service.should_create_initial_admin() is False