"""
ABOUTME: Test suite for Phase 3A config migration to centralized ConfigHelper patterns
ABOUTME: Validates ConfigHelper usage in migrated services, especially LDAP and OIDC providers

File: tests/test_phase3a_config_migration.py

Description:
    Comprehensive test suite for Phase 3A configuration migration validation.
    Tests that migrated services properly use ConfigHelper for nested config
    access and that the major config pattern improvements are working correctly.
    
    Key focus areas:
    - LDAP provider's 13-line config pattern reduction
    - OIDC provider's nested config access improvements  
    - Health service's config access pattern fixes
    - ConfigHelper functionality in migrated services
    
Author: Emfour Solutions
Created: 2025-09-03
"""

import pytest
import importlib
from unittest.mock import patch, MagicMock

from utils.config_helpers import ConfigHelper, nested_config_get


class TestConfigHelperIntegration:
    """Test ConfigHelper integration in Phase 3A migrated services"""

    def test_config_helper_import_in_migrated_services(self):
        """Test that services requiring ConfigHelper import it correctly"""
        services_with_config_patterns = [
            "services.auth.ldap_provider",
            "services.auth.oidc_provider",
            "services.health_service",
        ]

        for module_name in services_with_config_patterns:
            try:
                module_source = importlib.util.find_spec(module_name)
                if module_source and module_source.origin:
                    with open(module_source.origin, "r") as f:
                        content = f.read()
                        assert (
                            "from utils.config_helpers import ConfigHelper" in content
                        ), f"{module_name} should import ConfigHelper"

            except ImportError as e:
                pytest.fail(f"Could not check imports in {module_name}: {e}")


class TestLDAPProviderConfigMigration:
    """Test LDAP provider's major 13-line config pattern migration"""

    def test_ldap_provider_uses_config_helper(self):
        """Test that LDAP provider uses ConfigHelper instead of nested dict access"""
        try:
            from services.auth.ldap_provider import LDAPAuthProvider

            # Mock config with both old nested and new flat formats
            test_config = {
                "user_search": {
                    "base_dn": "ou=users,dc=test,dc=com",
                    "search_filter": "(uid={username})",
                    "attributes": {"username": "uid", "email": "mail"},
                },
                "user_search_base": "ou=fallback,dc=test,dc=com",
                "user_search_filter": "(sAMAccountName={username})",
                "attributes": {"username": "sAMAccountName"},
            }

            # Test that provider can handle the config
            # Note: We'd need to mock LDAP3 dependencies for full instantiation
            # For now, test the config access pattern through code inspection

            module_source = importlib.util.find_spec("services.auth.ldap_provider")
            if module_source and module_source.origin:
                with open(module_source.origin, "r") as f:
                    content = f.read()

                    # Should use ConfigHelper pattern
                    assert "helper = ConfigHelper(config)" in content
                    assert "helper.get(" in content

                    # Should not have the old 13-line nested pattern
                    old_pattern = 'user_search_config = config.get("user_search", {})'
                    assert (
                        old_pattern not in content
                    ), "LDAP provider still contains old nested config pattern"

        except ImportError:
            pytest.skip("LDAP provider dependencies not available")

    def test_ldap_config_helper_pattern_functionality(self):
        """Test that the new LDAP config pattern works correctly"""
        # Test the ConfigHelper pattern that replaced the 13-line code
        config = {
            "user_search": {
                "base_dn": "ou=users,dc=test,dc=com",
                "search_filter": "(uid={username})",
                "attributes": {"username": "uid"},
            },
            "user_search_base": "ou=fallback,dc=test,dc=com",
        }

        helper = ConfigHelper(config)

        # Test the new pattern (3 lines vs 13)
        base_dn = helper.get("user_search.base_dn", helper.get("user_search_base", ""))
        search_filter = helper.get(
            "user_search.search_filter",
            helper.get("user_search_filter", "(sAMAccountName={username})"),
        )
        attributes = helper.get("user_search.attributes", helper.get("attributes", {}))

        # Should get values from nested config
        assert base_dn == "ou=users,dc=test,dc=com"
        assert search_filter == "(uid={username})"
        assert attributes == {"username": "uid"}

    def test_ldap_config_fallback_functionality(self):
        """Test that LDAP config fallback (old flat format) works"""
        # Config with only flat format (fallback)
        config = {
            "user_search_base": "ou=fallback,dc=test,dc=com",
            "user_search_filter": "(sAMAccountName={username})",
            "attributes": {"username": "sAMAccountName"},
        }

        helper = ConfigHelper(config)

        # New pattern with fallback
        base_dn = helper.get("user_search.base_dn", helper.get("user_search_base", ""))
        search_filter = helper.get(
            "user_search.search_filter",
            helper.get("user_search_filter", "(sAMAccountName={username})"),
        )
        attributes = helper.get("user_search.attributes", helper.get("attributes", {}))

        # Should get values from flat config
        assert base_dn == "ou=fallback,dc=test,dc=com"
        assert search_filter == "(sAMAccountName={username})"
        assert attributes == {"username": "sAMAccountName"}


