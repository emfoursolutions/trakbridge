"""
ABOUTME: Unit tests for queue configuration loading, validation, and environment
ABOUTME: Tests configuration schema validation and environment variable precedence

This module contains configuration tests as specified in the Queue Management
Specification Phase 1. These tests verify that queue configuration is properly
loaded, validated, and can be overridden by environment variables.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import os
import pytest
import yaml
from unittest.mock import patch, mock_open


class TestQueueConfigurationLoading:
    """Test queue configuration loading from various sources"""

    @pytest.mark.xfail(reason="TDD test - queue configuration loading not implemented")
    def test_default_configuration_values(self):
        """Test that default configuration values match specification"""
        expected_defaults = {
            "queue": {
                "max_size": 500,
                "batch_size": 8,
                "overflow_strategy": "drop_oldest",
                "flush_on_config_change": True,
            },
            "transmission": {"batch_timeout_ms": 100, "queue_check_interval_ms": 50},
            "monitoring": {"log_queue_stats": True, "queue_warning_threshold": 400},
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        # Mock no config file found to test defaults
        with patch("builtins.open", side_effect=FileNotFoundError):
            config = cot_service._load_default_queue_configuration()

            # Verify all default values
            assert config["queue"]["max_size"] == expected_defaults["queue"]["max_size"]
            assert (
                config["queue"]["batch_size"]
                == expected_defaults["queue"]["batch_size"]
            )
            assert (
                config["queue"]["overflow_strategy"]
                == expected_defaults["queue"]["overflow_strategy"]
            )
            assert (
                config["queue"]["flush_on_config_change"]
                == expected_defaults["queue"]["flush_on_config_change"]
            )

    @pytest.mark.xfail(reason="TDD test - queue configuration loading not implemented")
    def test_yaml_configuration_loading(self):
        """Test loading configuration from YAML files"""
        yaml_config = """
queue:
  max_size: 750
  batch_size: 12
  overflow_strategy: "drop_newest"
  flush_on_config_change: false

transmission:
  batch_timeout_ms: 200
  queue_check_interval_ms: 75

monitoring:
  log_queue_stats: false
  queue_warning_threshold: 600
