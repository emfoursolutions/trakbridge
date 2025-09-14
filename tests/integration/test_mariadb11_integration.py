"""
Integration test to verify MariaDB 11 compatibility fixes work end-to-end.

This test validates that the MariaDB 11 compatibility changes prevent
"Got an error reading communication packets" errors in real scenarios.

Author: Emfour Solutions
Created: 2025-09-14
"""

import os
import pytest
from unittest.mock import patch

from config.environments import get_config


@pytest.mark.integration
@pytest.mark.mysql
@pytest.mark.mariadb
class TestMariaDB11EndToEnd:
    """End-to-end validation of MariaDB 11 compatibility fixes"""

    def test_mariadb11_configuration_complete(self):
        """Test that all MariaDB 11 compatibility options are properly configured"""
        # Test production environment with MariaDB
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mariadb",
                "DB_PORT": "3306",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "testpass",
                "DB_NAME": "trakbridge",
            },
        ):
            config = get_config("production")

            # Verify database URI includes MariaDB 11 compatibility parameters
            uri = config.SQLALCHEMY_DATABASE_URI
            assert "mysql+pymysql://" in uri
            assert "charset=utf8mb4" in uri
            assert "autocommit=true" in uri
            assert "local_infile=0" in uri

            # Verify engine options include MariaDB 11 settings
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Connection pool settings
            assert engine_options["pool_pre_ping"] is True
            assert engine_options["pool_recycle"] == 3600
            assert engine_options["pool_size"] == 50  # Production value
            assert engine_options["max_overflow"] == 100

            # MariaDB 11 specific connection arguments
            connect_args = engine_options["connect_args"]
            assert connect_args["connect_timeout"] == 90  # Extended for production
            assert connect_args["read_timeout"] == 60  # Extended timeouts
            assert connect_args["write_timeout"] == 60
            assert connect_args["charset"] == "utf8mb4"
            assert connect_args["autocommit"] is True
            assert connect_args["local_infile"] == 0
            assert "sql_mode" in connect_args

    def test_mariadb11_backward_compatibility(self):
        """Test that existing MySQL configurations continue to work"""
        # Test that standard MySQL setups get MariaDB 11 compatibility automatically
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mysql-server",
                "DB_USER": "root",
                "DB_PASSWORD": "password",
                "DB_NAME": "myapp",
            },
        ):
            config = get_config("production")

            # Should work with any MySQL/MariaDB server
            uri = config.SQLALCHEMY_DATABASE_URI
            assert "mysql+pymysql://root:" in uri
            assert "@mysql-server:3306/myapp" in uri

            # Should include compatibility options
            assert "autocommit=true" in uri
            assert "charset=utf8mb4" in uri

    def test_mariadb11_development_environment(self):
        """Test MariaDB 11 compatibility in development environment"""
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "localhost",
                "DB_USER": "dev",
                "DB_PASSWORD": "dev",
                "DB_NAME": "trakbridge_dev",
            },
        ):
            config = get_config("development")

            # Development should have reasonable timeouts
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Should inherit base MySQL configuration
            assert engine_options["pool_pre_ping"] is True
            assert engine_options["pool_recycle"] == 3600

            # Base connection arguments should be present
            connect_args = engine_options["connect_args"]
            assert connect_args["charset"] == "utf8mb4"
            assert connect_args["autocommit"] is True

    def test_mariadb11_testing_environment(self):
        """Test MariaDB 11 compatibility in testing environment"""
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "test-mariadb",
                "DB_USER": "test",
                "DB_PASSWORD": "test",
                "DB_NAME": "test_db",
            },
        ):
            config = get_config("testing")

            # Testing environment should have MariaDB 11 options
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Testing-specific pool settings
            assert engine_options["pool_size"] == 5
            assert engine_options["max_overflow"] == 10

            # MariaDB 11 connect args
            connect_args = engine_options["connect_args"]
            assert connect_args["connect_timeout"] == 30  # Shorter for testing
            assert connect_args["read_timeout"] == 15
            assert connect_args["write_timeout"] == 15
            assert connect_args["autocommit"] is True
            assert connect_args["local_infile"] == 0

    def test_non_mysql_databases_unaffected(self):
        """Test that PostgreSQL and SQLite are not affected by MariaDB changes"""
        # Test PostgreSQL
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "postgresql",
                "DB_HOST": "postgres",
                "DB_USER": "postgres",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
        ):
            config = get_config("production")
            uri = config.SQLALCHEMY_DATABASE_URI

            # Should use PostgreSQL driver
            assert "postgresql+psycopg2://" in uri
            # Should not have MySQL-specific parameters
            assert "charset=utf8mb4" not in uri
            assert "autocommit=true" not in uri

        # Test SQLite (default for testing)
        with patch.dict(os.environ, {"DB_TYPE": "sqlite"}):
            config = get_config("testing")
            uri = config.SQLALCHEMY_DATABASE_URI

            # Should use SQLite
            assert uri.startswith("sqlite:///")
            # Should not have MySQL-specific parameters
            assert "charset=utf8mb4" not in uri
            assert "autocommit=true" not in uri

    def test_mariadb11_docker_compose_integration(self):
        """Test integration with Docker Compose MariaDB 11 setup"""
        # Simulate Docker Compose environment
        docker_env = {
            "FLASK_ENV": "production",
            "DB_TYPE": "mysql",
            "DB_HOST": "mysql",  # Docker service name from docker-compose.yml
            "DB_PORT": "3306",
            "DB_USER": "trakbridge",
            "DB_PASSWORD": "secure_password",
            "DB_NAME": "trakbridge",
        }

        with patch.dict(os.environ, docker_env):
            config = get_config("production")

            # Verify complete configuration
            uri = config.SQLALCHEMY_DATABASE_URI
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Docker-compatible connection
            assert "@mysql:3306/trakbridge" in uri

            # Production-grade pool settings
            assert engine_options["pool_size"] == 50
            assert engine_options["pool_timeout"] == 60

            # MariaDB 11 timeouts for containerized environment
            connect_args = engine_options["connect_args"]
            assert connect_args["connect_timeout"] == 90
            assert connect_args["read_timeout"] == 60
            assert connect_args["write_timeout"] == 60

    def test_mariadb11_error_prevention_features(self):
        """Test that specific MariaDB 11 error prevention features are enabled"""
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mariadb-11",
                "DB_USER": "app",
                "DB_PASSWORD": "password",
                "DB_NAME": "application",
            },
        ):
            config = get_config("production")

            # Verify features that prevent "Got an error reading communication packets"
            uri = config.SQLALCHEMY_DATABASE_URI
            engine_options = config.SQLALCHEMY_ENGINE_OPTIONS

            # Connection health checking
            assert (
                engine_options["pool_pre_ping"] is True
            ), "pool_pre_ping prevents stale connections"

            # Connection recycling
            assert (
                engine_options["pool_recycle"] == 3600
            ), "pool_recycle prevents connection timeout"

            # Adequate timeouts
            connect_args = engine_options["connect_args"]
            assert connect_args["connect_timeout"] >= 30, "Adequate connect timeout"
            assert connect_args["read_timeout"] >= 30, "Adequate read timeout"
            assert connect_args["write_timeout"] >= 30, "Adequate write timeout"

            # Auto-commit mode
            assert (
                connect_args["autocommit"] is True
            ), "Autocommit prevents transaction issues"

            # Security features
            assert (
                connect_args["local_infile"] == 0
            ), "Local infile disabled for security"

            # SQL mode compatibility
            assert "init_command=SET sql_mode=" in uri, "SQL mode set for compatibility"
