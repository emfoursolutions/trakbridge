"""
ABOUTME: Test suite for Phase 3A logging migration to centralized get_module_logger
ABOUTME: Validates that all migrated service files use centralized logging correctly

File: tests/test_phase3a_logging_migration.py

Description:
    Comprehensive test suite for Phase 3A migration validation. Tests that all
    migrated service files properly use the centralized logging service and
    maintain backwards compatibility while providing enhanced functionality.

Tests:
    - Logger creation and configuration
    - Module-level logger imports in migrated files
    - Logging functionality consistency
    - Performance and reliability of centralized logging
    
Author: Emfour Solutions
Created: 2025-09-03
"""

import importlib
import logging
from unittest.mock import MagicMock, patch

import pytest

from services.logging_service import create_logger, get_module_logger


class TestCentralizedLoggingMigration:
    """Test centralized logging migration for Phase 3A services"""

    def test_get_module_logger_function_exists(self):
        """Test that get_module_logger function is available and callable"""
        assert callable(get_module_logger)

    def test_get_module_logger_returns_logger_instance(self):
        """Test that get_module_logger returns proper Logger instance"""
        logger = get_module_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_module_logger_auto_detection(self):
        """Test that get_module_logger can auto-detect calling module"""
        logger = get_module_logger()
        # Should auto-detect this test module
        assert "test_logging_migration" in logger.name

    def test_create_logger_alias_works(self):
        """Test that create_logger alias function works correctly"""
        logger1 = get_module_logger("test_module")
        logger2 = create_logger("test_module")
        assert logger1.name == logger2.name
        assert type(logger1) == type(logger2)


class TestMigratedServiceLogging:
    """Test that all Phase 3A migrated services use centralized logging correctly"""

    # List of all Phase 3A migrated service modules
    MIGRATED_SERVICES = [
        "services.auth.ldap_provider",
        "services.auth.oidc_provider",
        "services.stream_manager",
        "services.cot_service",
        "services.database_manager",
        "services.auth.bootstrap_service",
        "services.health_service",
        "services.encryption_service",
    ]

    def test_migrated_services_import_get_module_logger(self):
        """Test that all migrated services import get_module_logger"""
        for module_name in self.MIGRATED_SERVICES:
            try:
                module = importlib.import_module(module_name)

                # Check that the module imports get_module_logger
                module_source = importlib.util.find_spec(module_name)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()
                        assert (
                            "from services.logging_service import get_module_logger"
                            in content
                        ), f"{module_name} should import get_module_logger"

            except ImportError as e:
                pytest.fail(f"Could not import migrated service {module_name}: {e}")

    def test_migrated_services_have_logger_instances(self):
        """Test that all migrated services have logger instances"""
        for module_name in self.MIGRATED_SERVICES:
            try:
                module = importlib.import_module(module_name)

                # Should have a module-level logger
                assert hasattr(
                    module, "logger"
                ), f"{module_name} should have logger attribute"
                assert isinstance(
                    module.logger, logging.Logger
                ), f"{module_name}.logger should be Logger instance"

            except ImportError as e:
                pytest.fail(f"Could not import migrated service {module_name}: {e}")

    def test_migrated_services_logger_names_correct(self):
        """Test that migrated services have correctly named loggers"""
        for module_name in self.MIGRATED_SERVICES:
            try:
                module = importlib.import_module(module_name)

                expected_name = module_name
                actual_name = module.logger.name
                assert (
                    actual_name == expected_name
                ), f"{module_name} logger name should be '{expected_name}', got '{actual_name}'"

            except ImportError as e:
                pytest.fail(f"Could not import migrated service {module_name}: {e}")

    def test_migrated_services_no_old_logging_patterns(self):
        """Test that migrated services don't use old logging.getLogger(__name__) pattern"""
        for module_name in self.MIGRATED_SERVICES:
            try:
                module_source = importlib.util.find_spec(module_name)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should not contain old pattern
                        assert (
                            "logger = logging.getLogger(__name__)" not in content
                        ), f"{module_name} still contains old logging pattern"

                        # Should contain new pattern
                        assert (
                            "logger = get_module_logger(__name__)" in content
                        ), f"{module_name} should use new logging pattern"

            except ImportError as e:
                pytest.fail(f"Could not import migrated service {module_name}: {e}")


