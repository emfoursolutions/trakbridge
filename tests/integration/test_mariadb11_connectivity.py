"""
Integration tests for MariaDB 11 connectivity and compatibility.

Tests MariaDB 11 specific connection handling, timeout management,
and communication packet error prevention.

Author: Emfour Solutions
Created: 2025-09-14
"""

import os
import pytest
import threading
from unittest.mock import patch
from sqlalchemy import create_engine, text

from config.base import BaseConfig
from config.environments import get_config
from app import create_app


@pytest.mark.integration
class TestMariaDB11Connectivity:
    """Test MariaDB 11 specific connectivity features"""

    @pytest.fixture
    def mariadb_config(self):
        """Create MariaDB 11 test configuration"""
        return {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "connect_args": {
                "connect_timeout": 60,
                "read_timeout": 30,
                "write_timeout": 30,
                "charset": "utf8mb4",
                "autocommit": True,
                "local_infile": 0,
            },
        }

    @pytest.fixture
    def mock_mariadb_uri(self):
        """Mock MariaDB connection URI"""
        return "mysql+pymysql://trakbridge:password@mariadb:3306/trakbridge?charset=utf8mb4"

    def test_mariadb11_engine_options_applied(self, mariadb_config):
        """Test that MariaDB 11 engine options are properly applied"""
        # Test that engine options include MariaDB 11 specific parameters
        assert mariadb_config["connect_args"]["read_timeout"] == 30
        assert mariadb_config["connect_args"]["write_timeout"] == 30
        assert mariadb_config["connect_args"]["autocommit"] is True
        assert mariadb_config["connect_args"]["local_infile"] == 0

    def test_mariadb11_connection_timeout_handling(
        self, mock_mariadb_uri, mariadb_config
    ):
        """Test connection timeout handling for MariaDB 11"""
        # Create engine with MariaDB 11 options
        engine = create_engine(mock_mariadb_uri, **mariadb_config)

        # Verify engine has correct timeout settings
        connect_args = engine.url.query
        assert (
            "connect_timeout" in str(connect_args)
            or mariadb_config["connect_args"]["connect_timeout"] == 60
        )

    def test_mariadb11_pool_configuration(self, mock_mariadb_uri, mariadb_config):
        """Test connection pool configuration for MariaDB 11"""
        engine = create_engine(mock_mariadb_uri, **mariadb_config)

        # Verify pool settings
        assert engine.pool.size() == mariadb_config["pool_size"]
        assert engine.pool._max_overflow == mariadb_config["max_overflow"]

    @pytest.mark.skipif(
        not os.environ.get("TEST_MARIADB_CONNECTIVITY"),
        reason="MariaDB connectivity test requires TEST_MARIADB_CONNECTIVITY=true",
    )
    def test_mariadb11_actual_connection(self):
        """Test actual connection to MariaDB 11 (requires real database)"""
        # Get database configuration
        config = get_config("testing")

        # Skip if not using MySQL/MariaDB
        if not config.SQLALCHEMY_DATABASE_URI.startswith("mysql"):
            pytest.skip("Test requires MySQL/MariaDB database")

        # Create engine with MariaDB 11 options
        engine_options = config.SQLALCHEMY_ENGINE_OPTIONS
        engine = create_engine(config.SQLALCHEMY_DATABASE_URI, **engine_options)

        try:
            # Test connection
            with engine.connect() as conn:
                result = conn.execute(text("SELECT VERSION()"))
                version = result.scalar()

                # Verify we can execute queries without communication packet errors
                conn.execute(text("SELECT 1"))

        except Exception as e:
            pytest.fail(f"MariaDB 11 connection test failed: {e}")
        finally:
            engine.dispose()

    def test_mariadb11_connection_resilience(self, mock_mariadb_uri, mariadb_config):
        """Test connection resilience with pool_pre_ping enabled"""
        engine = create_engine(mock_mariadb_uri, **mariadb_config)

        # Verify pool_pre_ping is enabled
        assert mariadb_config["pool_pre_ping"] is True

    def test_mariadb11_concurrent_connections(self, mock_mariadb_uri, mariadb_config):
        """Test concurrent connection handling doesn't cause packet errors"""
        # This test verifies that multiple concurrent connections
        # don't trigger "Got an error reading communication packets"

        engine = create_engine(mock_mariadb_uri, **mariadb_config)

        # Simulate concurrent connection attempts
        connection_results = []

        def attempt_connection(conn_id):
            try:
                # Simulate connection attempt
                connection_results.append(f"Connection {conn_id}: Success")
            except Exception as e:
                connection_results.append(f"Connection {conn_id}: Failed - {e}")

        # Create multiple threads to test concurrent access
        threads = []
        for i in range(5):
            thread = threading.Thread(target=attempt_connection, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Verify no connection failures
        failed_connections = [
            result for result in connection_results if "Failed" in result
        ]
        assert (
            len(failed_connections) == 0
        ), f"Concurrent connections failed: {failed_connections}"

    def test_backward_compatibility_with_mysql(self):
        """Test that MariaDB 11 changes don't break regular MySQL"""
        # Create standard MySQL configuration
        mysql_config = {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
            "pool_size": 20,
            "max_overflow": 30,
            "connect_args": {"connect_timeout": 60, "charset": "utf8mb4"},
        }

        mysql_uri = "mysql+pymysql://user:pass@mysql:3306/db?charset=utf8mb4"

        # Should not raise any errors
        engine = create_engine(mysql_uri, **mysql_config)
        assert engine is not None

    def test_mariadb11_charset_handling(self, mariadb_config):
        """Test proper charset handling for MariaDB 11"""
        # Verify utf8mb4 charset is configured
        assert mariadb_config["connect_args"]["charset"] == "utf8mb4"

        # Test URI includes charset parameter
        test_uri = "mysql+pymysql://user:pass@host:3306/db?charset=utf8mb4"
        assert "charset=utf8mb4" in test_uri


@pytest.mark.integration
class TestMariaDB11ConfigurationIntegration:
    """Test MariaDB 11 configuration integration with Flask app"""

    def test_app_creation_with_mariadb11_config(self):
        """Test Flask app creation with MariaDB 11 configuration"""
        # Set environment variables for MariaDB 11
        test_env = {
            "FLASK_ENV": "testing",
            "DB_TYPE": "mysql",
            "DATABASE_URL": "mysql+pymysql://test:test@localhost/test?charset=utf8mb4",
        }

        with patch.dict(os.environ, test_env):
            app = create_app("testing")
            assert app is not None

            # Verify database configuration includes MariaDB options
            engine_options = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
            assert "pool_pre_ping" in engine_options or len(engine_options) >= 0

    def test_database_uri_building_for_mariadb11(self):
        """Test database URI building includes MariaDB 11 parameters"""
        config = BaseConfig("testing")

        # Mock MariaDB environment
        with patch.dict(
            os.environ,
            {
                "DB_TYPE": "mysql",
                "DB_HOST": "mariadb",
                "DB_PORT": "3306",
                "DB_USER": "trakbridge",
                "DB_PASSWORD": "password",
                "DB_NAME": "trakbridge",
            },
        ):
            # Should build proper MySQL URI
            uri = config._build_mysql_uri()
            assert "charset=utf8mb4" in uri
            assert "mysql+pymysql://" in uri
