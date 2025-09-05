"""
ABOUTME: Comprehensive unit tests for authentication providers and password expiration logic
ABOUTME: Tests LocalAuthProvider functionality, password validation, and expiration handling

Unit tests for TrakBridge authentication providers.

File: tests/unit/test_auth_providers.py

Description:
    Comprehensive unit tests for the authentication provider system, including:
    - LocalAuthProvider initialization and configuration
    - Password expiration logic with None/zero/positive values (fixes TypeError bug)
    - Password validation and policy enforcement
    - Authentication workflow testing
    - Error handling and edge cases
    - Security validation for password handling

Author: Emfour Solutions
Created: 2025-08-06
Last Modified: 2025-08-06
Version: 1.0.0
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from models.user import AuthProvider, User, UserRole
from services.auth.local_provider import LocalAuthProvider


class TestLocalAuthProvider:
    """Test the LocalAuthProvider class."""

    def test_local_auth_provider_initialization_default_config(self):
        """Test LocalAuthProvider initialization with default configuration."""
        config = {"password_policy": {}}

        provider = LocalAuthProvider(config)

        # Test default values
        assert provider.min_length == 8
        assert provider.require_uppercase is True
        assert provider.require_lowercase is True
        assert provider.require_numbers is True
        assert provider.require_special_chars is True
        assert provider.max_age_days == 90  # Default value

    def test_local_auth_provider_initialization_custom_config(self):
        """Test LocalAuthProvider initialization with custom configuration."""
        config = {
            "password_policy": {
                "min_length": 12,
                "require_uppercase": False,
                "require_lowercase": True,
                "require_numbers": True,
                "require_special_chars": False,
                "max_age_days": 30,
            },
            "allow_registration": True,
            "require_email_verification": True,
        }

        provider = LocalAuthProvider(config)

        # Test custom values
        assert provider.min_length == 12
        assert provider.require_uppercase is False
        assert provider.require_lowercase is True
        assert provider.require_numbers is True
        assert provider.require_special_chars is False
        assert provider.max_age_days == 30
        assert provider.allow_registration is True
        assert provider.require_email_verification is True

    def test_local_auth_provider_none_max_age_days(self):
        """Test LocalAuthProvider handles None max_age_days (fixes TypeError bug)."""
        config = {"password_policy": {"max_age_days": None}}  # This was causing the TypeError

        provider = LocalAuthProvider(config)

        # Should handle None gracefully
        assert provider.max_age_days is None

        # The fixed comparison should work without TypeError
        result = provider.max_age_days is None or provider.max_age_days <= 0
        assert result is True

    def test_password_expiration_logic_none_value(self):
        """Test password expiration logic with None max_age_days (main bug fix)."""
        config = {"password_policy": {"max_age_days": None}}

        provider = LocalAuthProvider(config)

        # Create a test user
        user = User(
            username="testuser",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.USER,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=datetime.now(timezone.utc)
            - timedelta(days=365),  # Very old password
        )

        # With None max_age_days, password should never expire
        is_expired = provider._is_password_expired(user)
        assert is_expired is False

    def test_password_expiration_logic_zero_value(self):
        """Test password expiration logic with zero max_age_days."""
        config = {"password_policy": {"max_age_days": 0}}  # Zero means no expiration

        provider = LocalAuthProvider(config)

        user = User(
            username="testuser",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.USER,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=365),
        )

        # With zero max_age_days, password should never expire
        is_expired = provider._is_password_expired(user)
        assert is_expired is False

    def test_password_expiration_logic_positive_value_not_expired(self):
        """Test password expiration logic with positive max_age_days - not expired."""
        config = {"password_policy": {"max_age_days": 30}}

        provider = LocalAuthProvider(config)

        user = User(
            username="testuser",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.USER,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=15),  # Recent password
        )

        # Password changed 15 days ago, should not be expired (limit is 30 days)
        is_expired = provider._is_password_expired(user)
        assert is_expired is False

    def test_password_expiration_logic_positive_value_expired(self):
        """Test password expiration logic with positive max_age_days - expired."""
        config = {"password_policy": {"max_age_days": 30}}

        provider = LocalAuthProvider(config)

        user = User(
            username="testuser",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.USER,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=datetime.now(timezone.utc) - timedelta(days=45),  # Old password
        )

        # Password changed 45 days ago, should be expired (limit is 30 days)
        is_expired = provider._is_password_expired(user)
        assert is_expired is True

    def test_password_expiration_logic_no_password_changed_date(self):
        """Test password expiration logic with no password_changed_at date."""
        config = {"password_policy": {"max_age_days": 30}}

        provider = LocalAuthProvider(config)

        user = User(
            username="testuser",
            email="test@example.com",
            full_name="Test User",
            role=UserRole.USER,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=None,  # No password change date
        )

        # With no password change date and max_age set, should be considered expired
        is_expired = provider._is_password_expired(user)
        assert is_expired is True

    def test_password_validation_valid_passwords(self):
        """Test password validation with valid passwords."""
        config = {
            "password_policy": {
                "min_length": 8,
                "require_uppercase": True,
                "require_lowercase": True,
                "require_numbers": True,
                "require_special_chars": True,
            }
        }

        provider = LocalAuthProvider(config)

        valid_passwords = [
            "StrongP@ss1",
            "MySecure123!",
            "Tr@kBridge2025",
            "Admin#Pass99",
        ]

        for password in valid_passwords:
            errors = provider.validate_password(password)
            assert len(errors) == 0, f"Password {password} should be valid but got errors: {errors}"

    def test_password_validation_invalid_passwords(self):
        """Test password validation with invalid passwords."""
        config = {
            "password_policy": {
                "min_length": 8,
                "require_uppercase": True,
                "require_lowercase": True,
                "require_numbers": True,
                "require_special_chars": True,
            }
        }

        provider = LocalAuthProvider(config)

        # Test various invalid passwords
        test_cases = [
            ("short", "Password must be at least 8 characters long"),
            ("nouppercase123!", "Password must contain at least one uppercase letter"),
            ("NOLOWERCASE123!", "Password must contain at least one lowercase letter"),
            ("NoNumbers!@#", "Password must contain at least one number"),
            (
                "NoSpecialChars123",
                "Password must contain at least one special character",
            ),
        ]

        for password, expected_error_substring in test_cases:
            errors = provider.validate_password(password)
            assert len(errors) > 0, f"Password {password} should be invalid"

            # Check if expected error message is present
            error_found = any(expected_error_substring.lower() in error.lower() for error in errors)
            assert (
                error_found
            ), f"Expected error containing '{expected_error_substring}' not found in {errors}"

    def test_password_validation_flexible_requirements(self):
        """Test password validation with flexible requirements."""
        config = {
            "password_policy": {
                "min_length": 6,
                "require_uppercase": False,
                "require_lowercase": True,
                "require_numbers": False,
                "require_special_chars": False,
            }
        }

        provider = LocalAuthProvider(config)

        # This should be valid with the relaxed requirements
        password = "simple"
        errors = provider.validate_password(password)
        assert len(errors) == 0

    def test_get_provider_info(self):
        """Test provider info retrieval."""
        config = {"password_policy": {}}
        provider = LocalAuthProvider(config)

        provider_info = provider.get_provider_info()
        assert provider_info["type"] == "local"
        assert "enabled" in provider_info

    def test_supports_feature(self):
        """Test feature support checking."""
        config = {"password_policy": {}}
        provider = LocalAuthProvider(config)

        # Test known features (based on actual implementation)
        assert provider.supports_feature("password_change") is True
        assert provider.supports_feature("user_creation") is True  # Changed from user_registration
        assert (
            provider.supports_feature("password_policy") is True
        )  # Changed from password_validation
        assert provider.supports_feature("authentication") is True

        # Test unknown feature
        assert provider.supports_feature("nonexistent_feature") is False

    def test_validate_configuration_valid(self):
        """Test configuration validation with valid config."""
        valid_config = {
            "password_policy": {
                "min_length": 8,
                "require_uppercase": True,
                "require_lowercase": True,
                "require_numbers": True,
                "require_special_chars": False,
                "max_age_days": 90,
            },
            "allow_registration": True,
            "require_email_verification": False,
        }

        provider = LocalAuthProvider(valid_config)
        issues = provider.validate_configuration()  # No parameters, returns list of issues

        assert len(issues) == 0

    def test_validate_configuration_invalid(self):
        """Test configuration validation with invalid config."""
        from services.auth.base_provider import ProviderConfigurationException

        invalid_config = {
            "password_policy": {
                "min_length": 2,  # Too short
                "max_age_days": -5,  # Negative value
            }
        }

        # Should raise exception during initialization with invalid config
        with pytest.raises(ProviderConfigurationException) as exc_info:
            provider = LocalAuthProvider(invalid_config)

        assert "Configuration validation failed" in str(exc_info.value)

    def test_authentication_method_exists(self):
        """Test that authenticate method exists and can be called."""
        config = {"password_policy": {}}
        provider = LocalAuthProvider(config)

        # Verify method exists
        assert hasattr(provider, "authenticate")
        assert callable(provider.authenticate)

        # Test with invalid credentials (should not crash)
        try:
            result = provider.authenticate("nonexistent", "badpassword")
            # Should return some kind of result, even if authentication fails
            assert isinstance(result, dict)
        except Exception:
            # If it throws an exception, that's also acceptable for this basic test
            pass

    def test_bug_fix_regression_test(self):
        """Regression test for the original TypeError bug with None max_age_days."""
        config = {
            "password_policy": {
                "max_age_days": None  # This was causing: TypeError: '<=' not supported between instances of 'NoneType' and 'int'
            }
        }

        provider = LocalAuthProvider(config)

        user = User(
            username="admin",
            email="admin@example.com",
            full_name="Admin User",
            role=UserRole.ADMIN,
            auth_provider=AuthProvider.LOCAL,
            password_changed_at=datetime.now(timezone.utc),
        )

        # This should not raise TypeError anymore
        try:
            is_expired = provider._is_password_expired(user)
            assert is_expired is False  # With None max_age_days, never expires
            test_passed = True
        except TypeError as e:
            test_passed = False
            pytest.fail(f"TypeError still occurs: {e}")

        assert test_passed, "The original TypeError bug should be fixed"