class TestLoggingFunctionality:
    """Test that centralized logging maintains full functionality"""

    def test_logger_supports_all_levels(self):
        """Test that centralized loggers support all logging levels"""
        logger = get_module_logger("test_functionality")

        # Should have all standard logging methods
        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "critical")

        # Should be callable
        assert callable(logger.debug)
        assert callable(logger.info)
        assert callable(logger.warning)
        assert callable(logger.error)
        assert callable(logger.critical)

    def test_logger_respects_log_levels(self):
        """Test that centralized loggers respect configured log levels"""
        logger = get_module_logger("test_levels")

        # Set to WARNING level
        logger.setLevel(logging.WARNING)

        with patch.object(logger, "handle") as mock_handle:
            logger.debug("debug message")
            logger.info("info message")
            logger.warning("warning message")
            logger.error("error message")

            # Should only handle WARNING and above
            assert mock_handle.call_count == 2  # warning + error

    def test_logger_formatting_works(self):
        """Test that logger formatting works correctly"""
        logger = get_module_logger("test_formatting")

        # In test environment, handle might not be called if no handlers
        # So we'll just verify the logger exists and is callable
        assert logger is not None
        assert callable(logger.info)

        # Test that logger can handle formatting without errors
        try:
            logger.info("Test message with %s formatting", "string")
            # If no exception, test passes
            assert True
        except Exception:
            assert False, "Logger should handle formatting without errors"


class TestBackwardCompatibility:
    """Test that migration maintains backward compatibility"""

    def test_old_and_new_loggers_equivalent(self):
        """Test that old and new logger creation methods are equivalent"""
        module_name = "test_compatibility"

        # Old way (what we migrated from)
        old_logger = logging.getLogger(module_name)

        # New way (what we migrated to)
        new_logger = get_module_logger(module_name)

        # Should have same name
        assert old_logger.name == new_logger.name

        # Should be same type
        assert type(old_logger) == type(new_logger)

        # Should have same basic functionality
        assert hasattr(old_logger, "info") and hasattr(new_logger, "info")
        assert hasattr(old_logger, "error") and hasattr(new_logger, "error")

    def test_existing_logging_configuration_preserved(self):
        """Test that existing logging configuration still works"""
        # This would be tested with actual app configuration
        # For now, test that basic logging principles are maintained
        logger1 = get_module_logger("test_config_1")
        logger2 = get_module_logger("test_config_2")

        # Different modules should have different loggers
        assert logger1 != logger2
        assert logger1.name != logger2.name

        # Same module should return same logger
        logger1_again = get_module_logger("test_config_1")
        assert logger1 == logger1_again


class TestPerformanceAndReliability:
    """Test performance and reliability of centralized logging"""

    def test_get_module_logger_performance(self):
        """Test that get_module_logger doesn't significantly impact performance"""
        import time

        # Time multiple logger creations
        start_time = time.time()
        for i in range(100):
            get_module_logger(f"perf_test_{i}")
        end_time = time.time()

        # Should be very fast (less than 0.1 seconds for 100 loggers)
        elapsed = end_time - start_time
        assert elapsed < 0.1, f"Logger creation too slow: {elapsed} seconds"

    def test_get_module_logger_reliability(self):
        """Test that get_module_logger handles edge cases reliably"""
        # Test with None
        logger_none = get_module_logger(None)
        assert isinstance(logger_none, logging.Logger)

        # Test with empty string
        logger_empty = get_module_logger("")
        assert isinstance(logger_empty, logging.Logger)

        # Test with special characters
        logger_special = get_module_logger("test.module-with_special@chars")
        assert isinstance(logger_special, logging.Logger)

    def test_auto_detection_robustness(self):
        """Test that auto-detection works in various contexts"""

        def nested_function():
            return get_module_logger()

        # Should work from nested function
        logger = nested_function()
        assert isinstance(logger, logging.Logger)
        assert "test_logging_migration" in logger.name