class TestOIDCProviderConfigMigration:
    """Test OIDC provider's nested config access improvements"""

    def test_oidc_provider_uses_config_helper(self):
        """Test that OIDC provider uses ConfigHelper for cleaner config access"""
        try:
            module_source = importlib.util.find_spec("services.auth.oidc_provider")
            if module_source and module_source.origin:
                with open(module_source.origin, "r") as f:
                    content = f.read()

                    # Should import and use ConfigHelper
                    assert "from utils.config_helpers import ConfigHelper" in content
                    assert "helper = ConfigHelper(" in content
                    assert "provider_helper = ConfigHelper(" in content

        except ImportError:
            pytest.skip("OIDC provider dependencies not available")

    def test_oidc_config_pattern_functionality(self):
        """Test the OIDC config pattern improvements"""
        config = {
            "providers": {
                "azure": {
                    "client_id": "test-client-id",
                    "client_secret": "test-secret",
                    "discovery_url": "https://login.microsoftonline.com/tenant/.well-known/openid_configuration",
                    "scope": "openid profile email",
                }
            }
        }

        # Test the new pattern
        helper = ConfigHelper(config)
        providers_config = helper.get("providers", {})

        provider_helper = ConfigHelper(providers_config.get("azure", {}))
        client_id = provider_helper.get("client_id", "")
        client_secret = provider_helper.get("client_secret", "")
        discovery_url = provider_helper.get("discovery_url", "")
        scope = provider_helper.get("scope", "openid profile email")

        # Should extract config correctly
        assert client_id == "test-client-id"
        assert client_secret == "test-secret"
        assert (
            discovery_url
            == "https://login.microsoftonline.com/tenant/.well-known/openid_configuration"
        )
        assert scope == "openid profile email"


class TestHealthServiceConfigMigration:
    """Test Health Service's config access pattern fixes (lines 370,375)"""

    def test_health_service_uses_config_helper(self):
        """Test that Health Service uses ConfigHelper for nested dict access"""
        module_source = importlib.util.find_spec("services.health_service")
        if module_source and module_source.origin:
            with open(module_source.origin, "r") as f:
                content = f.read()

                # Should import ConfigHelper
                assert "from utils.config_helpers import ConfigHelper" in content

                # Should use helper pattern instead of nested gets
                assert "helper = ConfigHelper(results)" in content
                assert "helper.get_int(" in content

                # Should not have old nested pattern
                old_pattern1 = 'results.get("error_streams", {}).get("count", 0)'
                old_pattern2 = 'results.get("active_streams", {}).get("count", 0)'

                assert (
                    old_pattern1 not in content
                ), "Health service still has old nested pattern"
                assert (
                    old_pattern2 not in content
                ), "Health service still has old nested pattern"

    def test_health_service_config_pattern_functionality(self):
        """Test that Health Service config pattern improvements work correctly"""
        # Mock results data like health service would have
        results = {
            "error_streams": {"count": 2, "status": "error"},
            "active_streams": {"count": 0, "status": "inactive"},
        }

        # Test new pattern
        helper = ConfigHelper(results)
        error_count = helper.get_int("error_streams.count", 0)
        active_count = helper.get_int("active_streams.count", 0)

        # Should work correctly
        assert error_count == 2
        assert active_count == 0

        # Test the logic that would be in health service
        warnings = []
        if error_count > 0:
            warnings.append(f"{error_count} streams with errors")
        if active_count == 0:
            warnings.append("No active streams")

        assert len(warnings) == 2
        assert "2 streams with errors" in warnings
        assert "No active streams" in warnings


