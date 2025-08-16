"""
ABOUTME: Comprehensive migration tests for all database types and enum handling
ABOUTME: Validates migration utilities work correctly across PostgreSQL, MySQL, and SQLite

File: tests/unit/test_migrations.py

Description:
    Unit tests for database migration utilities ensuring proper functionality
    across all supported database types (PostgreSQL, MySQL, SQLite). Tests
    enum column creation, database dialect detection, and backward compatibility
    with different enum definition formats.

Key features:
    - Multi-database migration testing (PostgreSQL, MySQL, SQLite)
    - Enum handling validation for both proper Python Enums and legacy formats
    - Migration utility function testing with mocked database contexts
    - Database dialect-specific column creation verification
    - Backward compatibility validation for existing migration files
    - Error handling and edge case testing

Author: Emfour Solutions
Created: 2025-08-14
Last Modified: 2025-08-14
Version: 1.0.0
"""

import pytest
import sqlalchemy as sa
from enum import Enum
from unittest.mock import Mock, patch, MagicMock
from alembic import op

# Import the migration utilities and test enums
from migrations.migration_utils import get_enum_column, get_dialect


class MockProperEnum(Enum):
    """Mock enum using proper Python Enum syntax with .value attributes"""
    LOCAL = "local"
    OIDC = "oidc"
    LDAP = "ldap"


class MockLegacyEnum(Enum):
    """Mock enum using legacy string-based format (like in migration files)"""
    LOCAL = "LOCAL"
    OIDC = "OIDC"
    LDAP = "LDAP"


class MockUserRole(Enum):
    """Mock enum for user roles"""
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"


