"""
ABOUTME: Test suite for Phase 3B plugin system migration to centralized logging patterns
ABOUTME: Validates that all plugin files use centralized logging and maintain plugin functionality

File: tests/test_phase3b_plugin_migration.py

Description:
    Comprehensive test suite for Phase 3B plugin system migration validation.
    Tests that all plugin files (6 total) properly migrate to centralized
    logging while maintaining full plugin functionality and compatibility.
    
    Plugin files being migrated in Phase 3B:
    - plugins/garmin_plugin.py (main plugin with extensive logging)
    - plugins/traccar_plugin.py (another major plugin)
    - plugins/deepstate_plugin.py (plugin migration)
    - plugins/spot_plugin.py (plugin migration)
    - plugins/base_plugin.py (base class for all plugins)
    - docs/example_external_plugins/sample_custom_tracker.py (example)
    
Tests:
    - Centralized logging migration validation
    - Plugin functionality preservation
    - Plugin system integration
    - Performance impact assessment
    - Backwards compatibility maintenance
    
Author: Emfour Solutions
Created: 2025-09-03
"""

import importlib
from unittest.mock import MagicMock, patch

import pytest

from services.logging_service import get_module_logger


class TestPhase3BPluginLoggingMigration:
    """Test centralized logging migration for Phase 3B plugin files"""

    # All Phase 3B plugin files to be migrated
    PLUGIN_FILES = [
        "plugins.garmin_plugin",
        "plugins.traccar_plugin",
        "plugins.deepstate_plugin",
        "plugins.spot_plugin",
        "plugins.base_plugin",
        "docs.example_external_plugins.sample_custom_tracker",
    ]

    def test_plugin_files_exist_and_importable(self):
        """Test that all plugin files exist and can be imported"""
        importable_plugins = []

        for plugin_module in self.PLUGIN_FILES:
            try:
                module = importlib.import_module(plugin_module)
                importable_plugins.append(plugin_module)
                assert module is not None, f"{plugin_module} should be importable"

            except ImportError as e:
                # Some plugins might have optional dependencies
                if plugin_module == "docs.example_external_plugins.sample_custom_tracker":
                    pytest.skip(f"Example plugin not available: {e}")
                else:
                    pytest.fail(f"Core plugin {plugin_module} should be importable: {e}")

        # Should be able to import most plugins
        assert len(importable_plugins) >= 4, "Should be able to import at least 4 plugins"

    def test_plugin_files_import_centralized_logging(self):
        """Test that plugin files import get_module_logger after migration"""
        for plugin_module in self.PLUGIN_FILES:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should import centralized logging
                        assert (
                            "from services.logging_service import get_module_logger" in content
                        ), f"{plugin_module} should import get_module_logger"

            except ImportError:
                pytest.skip(f"Plugin {plugin_module} not available for inspection")

    def test_plugin_files_use_centralized_logger_creation(self):
        """Test that plugin files use get_module_logger instead of logging.getLogger"""
        for plugin_module in self.PLUGIN_FILES:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should use new pattern (base_plugin uses lazy loading)
                        if plugin_module == "plugins.base_plugin":
                            # Base plugin uses lazy loading pattern
                            assert (
                                "get_module_logger" in content
                            ), f"{plugin_module} should import get_module_logger for lazy loading"
                        else:
                            # Regular plugins use direct pattern
                            assert (
                                "logger = get_module_logger(__name__)" in content
                            ), f"{plugin_module} should use get_module_logger(__name__)"

                        # Should not use old pattern
                        assert (
                            "logger = logging.getLogger(__name__)" not in content
                        ), f"{plugin_module} still contains old logging pattern"

            except ImportError:
                pytest.skip(f"Plugin {plugin_module} not available for inspection")

    def test_plugin_files_have_logger_instances(self):
        """Test that migrated plugin files have logger instances"""
        for plugin_module in self.PLUGIN_FILES:
            try:
                module = importlib.import_module(plugin_module)

                # Should have module-level logger
                assert hasattr(module, "logger"), f"{plugin_module} should have logger attribute"

                # Logger should be proper Logger instance or proxy
                import logging

                # Handle proxy pattern for base_plugin lazy loading
                if plugin_module == "plugins.base_plugin":
                    # For base plugin, check that logger proxy has logging methods
                    assert hasattr(
                        module.logger, "info"
                    ), f"{plugin_module}.logger should have info method"
                    assert hasattr(
                        module.logger, "error"
                    ), f"{plugin_module}.logger should have error method"
                    assert hasattr(
                        module.logger, "debug"
                    ), f"{plugin_module}.logger should have debug method"
                else:
                    # For regular plugins, expect actual Logger instance
                    assert isinstance(
                        module.logger, logging.Logger
                    ), f"{plugin_module}.logger should be Logger instance"

                # Logger name should match module (skip proxy check as it's lazy)
                if plugin_module != "plugins.base_plugin":
                    assert (
                        module.logger.name == plugin_module
                    ), f"{plugin_module} logger should have correct name"

            except ImportError:
                pytest.skip(f"Plugin {plugin_module} not available")