class TestConfigMigrationBenefits:
    """Test the benefits and improvements from config migration"""

    def test_config_helper_reduces_boilerplate(self):
        """Test that ConfigHelper reduces config access boilerplate"""
        complex_config = {
            "level1": {"level2": {"level3": {"target_value": "found_it"}}}
        }

        # Old way (what we migrated from)
        old_way = (
            complex_config.get("level1", {})
            .get("level2", {})
            .get("level3", {})
            .get("target_value", "default")
        )

        # New way (what we migrated to)
        helper = ConfigHelper(complex_config)
        new_way = helper.get("level1.level2.level3.target_value", "default")

        # Should get same result with cleaner syntax
        assert old_way == new_way == "found_it"

    def test_config_helper_handles_missing_keys_gracefully(self):
        """Test that ConfigHelper handles missing nested keys gracefully"""
        incomplete_config = {
            "level1": {
                "level2": {}
                # level3 missing
            }
        }

        helper = ConfigHelper(incomplete_config)
        result = helper.get("level1.level2.level3.target_value", "default_value")

        # Should return default without error
        assert result == "default_value"

    def test_config_helper_type_safety(self):
        """Test that ConfigHelper provides type-safe config access"""
        config = {
            "string_value": "hello",
            "int_value": "42",  # String that should convert to int
            "bool_value": "true",  # String that should convert to bool
            "list_value": ["item1", "item2"],
        }

        helper = ConfigHelper(config)

        # Test type-safe access
        string_val = helper.get_str("string_value", "")
        int_val = helper.get_int("int_value", 0)
        bool_val = helper.get_bool("bool_value", False)
        list_val = helper.get_list("list_value", [])

        assert string_val == "hello"
        assert int_val == 42  # Should be converted to int
        assert bool_val == True  # Should be converted to bool
        assert list_val == ["item1", "item2"]

    def test_config_migration_maintains_flexibility(self):
        """Test that config migration maintains configuration flexibility"""
        # Test both old and new config formats work
        old_format_config = {
            "user_search_base": "ou=users,dc=old,dc=com",
            "user_search_filter": "(sAMAccountName={username})",
        }

        new_format_config = {
            "user_search": {
                "base_dn": "ou=users,dc=new,dc=com",
                "search_filter": "(uid={username})",
            }
        }

        # Both should work with the migrated pattern
        for config in [old_format_config, new_format_config]:
            helper = ConfigHelper(config)

            # This is the pattern used in migrated LDAP provider
            base_dn = helper.get(
                "user_search.base_dn", helper.get("user_search_base", "")
            )
            search_filter = helper.get(
                "user_search.search_filter",
                helper.get("user_search_filter", "(sAMAccountName={username})"),
            )

            # Should get appropriate values from each format
            assert base_dn != ""  # Should find value in either format
            
            # Check that we get the appropriate value based on config format
            if "user_search" in config:  # New format
                assert search_filter == "(uid={username})"
            else:  # Old format
                assert search_filter == "(sAMAccountName={username})"
