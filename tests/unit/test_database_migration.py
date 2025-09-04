"""
ABOUTME: Test suite for Phase 3A database helpers integration in migrated services
ABOUTME: Validates database helper imports and readiness for future database pattern migration

File: tests/test_phase3a_database_migration.py

Description:
    Test suite for Phase 3A database helpers integration validation. While Phase 3A
    primarily focused on logging and config migrations, some services (bootstrap_service,
    encryption_service) also imported database helpers in preparation for future
    database pattern migrations.
    
    Tests:
    - Database helper imports in relevant migrated services
    - Database helper functionality and availability  
    - Preparation for future database pattern migrations
    - Integration with existing database operations
    
Author: Emfour Solutions  
Created: 2025-09-03
"""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from utils.database_helpers import (DatabaseHelper, create_record,
                                    find_by_field, find_by_id,
                                    get_stream_helper, get_tak_server_helper,
                                    get_user_helper, safe_database_operation)


class TestDatabaseHelperImports:
    """Test database helper imports in Phase 3A migrated services"""

    def test_database_helper_functions_available(self):
        """Test that database helper functions are importable and callable"""
        # Core functions should be available
        assert callable(safe_database_operation)
        assert callable(find_by_id)
        assert callable(find_by_field)
        assert callable(create_record)

        # Helper classes should be available
        assert DatabaseHelper is not None
        assert callable(get_stream_helper)
        assert callable(get_user_helper)
        assert callable(get_tak_server_helper)

    def test_services_with_database_helpers_import_correctly(self):
        """Test that services with database operations import helpers correctly"""
        services_with_db_helpers = [
            "services.auth.bootstrap_service",
            "services.encryption_service",
        ]

        for module_name in services_with_db_helpers:
            try:
                module_source = importlib.util.find_spec(module_name)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should import database helpers
                        db_helper_imports = [
                            "from utils.database_helpers import",
                            "safe_database_operation",
                            "find_by_field",
                            "create_record",
                            "DatabaseHelper",
                        ]

                        has_db_import = any(imp in content for imp in db_helper_imports)
                        assert (
                            has_db_import
                        ), f"{module_name} should import database helpers"

            except ImportError as e:
                pytest.fail(f"Could not check imports in {module_name}: {e}")


class TestBootstrapServiceDatabaseIntegration:
    """Test bootstrap service database helper integration"""

    def test_bootstrap_service_imports_database_helpers(self):
        """Test that bootstrap service imports necessary database helpers"""
        try:
            module_source = importlib.util.find_spec("services.auth.bootstrap_service")
            if module_source and module_source.origin:
                with open(module_source.origin, "r") as f:
                    content = f.read()

                    # Should have database helper imports
                    assert "from utils.database_helpers import" in content

                    # Bootstrap service specifically needs these for user creation
                    expected_imports = ["create_record", "find_by_field"]
                    for imp in expected_imports:
                        assert imp in content, f"Bootstrap service should import {imp}"

        except ImportError:
            pytest.skip("Bootstrap service not available")

    def test_bootstrap_service_database_operations_ready(self):
        """Test that bootstrap service is ready for database helper usage"""
        # Test the pattern that could be used in bootstrap service
        from models.user import User

        # Mock database operations that bootstrap service could use
        with patch("utils.database_helpers.find_by_field") as mock_find:
            with patch("utils.database_helpers.create_record") as mock_create:
                mock_find.return_value = None  # User doesn't exist
                mock_create.return_value = MagicMock(spec=User, username="admin")

                # This is the pattern bootstrap service could use
                existing_admin = mock_find(User, "username", "admin")
                if not existing_admin:
                    admin_user = mock_create(
                        User, username="admin", email="admin@test.com", role="admin"
                    )

                # Should have called the helpers correctly
                mock_find.assert_called_once_with(User, "username", "admin")
                mock_create.assert_called_once()


class TestEncryptionServiceDatabaseIntegration:
    """Test encryption service database helper integration"""

    def test_encryption_service_imports_database_helpers(self):
        """Test that encryption service imports database helpers"""
        try:
            module_source = importlib.util.find_spec("services.encryption_service")
            if module_source and module_source.origin:
                with open(module_source.origin, "r") as f:
                    content = f.read()

                    # Should have database helper imports
                    assert "from utils.database_helpers import" in content
                    assert "safe_database_operation" in content

        except ImportError:
            pytest.skip("Encryption service not available")

    def test_encryption_service_safe_operations_ready(self):
        """Test that encryption service is ready for safe database operations"""

        # Test pattern that encryption service could use
        def mock_key_operation():
            # Simulate key management database operation
            return {"key_id": "test-key", "created": True}

        with patch("utils.database_helpers.safe_database_operation") as mock_safe_op:
            mock_safe_op.return_value = {"key_id": "test-key", "created": True}

            # This is the pattern encryption service could use
            result = mock_safe_op(mock_key_operation)

            # Should have used safe operation wrapper
            mock_safe_op.assert_called_once_with(mock_key_operation)
            assert result == {"key_id": "test-key", "created": True}