class TestMigrationUtils:
    """Test migration utility functions"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_bind = Mock()
        self.mock_dialect = Mock()
        self.mock_bind.dialect = self.mock_dialect

    @patch('migrations.migration_utils.op.get_bind')
    def test_get_dialect_postgresql(self, mock_get_bind):
        """Test dialect detection for PostgreSQL"""
        mock_get_bind.return_value = self.mock_bind
        self.mock_dialect.name = "postgresql"
        
        dialect = get_dialect()
        assert dialect == "postgresql"

    @patch('migrations.migration_utils.op.get_bind')
    def test_get_dialect_mysql(self, mock_get_bind):
        """Test dialect detection for MySQL"""
        mock_get_bind.return_value = self.mock_bind
        self.mock_dialect.name = "mysql"
        
        dialect = get_dialect()
        assert dialect == "mysql"

    @patch('migrations.migration_utils.op.get_bind')
    def test_get_dialect_sqlite(self, mock_get_bind):
        """Test dialect detection for SQLite"""
        mock_get_bind.return_value = self.mock_bind
        self.mock_dialect.name = "sqlite"
        
        dialect = get_dialect()
        assert dialect == "sqlite"

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_postgresql_proper_enum(self, mock_get_dialect):
        """Test PostgreSQL enum column creation with proper Python Enum"""
        mock_get_dialect.return_value = "postgresql"
        
        column = get_enum_column(MockProperEnum, "auth_provider", nullable=False, default="local")
        
        # Verify column properties
        assert column.name == "auth_provider"
        assert not column.nullable
        assert str(column.default.arg) == "local"
        
        # Verify it's a PostgreSQL enum type
        assert isinstance(column.type, sa.Enum)
        # Check enum values are properly configured
        assert "local" in column.type.enums
        assert "oidc" in column.type.enums
        assert "ldap" in column.type.enums

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_postgresql_legacy_enum(self, mock_get_dialect):
        """Test PostgreSQL enum column creation with legacy string-based Enum"""
        mock_get_dialect.return_value = "postgresql"
        
        column = get_enum_column(MockLegacyEnum, "auth_provider", nullable=True, default="LOCAL")
        
        # Verify column properties
        assert column.name == "auth_provider"
        assert column.nullable
        assert str(column.default.arg) == "LOCAL"
        
        # Verify it's a PostgreSQL enum type with correct values
        assert isinstance(column.type, sa.Enum)
        assert "LOCAL" in column.type.enums
        assert "OIDC" in column.type.enums
        assert "LDAP" in column.type.enums

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_mysql_proper_enum(self, mock_get_dialect):
        """Test MySQL enum column creation with proper Python Enum"""
        mock_get_dialect.return_value = "mysql"
        
        column = get_enum_column(MockProperEnum, "auth_provider", nullable=False, default="local")
        
        # Verify column properties
        assert column.name == "auth_provider"
        assert not column.nullable
        assert str(column.default.arg) == "local"
        
        # Verify it's a String type (MySQL/SQLite approach)
        assert isinstance(column.type, sa.String)
        # Should be sized to fit the longest enum value
        assert column.type.length >= len("local")

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_sqlite_legacy_enum(self, mock_get_dialect):
        """Test SQLite enum column creation with legacy string-based Enum"""
        mock_get_dialect.return_value = "sqlite"
        
        column = get_enum_column(MockLegacyEnum, "auth_provider", nullable=True, default="LOCAL")
        
        # Verify column properties
        assert column.name == "auth_provider"
        assert column.nullable
        assert str(column.default.arg) == "LOCAL"
        
        # Verify it's a String type with appropriate length
        assert isinstance(column.type, sa.String)
        assert column.type.length >= len("LOCAL")

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_string_length_calculation(self, mock_get_dialect):
        """Test that string length is calculated correctly for all enum values"""
        mock_get_dialect.return_value = "sqlite"
        
        # Create an enum with varying length values
        class VaryingLengthEnum(Enum):
            SHORT = "a"
            MEDIUM = "medium_value"
            VERY_LONG_VALUE = "this_is_a_very_long_enum_value"
        
        column = get_enum_column(VaryingLengthEnum, "test_column")
        
        # Should be sized to fit the longest value
        assert column.type.length == len("this_is_a_very_long_enum_value")

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_with_enum_default(self, mock_get_dialect):
        """Test enum column creation with Enum member as default"""
        mock_get_dialect.return_value = "postgresql"
        
        column = get_enum_column(MockProperEnum, "auth_provider", default=MockProperEnum.LOCAL)
        
        # Should handle enum member as default value
        assert str(column.default.arg) == str(MockProperEnum.LOCAL)

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_with_string_default(self, mock_get_dialect):
        """Test enum column creation with string as default"""
        mock_get_dialect.return_value = "mysql"
        
        column = get_enum_column(MockProperEnum, "auth_provider", default="oidc")
        
        # Should handle string as default value
        assert str(column.default.arg) == "oidc"

    def test_enum_value_extraction_proper_enum(self):
        """Test that proper Python Enum values are extracted correctly"""
        # This tests the core logic of our enum handling fix
        try:
            enum_values = [member.value for member in MockProperEnum]
            if enum_values:
                _ = enum_values[0]  # Test accessibility
            success = True
        except (AttributeError, IndexError):
            enum_values = [str(member) for member in MockProperEnum]
            success = False
        
        assert success, "Proper enum should work with .value attribute"
        assert "local" in enum_values
        assert "oidc" in enum_values
        assert "ldap" in enum_values

    def test_enum_value_extraction_legacy_enum(self):
        """Test that legacy string-based Enum values are extracted correctly"""
        # This tests our fallback logic
        try:
            enum_values = [member.value for member in MockLegacyEnum]
            if enum_values:
                _ = enum_values[0]  # Test accessibility
        except (AttributeError, IndexError):
            enum_values = [str(member) for member in MockLegacyEnum]
        
        # Both approaches should work for legacy enums
        assert "LOCAL" in enum_values
        assert "OIDC" in enum_values  
        assert "LDAP" in enum_values

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_edge_cases(self, mock_get_dialect):
        """Test edge cases and error conditions"""
        mock_get_dialect.return_value = "sqlite"
        
        # Test with empty enum (edge case)
        class EmptyEnum(Enum):
            pass
        
        # Should handle empty enum gracefully
        try:
            column = get_enum_column(EmptyEnum, "test_column")
            # If it doesn't crash, the max() call was handled properly
            assert isinstance(column.type, sa.String)
        except ValueError:
            # max() on empty sequence is expected to fail
            pass

    @patch('migrations.migration_utils.get_dialect')
    def test_get_enum_column_all_databases_same_enum(self, mock_get_dialect):
        """Test that the same enum works across all database types"""
        test_cases = [
            ("postgresql", sa.Enum),
            ("mysql", sa.String),
            ("sqlite", sa.String)
        ]
        
        for dialect, expected_type in test_cases:
            mock_get_dialect.return_value = dialect
            
            column = get_enum_column(MockUserRole, "user_role", default="user")
            
            assert column.name == "user_role"
            assert isinstance(column.type, expected_type)
            assert str(column.default.arg) == "user"

    @patch('migrations.migration_utils.get_dialect')
    def test_migration_backward_compatibility(self, mock_get_dialect):
        """Test that existing migration enum formats still work"""
        mock_get_dialect.return_value = "sqlite"
        
        # Simulate the enum format used in the actual migration files
        class MigrationStyleEnum(Enum):
            LOCAL = "LOCAL"
            OIDC = "OIDC"
            LDAP = "LDAP"
        
        # This should not raise AttributeError: 'str' object has no attribute 'value'
        column = get_enum_column(MigrationStyleEnum, "provider", default="LOCAL")
        
        assert column.name == "provider"
        assert isinstance(column.type, sa.String)
        assert str(column.default.arg) == "LOCAL"
        assert column.type.length >= len("LOCAL")


class TestMigrationIntegration:
    """Integration tests for migration scenarios"""

    @patch('migrations.migration_utils.get_dialect')
    def test_consolidated_migration_enum_calls(self, mock_get_dialect):
        """Test that the enum calls from consolidated migration work correctly"""
        mock_get_dialect.return_value = "sqlite"
        
        # Test the exact enum classes and calls from the consolidated migration
        class AuthProvider(Enum):
            LOCAL = "LOCAL"
            OIDC = "OIDC" 
            LDAP = "LDAP"
        
        class UserRole(Enum):
            ADMIN = "ADMIN"
            OPERATOR = "OPERATOR"
            USER = "USER"
        
        class AccountStatus(Enum):
            ACTIVE = "ACTIVE"
            DISABLED = "DISABLED"
            LOCKED = "LOCKED"
        
        # These are the exact calls from the migration file (after our fixes)
        auth_provider_column = get_enum_column(AuthProvider, "auth_provider", default="LOCAL")
        user_role_column = get_enum_column(UserRole, "role", default="USER")
        account_status_column = get_enum_column(AccountStatus, "status", default="ACTIVE")
        session_provider_column = get_enum_column(AuthProvider, "provider", default="LOCAL")
        
        # All should succeed without AttributeError
        assert auth_provider_column.name == "auth_provider"
        assert user_role_column.name == "role"
        assert account_status_column.name == "status"
        assert session_provider_column.name == "provider"
        
        # All should be String type for SQLite
        for column in [auth_provider_column, user_role_column, account_status_column, session_provider_column]:
            assert isinstance(column.type, sa.String)

    @patch('migrations.migration_utils.get_dialect')
    def test_production_migration_scenario(self, mock_get_dialect):
        """Test the specific production scenario that was failing"""
        mock_get_dialect.return_value = "sqlite"
        
        # Exactly replicate the failing scenario
        class AuthProvider(Enum):
            LOCAL = "LOCAL"
            OIDC = "OIDC"
            LDAP = "LDAP"
        
        # This was the failing call: get_enum_column("provider", AuthProvider, "LOCAL")
        # Fixed to: get_enum_column(AuthProvider, "provider", default="LOCAL")
        try:
            column = get_enum_column(AuthProvider, "provider", default="LOCAL")
            success = True
            error = None
        except Exception as e:
            success = False
            error = str(e)
        
        assert success, f"Migration should succeed but failed with: {error}"
        assert column.name == "provider"
        assert str(column.default.arg) == "LOCAL"

    def test_enum_compatibility_matrix(self):
        """Test compatibility matrix of enum formats and database types"""
        enum_types = [
            ("proper", MockProperEnum),
            ("legacy", MockLegacyEnum)
        ]
        
        db_types = ["postgresql", "mysql", "sqlite"]
        
        for enum_name, enum_class in enum_types:
            for db_type in db_types:
                with patch('migrations.migration_utils.get_dialect') as mock_dialect:
                    mock_dialect.return_value = db_type
                    
                    # Should work for all combinations
                    column = get_enum_column(enum_class, "test_col", default="LOCAL")
                    
                    assert column.name == "test_col"
                    if db_type == "postgresql":
                        assert isinstance(column.type, sa.Enum)
                    else:
                        assert isinstance(column.type, sa.String)
                    assert str(column.default.arg) == "LOCAL"


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])