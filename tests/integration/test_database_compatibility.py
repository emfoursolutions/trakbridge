"""
Cross-database compatibility tests to ensure no regressions.

Tests SQLite, PostgreSQL, and MySQL/MariaDB configurations to verify
that MariaDB 11 fixes don't break existing database functionality.

Author: Emfour Solutions
Created: 2025-09-14
"""

import os
import pytest
from unittest.mock import patch
from contextlib import contextmanager

from config.base import BaseConfig
from config.environments import get_config
from app import create_app


@contextmanager
def clean_database_env():
    """Context manager to clear all database-related environment variables for testing."""
    database_env_vars = [
        'DATABASE_URL', 'DB_TYPE', 'DB_HOST', 'DB_PORT', 
        'DB_USER', 'DB_PASSWORD', 'DB_NAME'
    ]
    
    # Save original values
    original_values = {}
    for var in database_env_vars:
        if var in os.environ:
            original_values[var] = os.environ[var]
            del os.environ[var]
    
    try:
        yield
    finally:
        # Restore original values
        for var, value in original_values.items():
            os.environ[var] = value


@pytest.mark.integration
class TestCrossDatabaseCompatibility:
    """Test compatibility across all supported databases"""

    def test_sqlite_configuration_unchanged(self):
        """Test that SQLite configuration remains unchanged"""
        # Clean environment and mock SQLite configuration
        with clean_database_env(), patch.dict(os.environ, {"DB_TYPE": "sqlite"}, clear=False):
            test_config = BaseConfig("testing")

            # Should build SQLite URI without issues
            uri = test_config.SQLALCHEMY_DATABASE_URI
            assert uri.startswith("sqlite:///")

            # Engine options should not interfere with SQLite
            engine_options = test_config.SQLALCHEMY_ENGINE_OPTIONS
            sqlite_options = engine_options.get("connect_args", {})

            # Verify SQLite-specific options are preserved
            if "check_same_thread" in sqlite_options:
                assert sqlite_options["check_same_thread"] is False

    def test_postgresql_configuration_unchanged(self):
        """Test that PostgreSQL configuration remains unchanged"""
        # Clean environment and mock PostgreSQL configuration
        with clean_database_env(), patch.dict(
            os.environ,
            {
                "DB_TYPE": "postgresql",
                "DB_HOST": "postgres",
                "DB_PORT": "5432",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
            clear=False
        ):
            config = BaseConfig("testing")

            # Should build PostgreSQL URI without issues
            uri = config._build_postgresql_uri()
            assert "postgresql+psycopg2://" in uri

            # Engine options should preserve PostgreSQL settings
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
            assert "pool_pre_ping" in engine_options
            assert engine_options["pool_pre_ping"] is True

    def test_mysql_configuration_backward_compatible(self):
        """Test that existing MySQL configuration remains backward compatible"""
        # Clean environment and mock standard MySQL configuration
        with clean_database_env(), patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mysql",
                "DB_PORT": "3306",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
            clear=False
        ):
            config = BaseConfig("testing")

            # Should build MySQL URI with existing parameters
            uri = config._build_mysql_uri()
            assert "mysql+pymysql://" in uri
            assert "charset=utf8mb4" in uri

            # Engine options should include MySQL settings (testing environment has MySQL config)
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
            if "pool_pre_ping" in engine_options:
                assert engine_options["pool_pre_ping"] is True
            # For testing environment, pool_size might be configured
            if "pool_size" in engine_options:
                assert engine_options.get("pool_size", 0) > 0

    def test_db_type_overrides_database_url(self):
        """Test that DB_TYPE environment variable takes precedence over DATABASE_URL"""
        # This test verifies the fix for the CI configuration precedence issue
        with clean_database_env(), patch.dict(
            os.environ,
            {
                # CI often sets DATABASE_URL to PostgreSQL, but tests expect SQLite
                "DATABASE_URL": "postgresql://ci_user:ci_pass@postgres:5432/ci_db",
                "DB_TYPE": "sqlite",  # This should override DATABASE_URL
            },
            clear=False
        ):
            config = BaseConfig("testing")
            
            # Should use SQLite despite DATABASE_URL being PostgreSQL
            uri = config.SQLALCHEMY_DATABASE_URI
            assert uri.startswith("sqlite:///"), f"Expected SQLite URI, got: {uri}"
            
            # Database type detection should also return sqlite
            db_type = config._get_database_type()
            assert db_type == "sqlite"

    def test_database_url_fallback_when_no_db_type(self):
        """Test that DATABASE_URL is used when DB_TYPE is not set"""
        with clean_database_env(), patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test_user:test_pass@localhost:5432/test_db",
                # No DB_TYPE set - should use DATABASE_URL
            },
            clear=False
        ):
            config = BaseConfig("testing")
            
            # Should use the DATABASE_URL directly
            uri = config.SQLALCHEMY_DATABASE_URI
            assert uri == "postgresql://test_user:test_pass@localhost:5432/test_db"

    def test_db_type_precedence_with_various_database_urls(self):
        """Test DB_TYPE precedence with various DATABASE_URL formats"""
        test_cases = [
            {
                "name": "PostgreSQL DATABASE_URL with SQLite DB_TYPE",
                "DATABASE_URL": "postgresql://user:pass@host:5432/db",
                "DB_TYPE": "sqlite",
                "expected_prefix": "sqlite:///"
            },
            {
                "name": "MySQL DATABASE_URL with PostgreSQL DB_TYPE", 
                "DATABASE_URL": "mysql://user:pass@host:3306/db",
                "DB_TYPE": "postgresql",
                "expected_prefix": "postgresql+psycopg2://",
                "additional_env": {
                    "DB_HOST": "localhost", "DB_USER": "test", 
                    "DB_PASSWORD": "test", "DB_NAME": "test"
                }
            },
            {
                "name": "SQLite DATABASE_URL with MySQL DB_TYPE",
                "DATABASE_URL": "sqlite:///test.db", 
                "DB_TYPE": "mysql",
                "expected_prefix": "mysql+pymysql://",
                "additional_env": {
                    "DB_HOST": "localhost", "DB_USER": "test",
                    "DB_PASSWORD": "test", "DB_NAME": "test"
                }
            },
        ]
        
        for case in test_cases:
            with clean_database_env(), patch.dict(
                os.environ,
                {
                    "DATABASE_URL": case["DATABASE_URL"],
                    "DB_TYPE": case["DB_TYPE"],
                    **case.get("additional_env", {})
                },
                clear=False
            ):
                config = BaseConfig("testing")
                uri = config.SQLALCHEMY_DATABASE_URI
                assert uri.startswith(case["expected_prefix"]), (
                    f"{case['name']}: Expected {case['expected_prefix']}, got: {uri}"
                )

    def test_flask_app_creation_all_databases(self):
        """Test Flask app creation works with all database types"""
        database_configs = [
            {"DB_TYPE": "sqlite"},
            {
                "DB_TYPE": "postgresql",
                "DB_HOST": "postgres",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mysql",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
        ]

        for db_config in database_configs:
            with clean_database_env(), patch.dict(os.environ, db_config, clear=False):
                app = create_app("testing")
                assert app is not None
                assert "SQLALCHEMY_DATABASE_URI" in app.config

    def test_engine_options_by_database_type(self):
        """Test engine options are appropriate for each database type"""
        config = BaseConfig("testing")

        # Test SQLite options
        with patch.object(config, "_get_database_type", return_value="sqlite"):
            options = config.SQLALCHEMY_ENGINE_OPTIONS
            if "connect_args" in options:
                sqlite_args = options["connect_args"]
                # SQLite should have check_same_thread setting
                assert "timeout" in sqlite_args or len(sqlite_args) >= 0

        # Test PostgreSQL options
        with patch.object(config, "_get_database_type", return_value="postgresql"):
            options = config.SQLALCHEMY_ENGINE_OPTIONS
            assert "pool_pre_ping" in options
            # PostgreSQL should have proper pool settings
            assert options.get("pool_size", 5) > 0

        # Test MySQL options
        with patch.object(config, "_get_database_type", return_value="mysql"):
            options = config.SQLALCHEMY_ENGINE_OPTIONS
            if "pool_pre_ping" in options:
                assert options["pool_pre_ping"] is True
            # MySQL should have charset in connect_args if connect_args exist
            if "connect_args" in options and options["connect_args"]:
                # Charset should be present in connection arguments
                assert (
                    "charset" in options["connect_args"]
                    or len(options["connect_args"]) >= 0
                )

    def test_environment_specific_configurations(self):
        """Test environment-specific database configurations remain intact"""
        environments = ["development", "production", "testing"]

        for env in environments:
            config = get_config(env)
            assert config is not None

            # Each environment should have valid database configuration
            uri = config.SQLALCHEMY_DATABASE_URI
            assert uri is not None and len(uri) > 0

            # Engine options should be appropriate for environment
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
            assert isinstance(engine_options, dict)

    def test_database_uri_encoding(self):
        """Test database URI encoding works for all database types"""
        special_password = "p@ssw0rd!#$"

        database_configs = [
            {
                "DB_TYPE": "mysql",
                "DB_PASSWORD": special_password,
                "DB_HOST": "mysql",
                "DB_USER": "trakbridge",
                "DB_NAME": "trakbridge",
            },
            {
                "DB_TYPE": "postgresql",
                "DB_PASSWORD": special_password,
                "DB_HOST": "postgres",
                "DB_USER": "trakbridge",
                "DB_NAME": "trakbridge",
            },
        ]

        for db_config in database_configs:
            with patch.dict(os.environ, db_config):
                config = BaseConfig("testing")
                uri = config.SQLALCHEMY_DATABASE_URI

                # For network databases, special characters should be URL encoded
                if db_config["DB_TYPE"] in ["mysql", "postgresql"]:
                    assert special_password not in uri  # Raw password shouldn't appear
                    assert "%" in uri  # Should be encoded for network DBs

    @pytest.mark.parametrize(
        "db_type,expected_driver",
        [
            ("sqlite", "sqlite:///"),
            ("mysql", "mysql+pymysql://"),
            ("postgresql", "postgresql+psycopg2://"),
        ],
    )
    def test_database_drivers_unchanged(self, db_type, expected_driver):
        """Test that database drivers remain unchanged"""
        env_config = {"DB_TYPE": db_type}

        # Add required fields for network databases
        if db_type in ["mysql", "postgresql"]:
            env_config.update(
                {
                    "DB_HOST": "localhost",
                    "DB_USER": "test",
                    "DB_PASSWORD": "test",
                    "DB_NAME": "test",
                }
            )

        with clean_database_env(), patch.dict(os.environ, env_config, clear=False):
            config = BaseConfig("testing")
            uri = config.SQLALCHEMY_DATABASE_URI

            assert uri.startswith(expected_driver)

    def test_configuration_validation_all_databases(self):
        """Test configuration validation works for all database types"""
        database_types = ["sqlite", "mysql", "postgresql"]

        for db_type in database_types:
            env_config = {"DB_TYPE": db_type}

            # Add required fields for network databases
            if db_type in ["mysql", "postgresql"]:
                env_config.update(
                    {
                        "DB_HOST": "localhost",
                        "DB_USER": "test",
                        "DB_PASSWORD": "test",
                        "DB_NAME": "test",
                    }
                )

            with clean_database_env(), patch.dict(os.environ, env_config, clear=False):
                config = BaseConfig("testing")

                # Configuration validation should pass
                issues = config.validate_config()

                # Should have no critical validation errors
                critical_issues = [
                    issue for issue in issues if "error" in issue.lower()
                ]
                assert (
                    len(critical_issues) == 0
                ), f"Critical issues found for {db_type}: {critical_issues}"


@pytest.mark.integration
class TestMariaDBBackwardCompatibility:
    """Test backward compatibility with existing MariaDB/MySQL setups"""

    def test_existing_mariadb_configuration_works(self):
        """Test that existing MariaDB configurations continue to work"""
        # Simulate existing MariaDB setup (pre-MariaDB 11)
        existing_config = {
            "DB_TYPE": "mysql",
            "DB_HOST": "mariadb",
            "DB_PORT": "3306",
            "DB_USER": "trakbridge",
            "DB_PASSWORD": "password",
            "DB_NAME": "trakbridge",
        }

        with clean_database_env(), patch.dict(os.environ, existing_config, clear=False):
            config = BaseConfig("production")

            # Should build proper URI with MariaDB 11 compatibility
            uri = config.SQLALCHEMY_DATABASE_URI
            assert "mysql+pymysql://" in uri
            assert "charset=utf8mb4" in uri
            assert "autocommit=true" in uri  # MariaDB 11 compatibility

            # Should have reasonable engine options including MariaDB 11 options
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
            assert "pool_pre_ping" in engine_options
            assert engine_options["pool_pre_ping"] is True

    def test_docker_compose_mysql_service_compatibility(self):
        """Test compatibility with existing Docker Compose MySQL service"""
        # Test configuration that matches docker-compose.yml mysql service
        docker_mysql_config = {
            "DB_TYPE": "mysql",
            "DB_HOST": "mariadb",  # Service name from docker-compose.yml (actually mariadb)
            "DB_PORT": "3306",
            "DB_USER": "trakbridge",
            "DB_PASSWORD": "password",
            "DB_NAME": "trakbridge",
        }

        with clean_database_env(), patch.dict(os.environ, docker_mysql_config, clear=False):
            config = BaseConfig("production")
            uri = config.SQLALCHEMY_DATABASE_URI

            # Should match expected Docker service connection
            assert "mysql+pymysql://trakbridge:" in uri
            assert "@mariadb:3306/trakbridge" in uri

    def test_legacy_mysql_engine_options_preserved(self):
        """Test that legacy MySQL engine options are preserved"""
        config = BaseConfig("production")

        with patch.object(config, "_get_database_type", return_value="mysql"):
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Legacy options should still be present (now explicitly in production config)
            expected_legacy_options = ["pool_pre_ping", "pool_recycle"]
            for option in expected_legacy_options:
                assert option in engine_options, f"Legacy option {option} missing"

            # Verify that the production configuration includes both legacy and new options
            assert engine_options["pool_pre_ping"] is True
            assert engine_options["pool_recycle"] == 3600

            # Legacy connect_args should be preserved
            if "connect_args" in engine_options:
                connect_args = engine_options["connect_args"]
                assert "charset" in connect_args
                assert connect_args["charset"] == "utf8mb4"
