"""
ABOUTME: Unit tests for parallel processing configuration system in Phase 1B
ABOUTME: Tests follow TDD principles - all tests initially FAIL until configuration is implemented
"""

import pytest
import os
import tempfile
import yaml
from unittest.mock import patch, MagicMock
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from services.cot_service import EnhancedCOTService
from tests.fixtures.mock_location_data import generate_performance_test_datasets


class TestParallelConfiguration:
    """
    Phase 1B: Configuration & Fallbacks Tests
    All tests should FAIL initially until configuration system is implemented
    """

    @pytest.fixture
    def cot_service(self):
        """Create COT service instance for testing"""
        return EnhancedCOTService(use_pytak=True)

    @pytest.fixture
    def sample_config(self):
        """Sample performance configuration for testing"""
        return {
            "parallel_processing": {
                "enabled": True,
                "batch_size_threshold": 10,
                "max_concurrent_tasks": 50,
                "fallback_on_error": True,
                "enable_performance_logging": True
            }
        }

    @pytest.fixture
    def performance_datasets(self):
        """Load standardized test datasets"""
        return generate_performance_test_datasets()

    def test_configuration_loading_class_exists(self, cot_service):
        """
        Test that configuration loading mechanism exists
        STATUS: WILL FAIL - configuration loading doesn't exist yet
        """
        assert hasattr(cot_service, 'load_performance_config'), \
            "COT service should have load_performance_config method"
        assert callable(cot_service.load_performance_config), \
            "load_performance_config should be callable"

    def test_default_configuration_values(self, cot_service):
        """
        Test that service has sensible default configuration values
        STATUS: WILL FAIL - default config doesn't exist
        """
        # Should have default config even without loading file
        assert hasattr(cot_service, 'parallel_config'), \
            "Should have parallel_config attribute"
        
        config = cot_service.parallel_config
        assert config['enabled'] is True, "Parallel processing should be enabled by default"
        assert config['batch_size_threshold'] >= 1, "Batch size threshold should be positive"
        assert config['max_concurrent_tasks'] > 0, "Max concurrent tasks should be positive"
        assert config['fallback_on_error'] is True, "Should fallback on error by default"

    def test_configurable_batch_size_threshold(self, cot_service, performance_datasets):
        """
        Test that batch size threshold can be configured
        REQUIREMENT: Configurable when parallel processing kicks in
        STATUS: WILL FAIL - configurable batch size doesn't exist
        """
        small_dataset = performance_datasets["small"]  # 5 points
        medium_dataset = performance_datasets["medium"]  # 50 points

        # Test with high threshold (should use serial for both)
        cot_service.parallel_config = {"batch_size_threshold": 100, "enabled": True}
        
        # Mock to track which method gets called
        cot_service._create_pytak_events = MagicMock(return_value=[b"serial"])
        cot_service._create_parallel_pytak_events = MagicMock(return_value=[b"parallel"])
        
        # Small dataset should use serial (below threshold)
        result_small = cot_service._choose_processing_method(small_dataset)
        assert result_small == "serial", "Should choose serial for dataset below threshold"
        
        # Medium dataset should also use serial (still below high threshold)
        result_medium = cot_service._choose_processing_method(medium_dataset)
        assert result_medium == "serial", "Should choose serial when below configured threshold"

        # Test with low threshold (should use parallel for medium)
        cot_service.parallel_config = {"batch_size_threshold": 10, "enabled": True}
        result_medium_low = cot_service._choose_processing_method(medium_dataset)
        assert result_medium_low == "parallel", "Should choose parallel when above threshold"

    def test_parallel_processing_can_be_disabled(self, cot_service, performance_datasets):
        """
        Test that parallel processing can be completely disabled
        REQUIREMENT: Toggle to disable parallel processing entirely
        STATUS: WILL FAIL - disable toggle doesn't exist
        """
        large_dataset = performance_datasets["large"]  # 300 points
        
        # Disable parallel processing
        cot_service.parallel_config = {"enabled": False, "batch_size_threshold": 1}
        
        # Mock to track which method gets called
        cot_service._create_pytak_events = MagicMock(return_value=[b"serial"])
        cot_service._create_parallel_pytak_events = MagicMock(return_value=[b"parallel"])
        
        result = cot_service._choose_processing_method(large_dataset)
        assert result == "serial", "Should always choose serial when parallel processing disabled"
        
        # Enable parallel processing
        cot_service.parallel_config = {"enabled": True, "batch_size_threshold": 1}
        result_enabled = cot_service._choose_processing_method(large_dataset)
        assert result_enabled == "parallel", "Should choose parallel when enabled and above threshold"

    def test_configuration_file_loading(self, cot_service, sample_config):
        """
        Test that configuration can be loaded from YAML file
        STATUS: WILL FAIL - file loading doesn't exist
        """
        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_config, f)
            temp_config_path = f.name
        
        try:
            # Load configuration from file
            loaded_config = cot_service.load_performance_config(temp_config_path)
            
            assert loaded_config['parallel_processing']['enabled'] is True
            assert loaded_config['parallel_processing']['batch_size_threshold'] == 10
            assert loaded_config['parallel_processing']['max_concurrent_tasks'] == 50
            assert loaded_config['parallel_processing']['fallback_on_error'] is True
            
        finally:
            os.unlink(temp_config_path)

    def test_invalid_configuration_handling(self, cot_service):
        """
        Test that invalid configuration values are handled gracefully
        STATUS: WILL FAIL - configuration validation doesn't exist
        """
        invalid_configs = [
            {"parallel_processing": {"enabled": "not_boolean"}},  # Invalid boolean
            {"parallel_processing": {"batch_size_threshold": -1}},  # Negative threshold
            {"parallel_processing": {"max_concurrent_tasks": 0}},  # Zero tasks
            {"parallel_processing": {}},  # Empty config
            {},  # No parallel_processing section
        ]
        
        for invalid_config in invalid_configs:
            # Should not raise exception, should use defaults
            result = cot_service.validate_performance_config(invalid_config)
            
            # Should return valid default configuration
            assert isinstance(result, dict), "Should return dict even with invalid input"
            assert 'enabled' in result, "Should have enabled field"
            assert isinstance(result['enabled'], bool), "enabled should be boolean"
            assert result['batch_size_threshold'] > 0, "batch_size_threshold should be positive"

    def test_configuration_environment_override(self, cot_service):
        """
        Test that environment variables can override configuration
        STATUS: WILL FAIL - environment override doesn't exist
        """
        with patch.dict(os.environ, {
            'TRAKBRIDGE_PARALLEL_ENABLED': 'false',
            'TRAKBRIDGE_BATCH_SIZE_THRESHOLD': '25'
        }):
            config = cot_service.load_performance_config_with_env_override()
            
            assert config['enabled'] is False, "Environment should override enabled setting"
            assert config['batch_size_threshold'] == 25, "Environment should override batch size"

    @pytest.mark.asyncio
    async def test_max_concurrent_tasks_limit(self, cot_service, performance_datasets):
        """
        Test that max_concurrent_tasks configuration is respected
        STATUS: WILL FAIL - concurrent task limiting doesn't exist
        """
        large_dataset = performance_datasets["extra_large"]  # 1000 points
        
        # Set low concurrent task limit
        cot_service.parallel_config = {
            "enabled": True,
            "batch_size_threshold": 1,
            "max_concurrent_tasks": 5  # Very low limit
        }
        
        # Mock asyncio.gather to track concurrent tasks
        original_gather = __import__('asyncio').gather
        max_concurrent_seen = 0
        
        async def mock_gather(*args, **kwargs):
            nonlocal max_concurrent_seen
            max_concurrent_seen = max(max_concurrent_seen, len(args))
            # Return fake results
            return [b"mock_event"] * len(args)
        
        with patch('asyncio.gather', side_effect=mock_gather):
            await cot_service._create_parallel_pytak_events(
                large_dataset, "a-f-G-U-C", 300, "stream"
            )
            
            assert max_concurrent_seen <= 5, \
                f"Should not exceed max_concurrent_tasks limit, saw {max_concurrent_seen}"

    def test_performance_logging_configuration(self, cot_service):
        """
        Test that performance logging can be configured
        STATUS: WILL FAIL - performance logging toggle doesn't exist
        """
        # Test logging enabled
        cot_service.parallel_config = {"enable_performance_logging": True}
        assert cot_service.should_log_performance() is True, \
            "Should enable performance logging when configured"
        
        # Test logging disabled
        cot_service.parallel_config = {"enable_performance_logging": False}
        assert cot_service.should_log_performance() is False, \
            "Should disable performance logging when configured"

    def test_configuration_hot_reload(self, cot_service, sample_config):
        """
        Test that configuration can be reloaded without service restart
        STATUS: WILL FAIL - hot reload doesn't exist
        """
        # Initial configuration
        cot_service.parallel_config = {"enabled": False, "batch_size_threshold": 100}
        assert cot_service.parallel_config['enabled'] is False
        
        # Create new config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_config, f)
            temp_config_path = f.name
        
        try:
            # Reload configuration
            cot_service.reload_performance_config(temp_config_path)
            
            # Should have new values
            assert cot_service.parallel_config['enabled'] is True
            assert cot_service.parallel_config['batch_size_threshold'] == 10
            
        finally:
            os.unlink(temp_config_path)

    def test_configuration_file_path_resolution(self, cot_service):
        """
        Test that configuration file path can be resolved from multiple locations
        STATUS: WILL FAIL - path resolution doesn't exist
        """
        # Should check multiple paths in order
        config_paths = cot_service.get_config_file_search_paths()
        
        expected_paths = [
            "config/settings/performance.yaml",
            "/etc/trakbridge/performance.yaml",
            "~/.trakbridge/performance.yaml"
        ]
        
        for expected_path in expected_paths:
            assert any(expected_path in path for path in config_paths), \
                f"Should search for config in {expected_path}"


if __name__ == "__main__":
    # Run tests to verify they all FAIL initially (RED phase of TDD)
    pytest.main([__file__, "-v", "--tb=short"])