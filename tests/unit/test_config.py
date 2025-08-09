"""Unit tests for TrakBridge configuration."""

import os
from unittest.mock import Mock, patch

import pytest

from config.base import BaseConfig
from config.environments import (
    DevelopmentConfig,
    ProductionConfig,
    TestingEnvironmentConfig,
    get_config,
)


class TestConfigurationSystem:
    """Test the configuration system."""

    def test_get_config_development(self):
        """Test getting development configuration."""
        config = get_config("development")
        assert config is not None
        assert isinstance(config, DevelopmentConfig)
        assert config.DEBUG is True

    def test_get_config_production(self):
        """Test getting production configuration."""
        config = get_config("production")
        assert config is not None
        assert isinstance(config, ProductionConfig)
        assert config.DEBUG is False

    def test_get_config_testing(self):
        """Test getting testing configuration."""
        config = get_config("testing")
        assert config is not None
        assert isinstance(config, TestingEnvironmentConfig)
        assert config.TESTING is True

    def test_base_config_properties(self):
        """Test base configuration properties."""
        config = BaseConfig()

        # Test that required properties exist
        assert hasattr(config, "SECRET_KEY")
        assert hasattr(config, "SQLALCHEMY_DATABASE_URI")
        assert hasattr(config, "MAX_WORKER_THREADS")
        assert hasattr(config, "DEFAULT_POLL_INTERVAL")

    def test_config_validation(self):
        """Test configuration validation."""
        config = get_config("testing")

        # Test validation method exists and can be called
        if hasattr(config, "validate_config"):
            issues = config.validate_config()
            assert isinstance(issues, list)

    @patch.dict(os.environ, {"FLASK_ENV": "development"})
    def test_config_from_environment(self):
        """Test configuration from environment variables."""
        config = get_config()  # Should use FLASK_ENV
        assert config is not None
        assert isinstance(config, DevelopmentConfig)


class TestDevelopmentConfig:
    """Test development-specific configuration."""

    def test_development_config_properties(self):
        """Test development configuration properties."""
        config = DevelopmentConfig()

        assert config.DEBUG is True
        assert config.TESTING is False
        assert "sqlite" in config.SQLALCHEMY_DATABASE_URI.lower()


class TestProductionConfig:
    """Test production-specific configuration."""

    def test_production_config_properties(self):
        """Test production configuration properties."""
        config = ProductionConfig()

        assert config.DEBUG is False
        assert config.TESTING is False


class TestTestEnvironmentConfig:
    """Test testing-specific configuration."""

    def test_testing_config_properties(self):
        """Test testing configuration properties."""
        config = TestingEnvironmentConfig()

        assert config.TESTING is True
        assert config.DEBUG is False  # Testing config disables debug for cleaner output
        assert (
            "sqlite" in config.SQLALCHEMY_DATABASE_URI.lower()
            or "memory" in config.SQLALCHEMY_DATABASE_URI.lower()
        )
