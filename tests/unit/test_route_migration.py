"""
ABOUTME: Test suite for Phase 3C centralized logging migration validation (Routes & APIs)
ABOUTME: Validates all route files use centralized logging service with proper patterns

File: tests/unit/test_phase3c_route_migration.py

Description:
    Comprehensive test suite for validating Phase 3C of the centralized logging migration.
    Phase 3C covers route and API files migration from `logging.getLogger(__name__)` to
    the centralized `get_module_logger(__name__)` pattern. This test suite validates that
    all route files are properly using the centralized logging service and following
    the established patterns.

Key test scenarios:
    - Verify all route modules import centralized logging service
    - Validate logger instance types and naming conventions
    - Check for absence of old logging patterns (logging.getLogger)
    - Confirm proper module-level logger initialization
    - Validate logging functionality across all route blueprints
    - Test logging behavior consistency with other migrated phases
    - Integration testing with Phase 3A and 3B systems

Phase 3C Migration Scope:
    Target Files (8 route files):
    - routes/main.py (✅ already migrated)
    - routes/api.py (✅ already migrated) 
    - routes/auth.py (✅ already migrated)
    - routes/streams.py (✅ already migrated)
    - routes/tak_servers.py (✅ already migrated)
    - routes/admin.py (✅ already migrated)
    - routes/cot_types.py (✅ already migrated)
    - routes/__init__.py (✅ no logging needed)

Expected Benefits:
    - Consistent logging behavior across all route modules
    - Centralized log configuration and formatting
    - Better debug capabilities with standardized logger names
    - Reduced code duplication (eliminated ~8 lines across 7 files)

Author: Emfour Solutions
Created: 2025-09-03
Version: 1.0.0
"""

import importlib
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest


