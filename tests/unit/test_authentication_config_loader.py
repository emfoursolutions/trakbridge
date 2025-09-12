"""
Unit tests for the secure authentication configuration loader.

Tests the secure dual-configuration system that protects sensitive
authentication credentials while supporting both local development
and CI/CD deployment.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from config.authentication_loader import (
    SecureAuthenticationLoader,
    get_authentication_loader,
    load_authentication_config,
)


class TestSecureAuthenticationLoader(unittest.TestCase):
    """Test the SecureAuthenticationLoader class."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config" / "settings"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Create test template file
        self.template_content = """
authentication:
  session:
    lifetime_hours: ${SESSION_LIFETIME_HOURS:-8}
    secure_cookies: ${SESSION_SECURE_COOKIES:-true}
  
  provider_priority:
    - local
    - ldap
  
  providers:
    local:
      enabled: ${LOCAL_AUTH_ENABLED:-true}
      password_policy:
        min_length: ${PASSWORD_MIN_LENGTH:-8}
    
    ldap:
      enabled: ${LDAP_ENABLED:-false}
      server: "${LDAP_SERVER:-ldap.example.com}"
      bind_dn: "${LDAP_BIND_DN:-cn=service,dc=example,dc=com}"
      bind_password: "${LDAP_BIND_PASSWORD:-REPLACE_PASSWORD}"
"""

        # Create local config content with environment variable substitution
        self.local_content = """
authentication:
  session:
    lifetime_hours: ${SESSION_LIFETIME_HOURS:-12}
    secure_cookies: ${SESSION_SECURE_COOKIES:-false}
  
  provider_priority:
    - local
  
  providers:
    local:
      enabled: ${LOCAL_AUTH_ENABLED:-true}
      password_policy:
        min_length: ${PASSWORD_MIN_LENGTH:-4}
    
    ldap:
      enabled: ${LDAP_ENABLED:-false}
      default_role: "${LDAP_DEFAULT_ROLE:-user}"
"""

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_template_file(self):
        """Create a test template file."""
        template_path = self.config_dir / "authentication.yaml.template"
        with open(template_path, "w") as f:
            f.write(self.template_content)
        return template_path

    def _create_local_file(self):
        """Create a test local config file."""
        local_path = self.config_dir / "authentication.yaml"
        with open(local_path, "w") as f:
            f.write(self.local_content)
        return local_path

    def _create_loader(self, environment="development"):
        """Create a loader with test config directory."""
        loader = SecureAuthenticationLoader(environment)
        loader.config_dir = self.config_dir
        loader.local_config_path = self.config_dir / "authentication.yaml"
        loader.template_path = self.config_dir / "authentication.yaml.template"
        loader.example_path = self.config_dir / "authentication.yaml.example"
        return loader

    @patch.dict(os.environ, {}, clear=True)
    def test_local_config_priority_in_development(self):
        """Test that local config takes priority in development mode."""
        self._create_template_file()
        self._create_local_file()

        loader = self._create_loader("development")
        loader.is_ci = False  # Simulate local development

        config = loader.load_authentication_config()

        # Should use local config values
        self.assertEqual(config["authentication"]["session"]["lifetime_hours"], 12)
        self.assertFalse(config["authentication"]["session"]["secure_cookies"])
        self.assertEqual(
            config["authentication"]["providers"]["local"]["password_policy"][
                "min_length"
            ],
            4,
        )

    @patch.dict(
        os.environ,
        {
            "CI": "true",
            "SESSION_LIFETIME_HOURS": "6",
            "SESSION_SECURE_COOKIES": "true",
            "LOCAL_AUTH_ENABLED": "false",
            "LDAP_ENABLED": "true",
            "LDAP_SERVER": "ldap://ci-test.com",
            "LDAP_BIND_DN": "cn=citest,dc=test,dc=com",
            "LDAP_BIND_PASSWORD": "ci-secret",
            "PASSWORD_MIN_LENGTH": "10",
        },
    )
    def test_template_config_with_environment_variables(self):
        """Test template config with environment variable substitution."""
        self._create_template_file()
        self._create_local_file()  # Should be ignored in CI mode

        loader = self._create_loader("production")
        loader.is_ci = True  # Simulate CI environment

        config = loader.load_authentication_config()

        # Should use environment variables from template
        self.assertEqual(config["authentication"]["session"]["lifetime_hours"], 6)
        self.assertTrue(config["authentication"]["session"]["secure_cookies"])
        self.assertFalse(config["authentication"]["providers"]["local"]["enabled"])
        self.assertTrue(config["authentication"]["providers"]["ldap"]["enabled"])
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["server"],
            "ldap://ci-test.com",
        )
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["bind_dn"],
            "cn=citest,dc=test,dc=com",
        )
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["bind_password"], "ci-secret"
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_template_with_defaults(self):
        """Test template config uses default values when env vars not set."""
        self._create_template_file()

        loader = self._create_loader("development")
        loader.is_ci = True  # Force template usage

        config = loader.load_authentication_config()

        # Should use default values from template
        self.assertEqual(config["authentication"]["session"]["lifetime_hours"], 8)
        self.assertTrue(config["authentication"]["session"]["secure_cookies"])
        self.assertTrue(config["authentication"]["providers"]["local"]["enabled"])
        self.assertFalse(config["authentication"]["providers"]["ldap"]["enabled"])
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["server"], "ldap.example.com"
        )

    def test_fallback_to_default_config(self):
        """Test fallback to default safe configuration."""
        loader = self._create_loader("development")

        config = loader.load_authentication_config()

        # Should use default safe config
        auth_config = config["authentication"]
        self.assertIn("session", auth_config)
        self.assertIn("providers", auth_config)
        self.assertTrue(auth_config["providers"]["local"]["enabled"])
        self.assertFalse(auth_config["providers"]["ldap"]["enabled"])

    def test_configuration_validation(self):
        """Test configuration validation."""
        loader = self._create_loader("development")

        # Valid configuration
        valid_config = {"authentication": {"providers": {"local": {"enabled": True}}}}
        self.assertIsNone(loader.validate_config(valid_config))

        # Invalid configuration - no providers enabled
        invalid_config = {
            "authentication": {
                "providers": {"local": {"enabled": False}, "ldap": {"enabled": False}}
            }
        }
        error = loader.validate_config(invalid_config)
        self.assertIsNotNone(error)
        self.assertIn("No authentication providers are enabled", error)

        # Invalid configuration - missing providers section
        invalid_config2 = {"authentication": {}}
        error2 = loader.validate_config(invalid_config2)
        self.assertIsNotNone(error2)
        self.assertIn("Missing 'providers' section", error2)

    def test_ldap_validation(self):
        """Test LDAP-specific validation."""
        loader = self._create_loader("development")

        # Valid LDAP configuration
        valid_ldap_config = {
            "authentication": {
                "providers": {
                    "ldap": {
                        "enabled": True,
                        "server": "ldap://test.com",
                        "bind_dn": "cn=test,dc=com",
                        "bind_password": "password",
                        "user_search_base": "ou=users,dc=com",
                    }
                }
            }
        }
        self.assertIsNone(loader.validate_config(valid_ldap_config))

        # Invalid LDAP configuration - missing required fields
        invalid_ldap_config = {
            "authentication": {
                "providers": {
                    "ldap": {
                        "enabled": True,
                        "server": "ldap://test.com",
                        # Missing bind_dn, bind_password, user_search_base
                    }
                }
            }
        }
        error = loader.validate_config(invalid_ldap_config)
        self.assertIsNotNone(error)
        self.assertIn("LDAP enabled but missing required field", error)

    def test_oidc_validation(self):
        """Test OIDC-specific validation."""
        loader = self._create_loader("development")

        # Valid OIDC configuration
        valid_oidc_config = {
            "authentication": {
                "providers": {
                    "oidc": {
                        "enabled": True,
                        "issuer": "https://provider.com",
                        "client_id": "client123",
                        "client_secret": "secret123",
                    }
                }
            }
        }
        self.assertIsNone(loader.validate_config(valid_oidc_config))

        # Invalid OIDC configuration - missing required fields
        invalid_oidc_config = {
            "authentication": {
                "providers": {
                    "oidc": {
                        "enabled": True,
                        "issuer": "https://provider.com",
                        # Missing client_id, client_secret
                    }
                }
            }
        }
        error = loader.validate_config(invalid_oidc_config)
        self.assertIsNotNone(error)
        self.assertIn("OIDC enabled but missing required field", error)

    def test_masked_config_output(self):
        """Test that sensitive values are masked in output."""
        loader = self._create_loader("development")

        config_with_secrets = {
            "authentication": {
                "providers": {
                    "ldap": {"bind_password": "secret123", "server": "ldap://test.com"},
                    "oidc": {
                        "client_secret": "oauth_secret",
                        "client_id": "public_client_id",
                    },
                }
            }
        }

        masked_config = loader.get_masked_config(config_with_secrets)

        # Sensitive fields should be masked
        self.assertEqual(
            masked_config["authentication"]["providers"]["ldap"]["bind_password"],
            "***MASKED***",
        )
        self.assertEqual(
            masked_config["authentication"]["providers"]["oidc"]["client_secret"],
            "***MASKED***",
        )

        # Non-sensitive fields should remain
        self.assertEqual(
            masked_config["authentication"]["providers"]["ldap"]["server"],
            "ldap://test.com",
        )
        self.assertEqual(
            masked_config["authentication"]["providers"]["oidc"]["client_id"],
            "public_client_id",
        )

    @patch.dict(os.environ, {"CI": "true"})
    def test_ci_detection(self):
        """Test CI environment detection."""
        loader = self._create_loader("production")
        self.assertTrue(loader.is_ci)

        with patch.dict(os.environ, {}, clear=True):
            loader2 = self._create_loader("development")
            self.assertFalse(loader2.is_ci)

    def test_boolean_string_conversion(self):
        """Test that string boolean values are converted properly."""
        loader = self._create_loader("development")

        # Test boolean conversion
        content = 'enabled: "true"\nother: "false"'
        converted = loader._convert_boolean_strings(content)

        self.assertIn("enabled: true", converted)
        self.assertIn("other: false", converted)

    @patch.dict(os.environ, {"TEST_VAR": "test_value"})
    def test_environment_variable_substitution(self):
        """Test environment variable substitution patterns."""
        loader = self._create_loader("development")

        # Test substitution with default
        content = 'setting: "${TEST_VAR:-default_value}"'
        result = loader._substitute_environment_variables(content)
        self.assertIn('setting: "test_value"', result)

        # Test substitution with missing var (should use default)
        content2 = 'setting: "${MISSING_VAR:-default_value}"'
        result2 = loader._substitute_environment_variables(content2)
        self.assertIn('setting: "default_value"', result2)

    @patch.dict(
        os.environ,
        {
            "SESSION_LIFETIME_HOURS": "24",
            "LDAP_ENABLED": "true",
            "LDAP_DEFAULT_ROLE": "admin",
        },
    )
    def test_local_config_with_environment_substitution(self):
        """Test that local config now supports environment variable substitution."""
        self._create_local_file()

        loader = self._create_loader("development")
        loader.is_ci = False  # Simulate local development

        config = loader.load_authentication_config()

        # Should use environment variables from local config
        self.assertEqual(config["authentication"]["session"]["lifetime_hours"], 24)
        self.assertTrue(config["authentication"]["providers"]["ldap"]["enabled"])
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["default_role"], "admin"
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_local_config_environment_defaults(self):
        """Test that local config uses defaults when environment variables not set."""
        self._create_local_file()

        loader = self._create_loader("development")
        loader.is_ci = False  # Simulate local development

        config = loader.load_authentication_config()

        # Should use default values from local config
        self.assertEqual(config["authentication"]["session"]["lifetime_hours"], 12)
        self.assertFalse(config["authentication"]["session"]["secure_cookies"])
        self.assertTrue(config["authentication"]["providers"]["local"]["enabled"])
        self.assertFalse(config["authentication"]["providers"]["ldap"]["enabled"])
        self.assertEqual(
            config["authentication"]["providers"]["ldap"]["default_role"], "user"
        )