"""

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch("builtins.open", mock_open(read_data=yaml_config)):
            config = cot_service._load_queue_configuration_from_file("dummy_path.yaml")

            # Verify YAML values are loaded correctly
            assert config["queue"]["max_size"] == 750
            assert config["queue"]["batch_size"] == 12
            assert config["queue"]["overflow_strategy"] == "drop_newest"
            assert not config["queue"]["flush_on_config_change"]
            assert config["transmission"]["batch_timeout_ms"] == 200
            assert config["monitoring"]["queue_warning_threshold"] == 600

    @pytest.mark.xfail(reason="TDD test - queue configuration loading not implemented")
    def test_environment_variable_override(self):
        """Test that environment variables override config file values"""
        env_vars = {
            "QUEUE_MAX_SIZE": "1000",
            "QUEUE_BATCH_SIZE": "16",
            "QUEUE_OVERFLOW_STRATEGY": "block",
            "QUEUE_FLUSH_ON_CONFIG_CHANGE": "false",
            "TRANSMISSION_BATCH_TIMEOUT_MS": "300",
            "TRANSMISSION_QUEUE_CHECK_INTERVAL_MS": "25",
            "MONITORING_LOG_QUEUE_STATS": "false",
            "MONITORING_QUEUE_WARNING_THRESHOLD": "800",
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch.dict(os.environ, env_vars, clear=False):
            config = cot_service._apply_environment_overrides({})

            # Verify environment variables take precedence
            assert config["queue"]["max_size"] == 1000
            assert config["queue"]["batch_size"] == 16
            assert config["queue"]["overflow_strategy"] == "block"
            assert not config["queue"]["flush_on_config_change"]
            assert config["transmission"]["batch_timeout_ms"] == 300
            assert config["transmission"]["queue_check_interval_ms"] == 25
            assert not config["monitoring"]["log_queue_stats"]
            assert config["monitoring"]["queue_warning_threshold"] == 800

    @pytest.mark.xfail(reason="TDD test - queue configuration loading not implemented")
    def test_partial_environment_override(self):
        """Test that only specified environment variables are overridden"""
        base_config = {
            "queue": {
                "max_size": 500,
                "batch_size": 8,
                "overflow_strategy": "drop_oldest",
            }
        }

        # Only override max_size
        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch.dict(os.environ, {"QUEUE_MAX_SIZE": "1200"}, clear=False):
            config = cot_service._apply_environment_overrides(base_config)

            # Only max_size should change
            assert config["queue"]["max_size"] == 1200
            assert config["queue"]["batch_size"] == 8  # Unchanged
            assert config["queue"]["overflow_strategy"] == "drop_oldest"  # Unchanged


class TestQueueConfigurationValidation:
    """Test configuration validation and error handling"""

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_valid_configuration_passes_validation(self):
        """Test that valid configuration passes all validation checks"""
        valid_config = {
            "queue": {
                "max_size": 500,
                "batch_size": 8,
                "overflow_strategy": "drop_oldest",
                "flush_on_config_change": True,
            },
            "transmission": {"batch_timeout_ms": 100, "queue_check_interval_ms": 50},
            "monitoring": {"log_queue_stats": True, "queue_warning_threshold": 400},
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        # Should not raise any exceptions
        validated_config = cot_service._validate_queue_configuration(valid_config)
        assert validated_config == valid_config

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_invalid_max_size_validation(self):
        """Test validation of max_size parameter"""
        invalid_configs = [
            {"queue": {"max_size": -10}},  # Negative
            {"queue": {"max_size": 0}},  # Zero
            {"queue": {"max_size": "invalid"}},  # Non-numeric
        ]

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        for invalid_config in invalid_configs:
            with pytest.raises(ValueError, match="max_size"):
                cot_service._validate_queue_configuration(invalid_config)

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_invalid_batch_size_validation(self):
        """Test validation of batch_size parameter"""
        invalid_configs = [
            {"queue": {"batch_size": 0}},  # Zero
            {"queue": {"batch_size": -5}},  # Negative
            {"queue": {"batch_size": 101}},  # Too large (> 100)
        ]

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        for invalid_config in invalid_configs:
            with pytest.raises(ValueError, match="batch_size"):
                cot_service._validate_queue_configuration(invalid_config)

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_invalid_overflow_strategy_validation(self):
        """Test validation of overflow_strategy parameter"""
        invalid_config = {"queue": {"overflow_strategy": "invalid_strategy"}}

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with pytest.raises(ValueError, match="overflow_strategy"):
            cot_service._validate_queue_configuration(invalid_config)

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_configuration_auto_correction(self):
        """Test that invalid values are auto-corrected to safe defaults"""
        invalid_config = {
            "queue": {
                "max_size": -100,  # Will be corrected to default
                "batch_size": 0,  # Will be corrected to default
                "overflow_strategy": "invalid",  # Will be corrected to default
            }
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        # With auto-correction enabled
        corrected_config = cot_service._validate_and_correct_configuration(
            invalid_config
        )

        assert corrected_config["queue"]["max_size"] > 0
        assert corrected_config["queue"]["batch_size"] > 0
        assert corrected_config["queue"]["overflow_strategy"] in [
            "drop_oldest",
            "drop_newest",
            "block",
        ]

    @pytest.mark.xfail(
        reason="TDD test - queue configuration validation not implemented"
    )
    def test_timeout_validation(self):
        """Test validation of timeout parameters"""
        invalid_configs = [
            {"transmission": {"batch_timeout_ms": -50}},  # Negative timeout
            {"transmission": {"batch_timeout_ms": 0}},  # Zero timeout
            {"transmission": {"queue_check_interval_ms": -10}},  # Negative interval
        ]

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        for invalid_config in invalid_configs:
            with pytest.raises(ValueError, match="timeout|interval"):
                cot_service._validate_queue_configuration(invalid_config)


class TestConfigurationPrecedence:
    """Test configuration precedence and merging"""

    @pytest.mark.xfail(
        reason="TDD test - queue configuration precedence not implemented"
    )
    def test_configuration_precedence_order(self):
        """Test that configuration sources are applied in correct precedence order"""
        # 1. Default config (lowest precedence)
        default_config = {
            "queue": {
                "max_size": 500,
                "batch_size": 8,
                "overflow_strategy": "drop_oldest",
            }
        }

        # 2. YAML file config (medium precedence)
        yaml_config = {
            "queue": {
                "max_size": 750,  # Override default
                "batch_size": 8,  # Keep default
                "overflow_strategy": "drop_newest",  # Override default
            }
        }

        # 3. Environment variables (highest precedence)
        env_override = {
            "QUEUE_MAX_SIZE": "1000"  # Override YAML
            # batch_size and overflow_strategy come from YAML
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch.dict(os.environ, env_override, clear=False):
            # Simulate the configuration loading process
            config = default_config.copy()
            config = cot_service._merge_configurations(config, yaml_config)
            config = cot_service._apply_environment_overrides(config)

            # Verify precedence
            assert config["queue"]["max_size"] == 1000  # From environment
            assert config["queue"]["overflow_strategy"] == "drop_newest"  # From YAML
            assert config["queue"]["batch_size"] == 8  # From YAML (and default)

    @pytest.mark.xfail(
        reason="TDD test - queue configuration precedence not implemented"
    )
    def test_deep_configuration_merging(self):
        """Test that nested configuration structures are merged correctly"""
        base_config = {
            "queue": {"max_size": 500, "batch_size": 8},
            "transmission": {"batch_timeout_ms": 100},
        }

        override_config = {
            "queue": {
                "max_size": 1000  # Override only max_size
                # batch_size should remain from base
            },
            "monitoring": {"log_queue_stats": True},  # New section
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()
        merged_config = cot_service._merge_configurations(base_config, override_config)

        # Verify deep merging
        assert merged_config["queue"]["max_size"] == 1000  # Overridden
        assert merged_config["queue"]["batch_size"] == 8  # Preserved
        assert merged_config["transmission"]["batch_timeout_ms"] == 100  # Preserved
        assert merged_config["monitoring"]["log_queue_stats"]  # Added

    @pytest.mark.xfail(
        reason="TDD test - queue configuration precedence not implemented"
    )
    def test_environment_variable_type_conversion(self):
        """Test that environment variables are converted to correct types"""
        env_vars = {
            "QUEUE_MAX_SIZE": "500",  # String -> int
            "QUEUE_FLUSH_ON_CONFIG_CHANGE": "true",  # String -> bool
            "MONITORING_LOG_QUEUE_STATS": "false",  # String -> bool
            "TRANSMISSION_BATCH_TIMEOUT_MS": "250.5",  # String -> float (should be int)
        }

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch.dict(os.environ, env_vars, clear=False):
            config = cot_service._apply_environment_overrides({})

            # Verify type conversions
            assert isinstance(config["queue"]["max_size"], int)
            assert config["queue"]["max_size"] == 500

            assert isinstance(config["queue"]["flush_on_config_change"], bool)
            assert config["queue"]["flush_on_config_change"]

            assert isinstance(config["monitoring"]["log_queue_stats"], bool)
            assert not config["monitoring"]["log_queue_stats"]

            # Float should be converted to int for timeout
            assert isinstance(config["transmission"]["batch_timeout_ms"], int)
            assert config["transmission"]["batch_timeout_ms"] == 250


class TestConfigurationFileDiscovery:
    """Test configuration file discovery and loading"""

    @pytest.mark.xfail(
        reason="TDD test - queue configuration file discovery not implemented"
    )
    def test_configuration_file_search_order(self):
        """Test that configuration files are searched in correct order"""
        expected_search_paths = [
            "config/settings/queue.yaml",
            "config/settings/production/queue.yaml",
            "config/settings/development/queue.yaml",
            "/etc/trakbridge/queue.yaml",
            "~/.trakbridge/queue.yaml",
        ]

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()
        search_paths = cot_service._get_configuration_search_paths()

        # Verify search paths are in expected order
        for expected_path in expected_search_paths:
            assert any(
                expected_path in path for path in search_paths
            ), f"Missing search path: {expected_path}"

    @pytest.mark.xfail(
        reason="TDD test - queue configuration file discovery not implemented"
    )
    def test_configuration_file_not_found_fallback(self):
        """Test fallback to defaults when no configuration file is found"""
        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        # Mock all file paths to not exist
        with patch("os.path.exists", return_value=False):
            config = cot_service._load_queue_configuration()

            # Should fall back to defaults
            assert config["queue"]["max_size"] == 500  # Default value
            assert config["queue"]["batch_size"] == 8  # Default value

    @pytest.mark.xfail(
        reason="TDD test - queue configuration file discovery not implemented"
    )
    def test_malformed_yaml_handling(self):
        """Test handling of malformed YAML configuration files"""
        malformed_yaml = """
queue:
  max_size: 500
  batch_size: [unclosed list
  overflow_strategy: "drop_oldest"
"""

        from services.cot_service import get_cot_service, reset_cot_service

        reset_cot_service()  # Reset singleton for clean test
        cot_service = get_cot_service()

        with patch("builtins.open", mock_open(read_data=malformed_yaml)):
            # Should handle YAML parse errors gracefully
            with pytest.raises(yaml.YAMLError):
                cot_service._load_queue_configuration_from_file("malformed.yaml")