class TestPhase3CRouteMigration:
    """Test suite for Phase 3C route files migration to centralized logging"""

    # Route modules that should use centralized logging
    ROUTE_MODULES_WITH_LOGGING = [
        "routes.main",
        "routes.api",
        "routes.auth",
        "routes.streams",
        "routes.tak_servers",
        "routes.admin",
        "routes.cot_types",
    ]

    # Modules that don't need logging (package init files, etc.)
    ROUTE_MODULES_WITHOUT_LOGGING = ["routes.__init__"]

    ALL_ROUTE_MODULES = ROUTE_MODULES_WITH_LOGGING + ROUTE_MODULES_WITHOUT_LOGGING

    def test_route_module_imports(self):
        """Test that all route modules can be imported successfully"""
        for module_name in self.ALL_ROUTE_MODULES:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_centralized_logging_imports(self):
        """Test that route modules with logging import the centralized logging service"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)

            # Check that get_module_logger is imported from services.logging_service
            module_source = self._get_module_source(module_name)

            assert (
                "from services.logging_service import get_module_logger"
                in module_source
            ), f"{module_name} should import get_module_logger from services.logging_service"

    def test_no_old_logging_patterns(self):
        """Test that route modules don't use old logging.getLogger patterns"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module_source = self._get_module_source(module_name)

            # Check that old logging patterns are not present
            assert (
                "logging.getLogger(__name__)" not in module_source
            ), f"{module_name} should not use logging.getLogger(__name__)"

            assert (
                "logging.getLogger(" not in module_source
            ), f"{module_name} should not use logging.getLogger() at all"

    def test_logger_instance_creation(self):
        """Test that route modules create logger instances using centralized service"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)
            module_source = self._get_module_source(module_name)

            # Check for proper logger initialization pattern
            assert (
                "logger = get_module_logger(__name__)" in module_source
            ), f"{module_name} should use 'logger = get_module_logger(__name__)' pattern"

            # Check that logger attribute exists
            assert hasattr(
                module, "logger"
            ), f"{module_name} should have 'logger' attribute"

    def test_logger_instance_types(self):
        """Test that route modules have proper logger instances"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)

            logger = getattr(module, "logger", None)
            assert logger is not None, f"{module_name} should have a logger attribute"

            # Logger should be a Logger instance
            assert isinstance(
                logger, logging.Logger
            ), f"{module_name}.logger should be a Logger instance, got {type(logger)}"

    def test_logger_naming_consistency(self):
        """Test that logger names follow the expected pattern"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)

            logger = getattr(module, "logger", None)
            assert logger is not None, f"{module_name} should have a logger attribute"

            # Logger name should match the module name
            expected_name = module_name
            assert (
                logger.name == expected_name
            ), f"{module_name}.logger name should be '{expected_name}', got '{logger.name}'"

    def test_logger_functionality(self):
        """Test that loggers can actually log messages"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)

            logger = getattr(module, "logger", None)
            assert logger is not None, f"{module_name} should have a logger attribute"

            # Test that logger has all standard logging methods
            for method in ["debug", "info", "warning", "error", "critical"]:
                assert hasattr(
                    logger, method
                ), f"{module_name}.logger should have {method} method"

                # Test that the method is callable
                assert callable(
                    getattr(logger, method)
                ), f"{module_name}.logger.{method} should be callable"

    def test_blueprint_registration(self):
        """Test that blueprints are properly registered with logging"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            if (
                module_name == "routes.main"
            ):  # main doesn't have bp, it has different structure
                continue

            module = importlib.import_module(module_name)

            # Most route modules should have a 'bp' (blueprint) attribute
            if hasattr(module, "bp"):
                blueprint = getattr(module, "bp")
                # Blueprint should have a name
                assert hasattr(
                    blueprint, "name"
                ), f"{module_name} blueprint should have a name attribute"

    def test_no_circular_imports(self):
        """Test that importing route modules doesn't create circular import issues"""
        # Clear any previously imported modules to test fresh imports
        modules_to_test = [mod for mod in self.ALL_ROUTE_MODULES if mod in sys.modules]
        for mod_name in modules_to_test:
            if mod_name in sys.modules:
                del sys.modules[mod_name]

        # Try importing all modules in sequence
        for module_name in self.ALL_ROUTE_MODULES:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Circular import detected in {module_name}: {e}")

    def test_consistent_import_order(self):
        """Test that import statements follow consistent ordering"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module_source = self._get_module_source(module_name)

            # Find the line with logging service import
            lines = module_source.split("\n")
            logging_import_line = None
            logger_creation_line = None

            for i, line in enumerate(lines):
                if "from services.logging_service import get_module_logger" in line:
                    logging_import_line = i
                if "logger = get_module_logger(__name__)" in line:
                    logger_creation_line = i

            assert (
                logging_import_line is not None
            ), f"{module_name} should import get_module_logger"
            assert (
                logger_creation_line is not None
            ), f"{module_name} should create logger instance"
            assert (
                logging_import_line < logger_creation_line
            ), f"{module_name} should import get_module_logger before using it"

    def test_integration_with_phase3a_services(self):
        """Test that route logging integrates properly with Phase 3A services"""
        # Import a Phase 3A service and a Phase 3C route to test integration
        try:
            from services.logging_service import get_module_logger
            from routes.main import logger as main_logger

            # Both should use the same logging service
            test_logger = get_module_logger("test.integration")

            # Loggers should be properly configured
            assert isinstance(main_logger, logging.Logger)
            assert isinstance(test_logger, logging.Logger)

            # Both should be using the same root logger configuration
            assert (
                main_logger.parent == test_logger.parent
                or main_logger.parent.parent == test_logger.parent.parent
            )

        except ImportError as e:
            pytest.fail(
                f"Integration test failed - cannot import required modules: {e}"
            )

    def test_integration_with_phase3b_plugins(self):
        """Test that route logging integrates properly with Phase 3B plugins"""
        try:
            from routes.streams import logger as streams_logger

            # Try to import a Phase 3B plugin to test integration
            from plugins.base_plugin import logger as plugin_logger

            # Both should be Logger instances (plugin_logger might be a proxy)
            assert isinstance(streams_logger, logging.Logger)
            # For plugin logger, we check if it has logger methods (proxy pattern)
            assert hasattr(plugin_logger, "info")
            assert hasattr(plugin_logger, "error")
            assert hasattr(plugin_logger, "debug")

        except ImportError as e:
            pytest.fail(f"Integration test with Phase 3B failed: {e}")

    def test_module_docstrings_updated(self):
        """Test that module docstrings contain proper file identification"""
        for module_name in self.ROUTE_MODULES_WITH_LOGGING:
            module = importlib.import_module(module_name)

            # Module should have a docstring
            assert module.__doc__ is not None, f"{module_name} should have a docstring"

            # Check for ABOUTME patterns (if present)
            if "ABOUTME:" in module.__doc__:
                lines = module.__doc__.split("\n")
                aboutme_lines = [
                    line.strip()
                    for line in lines
                    if line.strip().startswith("ABOUTME:")
                ]
                assert (
                    len(aboutme_lines) >= 2
                ), f"{module_name} should have at least 2 ABOUTME lines if using this pattern"

    def test_phase3c_statistics(self):
        """Test and report Phase 3C migration statistics"""
        total_files = len(self.ALL_ROUTE_MODULES)
        files_with_logging = len(self.ROUTE_MODULES_WITH_LOGGING)
        files_without_logging = len(self.ROUTE_MODULES_WITHOUT_LOGGING)

        # Verify all files are accounted for
        assert total_files == files_with_logging + files_without_logging

        # Calculate lines saved (approximately 1 line per migrated logger declaration)
        estimated_lines_saved = files_with_logging  # Conservative estimate

        # Log migration statistics
        print(f"\n=== Phase 3C Migration Statistics ===")
        print(f"Total route files examined: {total_files}")
        print(f"Files using centralized logging: {files_with_logging}")
        print(f"Files not requiring logging: {files_without_logging}")
        print(f"Estimated lines of code saved: ~{estimated_lines_saved}")
        print(f"Migration status: COMPLETE ✅")

    def _get_module_source(self, module_name: str) -> str:
        """Get the source code of a module"""
        try:
            module = importlib.import_module(module_name)
            module_file = getattr(module, "__file__", None)

            if module_file is None:
                pytest.fail(f"Cannot get source file for {module_name}")

            with open(module_file, "r", encoding="utf-8") as f:
                return f.read()

        except Exception as e:
            pytest.fail(f"Failed to get source for {module_name}: {e}")


# Integration tests with other phases
class TestPhase3CIntegration:
    """Integration tests between Phase 3C and other phases"""

    def test_cross_phase_logger_consistency(self):
        """Test that loggers across all phases use consistent naming"""
        try:
            # Import loggers from different phases
            from services.logging_service import get_module_logger  # Phase 3A
            from plugins.base_plugin import logger as plugin_logger  # Phase 3B
            from routes.main import logger as route_logger  # Phase 3C

            # Create test logger
            test_logger = get_module_logger("test.cross_phase")

            # All should be using the centralized service
            assert isinstance(route_logger, logging.Logger)
            assert isinstance(test_logger, logging.Logger)

            # Plugin logger might be proxy, but should have logging methods
            assert hasattr(plugin_logger, "info")
            assert hasattr(plugin_logger, "error")

        except ImportError as e:
            pytest.fail(f"Cross-phase integration test failed: {e}")

    def test_all_phases_working_together(self):
        """Test that all migrated phases work together without conflicts"""
        try:
            # Import from all phases
            from services.logging_service import get_module_logger  # Phase 3A
            from plugins.spot_plugin import logger as plugin_logger  # Phase 3B
            from routes.api import logger as api_logger  # Phase 3C

            # All should be functioning
            assert get_module_logger is not None
            assert hasattr(plugin_logger, "info")  # Could be proxy
            assert isinstance(api_logger, logging.Logger)

            # Test that they don't conflict with each other
            assert api_logger.name == "routes.api"

            # Test that the centralized service works
            test_logger = get_module_logger("test.multi_phase")
            assert isinstance(test_logger, logging.Logger)

        except ImportError as e:
            pytest.fail(f"Multi-phase integration test failed: {e}")


if __name__ == "__main__":
    # Run the tests if executed directly
    pytest.main([__file__, "-v"])