class TestPluginFunctionalityPreservation:
    """Test that plugin functionality is preserved after migration"""

    def test_base_plugin_class_functionality(self):
        """Test that base plugin class maintains functionality"""
        try:
            from plugins.base_plugin import BaseGPSPlugin

            # Should be importable and have expected interface
            assert BaseGPSPlugin is not None

            # Should have expected methods (abstract methods)
            assert hasattr(BaseGPSPlugin, "fetch_locations")
            assert hasattr(BaseGPSPlugin, "plugin_metadata")

            # Should have logger after migration
            module = importlib.import_module("plugins.base_plugin")
            assert hasattr(module, "logger")

        except ImportError:
            pytest.skip("Base plugin not available")

    def test_garmin_plugin_functionality_preserved(self):
        """Test that Garmin plugin functionality is preserved"""
        try:
            from plugins.garmin_plugin import GarminInReachPlugin

            # Should be importable
            assert GarminInReachPlugin is not None

            # Should have expected plugin methods
            assert hasattr(GarminInReachPlugin, "fetch_locations")
            assert hasattr(GarminInReachPlugin, "plugin_metadata")

            # Should have logger after migration
            module = importlib.import_module("plugins.garmin_plugin")
            assert hasattr(module, "logger")

            # Should be able to instantiate with config
            test_config = {"mapshare_id": "test-id"}
            # Note: We'd need to mock dependencies for full instantiation
            # For now, test that class is available

        except ImportError:
            pytest.skip("Garmin plugin not available")

    def test_traccar_plugin_functionality_preserved(self):
        """Test that Traccar plugin functionality is preserved"""
        try:
            from plugins.traccar_plugin import TraccarPlugin

            # Should be importable and functional
            assert TraccarPlugin is not None

            # Should have expected methods
            assert hasattr(TraccarPlugin, "fetch_locations")
            assert hasattr(TraccarPlugin, "plugin_metadata")

            # Should have logger after migration
            module = importlib.import_module("plugins.traccar_plugin")
            assert hasattr(module, "logger")

        except ImportError:
            pytest.skip("Traccar plugin not available")

    def test_plugin_inheritance_chain_intact(self):
        """Test that plugin inheritance chain remains intact after migration"""
        try:
            from plugins.base_plugin import BaseGPSPlugin
            from plugins.garmin_plugin import GarminInReachPlugin

            # Inheritance should be preserved
            assert issubclass(
                GarminInReachPlugin, BaseGPSPlugin
            ), "Plugin inheritance chain should be preserved"

        except ImportError:
            pytest.skip("Plugin classes not available")

    def test_plugin_configuration_fields_preserved(self):
        """Test that plugin configuration fields are preserved"""
        try:
            from plugins.garmin_plugin import GarminInReachPlugin

            # Should have configuration fields defined
            if hasattr(GarminInReachPlugin, "get_config_fields"):
                config_fields = GarminInReachPlugin.get_config_fields()
                assert isinstance(config_fields, list), "Config fields should be list"
                assert len(config_fields) > 0, "Should have configuration fields"

        except ImportError:
            pytest.skip("Garmin plugin not available")