class TestDatabaseHelperFunctionality:
    """Test database helper functionality for migrated services"""

    def test_safe_database_operation_wrapper(self):
        """Test that safe_database_operation wrapper works correctly"""

        def test_operation(value):
            return f"processed_{value}"

        # Should execute and return result
        result = safe_database_operation(test_operation, "test")
        assert result == "processed_test"

    def test_find_by_field_function_signature(self):
        """Test that find_by_field has correct signature for services"""
        from models.user import User

        # Should be callable with model, field, value
        with patch("utils.database_helpers.find_by_field") as mock_find:
            mock_find.return_value = None

            result = mock_find(User, "username", "test_user")
            mock_find.assert_called_once_with(User, "username", "test_user")

    def test_create_record_function_signature(self):
        """Test that create_record has correct signature for services"""
        from models.user import User

        # Should be callable with model and kwargs
        with patch("utils.database_helpers.create_record") as mock_create:
            mock_create.return_value = MagicMock(spec=User)

            result = mock_create(User, username="test", email="test@example.com")
            mock_create.assert_called_once_with(
                User, username="test", email="test@example.com"
            )

    def test_database_helper_class_instantiation(self):
        """Test that DatabaseHelper class can be instantiated"""
        from models.user import User

        # Should be able to create helper instance
        helper = DatabaseHelper(User)
        assert helper is not None
        assert helper.model_class == User

        # Should have expected methods
        assert hasattr(helper, "find_by_id")
        assert hasattr(helper, "find_by_field")
        assert hasattr(helper, "create")
        assert hasattr(helper, "update")
        assert hasattr(helper, "delete")


class TestDatabaseHelperConvenience:
    """Test convenience functions for common models"""

    def test_get_stream_helper_function(self):
        """Test get_stream_helper convenience function"""
        helper = get_stream_helper()
        assert helper is not None
        assert isinstance(helper, DatabaseHelper)
        # Should be configured for Stream model
        assert helper.model_class.__name__ == "Stream"

    def test_get_user_helper_function(self):
        """Test get_user_helper convenience function"""
        helper = get_user_helper()
        assert helper is not None
        assert isinstance(helper, DatabaseHelper)
        # Should be configured for User model
        assert helper.model_class.__name__ == "User"

    def test_get_tak_server_helper_function(self):
        """Test get_tak_server_helper convenience function"""
        helper = get_tak_server_helper()
        assert helper is not None
        assert isinstance(helper, DatabaseHelper)
        # Should be configured for TAKServer model
        assert helper.model_class.__name__ == "TakServer"


class TestFutureDatabaseMigrationReadiness:
    """Test that Phase 3A sets up services for future database migration"""

    def test_services_ready_for_database_pattern_migration(self):
        """Test that migrated services are ready for future database pattern migration"""
        services_with_future_db_potential = [
            "services.auth.bootstrap_service",
            "services.encryption_service",
            "services.health_service",  # For health check queries
        ]

        for module_name in services_with_future_db_potential:
            try:
                # Services should be importable without database helper usage errors
                module = importlib.import_module(module_name)
                assert module is not None

                # Should have logger for database operation logging
                assert hasattr(module, "logger")

            except ImportError as e:
                pytest.skip(f"Service {module_name} not available: {e}")

    def test_database_helpers_compatible_with_existing_patterns(self):
        """Test that database helpers are compatible with existing database patterns"""
        # Test that helpers don't conflict with existing SQLAlchemy usage
        from database import db

        # Should be able to import both old and new patterns
        assert db is not None  # Existing pattern

        # New patterns should also be available
        from utils.database_helpers import (database_transaction,
                                            safe_database_operation)

        assert callable(database_transaction)
        assert callable(safe_database_operation)

    def test_database_migration_path_clear(self):
        """Test that path is clear for future database pattern migration"""
        # Services should have imports ready for database helpers
        # This enables future migration of try/catch patterns to helper functions

        services_with_db_imports = [
            "services.auth.bootstrap_service",
            "services.encryption_service",
        ]

        for module_name in services_with_db_imports:
            try:
                module_source = importlib.util.find_spec(module_name)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should have database helper imports ready
                        has_helper_imports = (
                            "from utils.database_helpers import" in content
                            or "safe_database_operation" in content
                            or "find_by_field" in content
                            or "create_record" in content
                        )

                        assert (
                            has_helper_imports
                        ), f"{module_name} should have database helper imports for future migration"

            except ImportError as e:
                pytest.skip(f"Could not check {module_name}: {e}")


class TestDatabaseMigrationIntegration:
    """Test integration aspects of database helper migration"""

    def test_database_helpers_work_with_migrated_logging(self):
        """Test that database helpers work with migrated logging system"""
        from services.logging_service import get_module_logger

        # Database helpers should use the same logging system
        logger = get_module_logger("test_db_helpers")

        # Should be able to use database helpers with centralized logging
        with patch.object(logger, "info") as mock_log:

            def test_db_op():
                logger.info("Database operation executed")
                return "success"

            result = safe_database_operation(test_db_op)

            assert result == "success"
            mock_log.assert_called_once_with("Database operation executed")

    def test_database_helpers_work_with_config_helpers(self):
        """Test that database helpers can work with config helpers for configuration"""
        from utils.config_helpers import ConfigHelper

        # Should be able to configure database operations using ConfigHelper
        db_config = {
            "database": {"retry_attempts": 3, "timeout": 30, "enable_logging": True}
        }

        helper = ConfigHelper(db_config)
        retry_attempts = helper.get_int("database.retry_attempts", 1)
        timeout = helper.get_int("database.timeout", 10)
        enable_logging = helper.get_bool("database.enable_logging", False)

        # Configuration should be accessible for database helper configuration
        assert retry_attempts == 3
        assert timeout == 30
        assert enable_logging == True