class TestAuthenticationLoaderIntegration(unittest.TestCase):
    """Integration tests for the authentication loader."""

    def test_singleton_loader_instance(self):
        """Test that get_authentication_loader returns singleton instance."""
        loader1 = get_authentication_loader("development")
        loader2 = get_authentication_loader("development")

        self.assertIs(loader1, loader2)

        # Different environment should create new instance
        loader3 = get_authentication_loader("production")
        self.assertIsNot(loader1, loader3)

    def test_load_authentication_config_function(self):
        """Test the convenience function for loading config."""
        config = load_authentication_config("development")

        self.assertIsInstance(config, dict)
        self.assertIn("authentication", config)
        auth_config = config["authentication"]
        self.assertIn("providers", auth_config)
        self.assertIn("session", auth_config)

    @patch("config.authentication_loader.logger")
    def test_configuration_logging(self, mock_logger):
        """Test that configuration loading is properly logged."""
        loader = SecureAuthenticationLoader("development")
        config = loader.load_authentication_config()

        # Verify debug logging was called
        mock_logger.debug.assert_called()

        # Verify validation logging
        validation_error = loader.validate_config(config)
        if validation_error is None:
            mock_logger.debug.assert_any_call(
                "Authentication configuration validation passed"
            )


if __name__ == "__main__":
    # Run the tests
    unittest.main()