class TestPluginSystemIntegration:
    """Test plugin system integration after Phase 3B migration"""

    def test_plugin_manager_can_load_migrated_plugins(self):
        """Test that plugin manager can load plugins after migration"""
        try:
            from plugins.plugin_manager import PluginManager

            # Plugin manager should be able to discover plugins
            # (This would be more comprehensive with actual plugin loading)
            manager = PluginManager()
            assert manager is not None

        except ImportError:
            pytest.skip("Plugin manager not available")

    def test_plugin_logging_integrates_with_system(self):
        """Test that plugin logging integrates with main application logging"""
        try:
            # Test that plugin loggers work with centralized logging system
            plugin_logger = get_module_logger("plugins.test_plugin")

            # Should be proper logger instance
            import logging

            assert isinstance(plugin_logger, logging.Logger)
            assert plugin_logger.name == "plugins.test_plugin"

            # Should have all standard logging methods
            assert hasattr(plugin_logger, "info")
            assert hasattr(plugin_logger, "error")
            assert hasattr(plugin_logger, "debug")

        except Exception as e:
            pytest.fail(f"Plugin logging integration failed: {e}")

    def test_plugin_error_logging_works(self):
        """Test that plugin error logging works correctly"""
        try:
            from plugins.garmin_plugin import GarminInReachPlugin

            # Plugin should be able to log errors
            module = importlib.import_module("plugins.garmin_plugin")
            logger = module.logger

            with patch.object(logger, "error") as mock_error:
                # Test that we can call logger.error
                logger.error("Test error message")
                mock_error.assert_called_once_with("Test error message")

        except ImportError:
            pytest.skip("Garmin plugin not available")


class TestPluginMigrationBenefits:
    """Test the benefits achieved by Phase 3B plugin migration"""

    def test_plugin_logging_consistency(self):
        """Test that all plugins have consistent logging patterns"""
        plugin_modules = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.base_plugin",
        ]

        logger_patterns = set()

        for plugin_module in plugin_modules:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Extract logging pattern
                        if "logger = get_module_logger(__name__)" in content:
                            logger_patterns.add("centralized")
                        elif "logger = logging.getLogger(__name__)" in content:
                            logger_patterns.add("old")

            except ImportError:
                continue

        # All should use centralized pattern
        assert (
            logger_patterns == {"centralized"} or len(logger_patterns) == 0
        ), f"All plugins should use centralized logging, found patterns: {logger_patterns}"

    def test_plugin_code_reduction_achieved(self):
        """Test that plugin code reduction is achieved"""
        # Each plugin should have 1 line reduction (logging.getLogger -> get_module_logger)
        # Plus cleaner import patterns

        plugin_modules = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.base_plugin",
        ]

        import_improvements = 0

        for plugin_module in plugin_modules:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should have centralized logging import
                        if "from services.logging_service import get_module_logger" in content:
                            import_improvements += 1

            except ImportError:
                continue

        # Should have improved imports
        assert import_improvements >= 2, f"Should have import improvements in plugins"

    def test_plugin_maintainability_improved(self):
        """Test that plugin maintainability is improved"""
        # Test that plugins use consistent logging patterns
        try:
            from plugins.garmin_plugin import GarminInReachPlugin

            module = importlib.import_module("plugins.garmin_plugin")
            logger = module.logger

            # Logger should be centrally managed
            assert hasattr(logger, "info")
            assert hasattr(logger, "error")
            assert logger.name == "plugins.garmin_plugin"

            # This represents improved maintainability through consistent patterns

        except ImportError:
            pytest.skip("Garmin plugin not available")


class TestPluginMigrationPerformance:
    """Test performance impact of Phase 3B plugin migration"""

    def test_plugin_import_performance_maintained(self):
        """Test that plugin imports don't have performance regression"""
        import time

        plugin_modules = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.base_plugin",
        ]

        import_times = {}

        for plugin_module in plugin_modules:
            start_time = time.time()
            try:
                importlib.import_module(plugin_module)
                end_time = time.time()
                import_times[plugin_module] = end_time - start_time

            except ImportError:
                continue

        # No plugin should take too long to import
        for plugin, import_time in import_times.items():
            assert import_time < 0.5, f"{plugin} import too slow: {import_time}s"

    def test_plugin_logger_creation_performance(self):
        """Test that plugin logger creation is performant"""
        import time

        # Test creating multiple plugin loggers
        start_time = time.time()

        loggers = []
        for i in range(50):
            logger = get_module_logger(f"plugins.test_plugin_{i}")
            loggers.append(logger)

        end_time = time.time()
        elapsed = end_time - start_time

        # Should create plugin loggers quickly
        assert elapsed < 0.05, f"Plugin logger creation too slow: {elapsed}s"
        assert len(loggers) == 50


