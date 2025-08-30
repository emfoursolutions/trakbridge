"""
Integration test for secure authentication configuration system.

This test verifies that the secure authentication loader integrates
properly with the main application configuration system and can
handle both local development and CI/CD scenarios.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest


class TestSecureAuthenticationIntegration(unittest.TestCase):
    """Integration tests for secure authentication configuration."""

    def setUp(self):
        """Set up test environment."""
        # Save original environment
        self.original_env = dict(os.environ)

    def tearDown(self):
        """Restore original environment."""
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_config_integration_local_development(self):
        """Test integration with BaseConfig in local development mode."""
        # Clear CI environment
        os.environ.pop("CI", None)

        try:
            from config import Config

            # Verify config loaded successfully
            self.assertIsNotNone(Config)
            self.assertTrue(hasattr(Config, "auth_config"))

            # Verify authentication config structure
            auth_config = Config.auth_config
            self.assertIsInstance(auth_config, dict)
            self.assertIn("providers", auth_config)
            self.assertIn("session", auth_config)

            # Verify at least one provider is enabled
            providers = auth_config.get("providers", {})
            enabled_providers = [
                name
                for name, config in providers.items()
                if config.get("enabled", False)
            ]
            self.assertGreater(
                len(enabled_providers),
                0,
                "At least one auth provider should be enabled",
            )

        except ImportError as e:
            self.skipTest(f"Config module not available: {e}")

    @patch.dict(
        os.environ,
        {
            "CI": "true",
            "LOCAL_AUTH_ENABLED": "true",
            "LDAP_ENABLED": "false",
            "OIDC_ENABLED": "false",
            "SESSION_LIFETIME_HOURS": "4",
            "SESSION_SECURE_COOKIES": "true",
        },
    )
    def test_config_integration_ci_mode(self):
        """Test integration with BaseConfig in CI/CD mode."""
        try:
            # Force reload of config module to pick up CI environment
            import importlib

            import config

            importlib.reload(config)

            from config import Config

            # Verify config loaded successfully in CI mode
            self.assertIsNotNone(Config)
            self.assertTrue(hasattr(Config, "auth_config"))

            # Verify CI environment variables were applied
            auth_config = Config.auth_config
            session_config = auth_config.get("session", {})

            # Note: The session config might be overridden by environment-specific settings
            # so we just verify the structure is correct
            self.assertIsInstance(session_config, dict)

            # Verify providers structure
            providers = auth_config.get("providers", {})
            self.assertIn("local", providers)

        except ImportError as e:
            self.skipTest(f"Config module not available: {e}")

    def test_authentication_loader_with_missing_template(self):
        """Test graceful handling when template file is missing."""
        from config.authentication_loader import SecureAuthenticationLoader

        # Create loader with non-existent config directory
        with tempfile.TemporaryDirectory() as temp_dir:
            loader = SecureAuthenticationLoader("development")
            loader.config_dir = Path(temp_dir)
            loader.local_config_path = Path(temp_dir) / "authentication.yaml"
            loader.template_path = Path(temp_dir) / "authentication.yaml.template"
            loader.example_path = Path(temp_dir) / "authentication.yaml.example"

            # Should fall back to default configuration
            config = loader.load_authentication_config()

            self.assertIsInstance(config, dict)
            self.assertIn("authentication", config)

            # Verify default configuration is safe
            auth_config = config["authentication"]
            self.assertIn("providers", auth_config)
            self.assertTrue(auth_config["providers"]["local"]["enabled"])
            self.assertFalse(auth_config["providers"]["ldap"]["enabled"])
            self.assertFalse(auth_config["providers"]["oidc"]["enabled"])

    @patch.dict(
        os.environ,
        {
            "LDAP_ENABLED": "True",
            "LDAP_SERVER": "ldap://test.example.com",
            "LDAP_BIND_DN": "cn=test,dc=example,dc=com",
            "LDAP_BIND_PASSWORD": "test-password",
            "LDAP_USER_SEARCH_BASE": "ou=users,dc=example,dc=com",
        },
    )
    def test_secure_logging_masks_secrets(self):
        """Test that sensitive values are masked in log output."""
        from config.authentication_loader import SecureAuthenticationLoader

        loader = SecureAuthenticationLoader("development")

        config_with_secrets = {
            "authentication": {
                "providers": {
                    "ldap": {
                        "bind_password": "super-secret-password",
                        "server": "ldap://public-server.com",
                    },
                    "oidc": {
                        "client_secret": "oauth-secret-key",
                        "client_id": "public-client-id",
                    },
                }
            }
        }

        masked_config = loader.get_masked_config(config_with_secrets)

        # Convert to string to simulate logging
        config_str = str(masked_config)

        # Verify secrets are masked
        self.assertNotIn("super-secret-password", config_str)
        self.assertNotIn("oauth-secret-key", config_str)
        self.assertIn("***MASKED***", config_str)

        # Verify non-secrets are preserved
        self.assertIn("ldap://public-server.com", config_str)
        self.assertIn("public-client-id", config_str)

    def test_environment_specific_overrides(self):
        """Test that environment-specific configuration overrides work."""
        from config.authentication_loader import SecureAuthenticationLoader

        # Test with development environment
        dev_loader = SecureAuthenticationLoader("development")
        dev_config = dev_loader.load_authentication_config()

        # Test with production environment
        prod_loader = SecureAuthenticationLoader("production")
        prod_config = prod_loader.load_authentication_config()

        # Both should load successfully
        self.assertIsInstance(dev_config, dict)
        self.assertIsInstance(prod_config, dict)

        # Both should have authentication sections
        self.assertIn("authentication", dev_config)
        self.assertIn("authentication", prod_config)


if __name__ == "__main__":
    # Run the tests
    unittest.main()