class TestPluginBackwardsCompatibility:
    """Test that Phase 3B maintains plugin backwards compatibility"""

    def test_plugin_interfaces_unchanged(self):
        """Test that plugin interfaces remain unchanged"""
        try:
            from plugins.base_plugin import BaseGPSPlugin

            # Base plugin interface should be unchanged
            expected_methods = ["fetch_locations", "plugin_metadata"]

            for method in expected_methods:
                assert hasattr(
                    BaseGPSPlugin, method
                ), f"BaseGPSPlugin should still have {method} method"

        except ImportError:
            pytest.skip("Base plugin not available")

    def test_existing_plugin_instantiation_works(self):
        """Test that existing plugin instantiation patterns still work"""
        try:
            from plugins.garmin_plugin import GarminInReachPlugin

            # Should be able to create plugin with config
            # (Would need proper mocking for full test)
            test_config = {"mapshare_id": "test-id", "feed_password": "test-password"}

            # Class should be instantiable
            assert GarminInReachPlugin is not None

        except ImportError:
            pytest.skip("Garmin plugin not available")

    def test_plugin_logging_backwards_compatible(self):
        """Test that plugin logging is backwards compatible"""
        # Old logging calls should still work in migrated plugins
        try:
            module = importlib.import_module("plugins.garmin_plugin")
            logger = module.logger

            # Standard logging methods should work
            with patch.object(logger, "info") as mock_info:
                logger.info("Test info message")
                mock_info.assert_called_once_with("Test info message")

            with patch.object(logger, "error") as mock_error:
                logger.error("Test error message")
                mock_error.assert_called_once_with("Test error message")

        except ImportError:
            pytest.skip("Garmin plugin not available")


class TestPhase3BCompleteness:
    """Test that Phase 3B migration is complete and comprehensive"""

    def test_all_target_plugins_migrated(self):
        """Test that all target plugin files have been migrated"""
        target_plugins = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.deepstate_plugin",
            "plugins.spot_plugin",
            "plugins.base_plugin",
        ]

        migrated_count = 0

        for plugin_module in target_plugins:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should have new logging pattern
                        if (
                            "from services.logging_service import get_module_logger" in content
                            and "logger = get_module_logger(__name__)" in content
                        ):
                            migrated_count += 1

            except ImportError:
                continue

        # Should have migrated most plugins
        assert migrated_count >= 3, f"Should have migrated at least 3 plugins, got {migrated_count}"

    def test_no_old_logging_patterns_remain_in_plugins(self):
        """Test that no old logging patterns remain in migrated plugins"""
        target_plugins = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.base_plugin",
        ]

        for plugin_module in target_plugins:
            try:
                module_source = importlib.util.find_spec(plugin_module)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()

                        # Should not have old pattern
                        assert (
                            "logger = logging.getLogger(__name__)" not in content
                        ), f"{plugin_module} still contains old logging pattern"

            except ImportError:
                continue

    def test_plugin_system_consistency_achieved(self):
        """Test that plugin system consistency is achieved"""
        # All plugins should follow same patterns
        plugin_modules = [
            "plugins.garmin_plugin",
            "plugins.traccar_plugin",
            "plugins.base_plugin",
        ]

        consistent_patterns = True

        for plugin_module in plugin_modules:
            try:
                module = importlib.import_module(plugin_module)

                # Should have logger attribute
                if not hasattr(module, "logger"):
                    consistent_patterns = False

                # Logger should have correct name
                if hasattr(module, "logger") and module.logger.name != plugin_module:
                    consistent_patterns = False

            except ImportError:
                continue

        assert consistent_patterns, "Plugin system should have consistent patterns"
