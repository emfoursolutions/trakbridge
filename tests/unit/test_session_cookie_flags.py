# ABOUTME: Unit and integration tests for explicit session cookie security flags.
# ABOUTME: Covers SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, and SESSION_COOKIE_SECURE per environment.

import os
from unittest.mock import patch

import pytest

from app import create_app


# Common env vars needed to boot any environment without hitting real infra.
_BASE_ENV = {
    "SECRET_KEY": "test-secret-key-for-session-cookie-tests",
    "TRAKBRIDGE_ENCRYPTION_KEY": "test-encryption-key-for-testing-12345",
    "DATABASE_URL": "sqlite:///:memory:",
    "DB_TYPE": "",
}


class TestSessionCookieHttpOnly:
    """SESSION_COOKIE_HTTPONLY must be True in every environment."""

    @pytest.mark.parametrize("env", ["development", "testing", "production"])
    def test_httponly_always_true(self, env):
        """HttpOnly flag is set explicitly and is True in all environments."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": env}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app(env)
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True


class TestSessionCookieSameSite:
    """SESSION_COOKIE_SAMESITE must be 'Lax' in every environment."""

    @pytest.mark.parametrize("env", ["development", "testing", "production"])
    def test_samesite_always_lax(self, env):
        """SameSite flag is set explicitly to Lax in all environments."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": env}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app(env)
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


class TestSessionCookieSecure:
    """SESSION_COOKIE_SECURE is environment-aware and supports an env-var override."""

    def test_secure_true_in_production(self):
        """SESSION_COOKIE_SECURE is True for production."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": "production"}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app("production")
        assert app.config["SESSION_COOKIE_SECURE"] is True

    @pytest.mark.parametrize("env", ["development", "testing"])
    def test_secure_false_in_non_production_by_default(self, env):
        """SESSION_COOKIE_SECURE defaults to False outside production."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": env, "SESSION_COOKIE_SECURE": ""}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app(env)
        assert app.config["SESSION_COOKIE_SECURE"] is False

    @pytest.mark.parametrize("env", ["development", "testing"])
    def test_secure_override_via_env_var_in_non_production(self, env):
        """Setting SESSION_COOKIE_SECURE=true env var forces Secure on in non-production."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": env, "SESSION_COOKIE_SECURE": "true"}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app(env)
        assert app.config["SESSION_COOKIE_SECURE"] is True

    @pytest.mark.parametrize("override_val", ["1", "yes", "True", "TRUE"])
    def test_secure_override_truthy_values(self, override_val):
        """Various truthy string values for SESSION_COOKIE_SECURE env var enable Secure."""
        boot_env = {
            **_BASE_ENV,
            "FLASK_ENV": "development",
            "SESSION_COOKIE_SECURE": override_val,
        }
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app("development")
        assert app.config["SESSION_COOKIE_SECURE"] is True


class TestSessionCookieIntegration:
    """Integration check: Set-Cookie header on a response carries expected attributes."""

    def test_login_response_set_cookie_httponly(self):
        """Login response Set-Cookie header includes HttpOnly."""
        boot_env = {
            **_BASE_ENV,
            "FLASK_ENV": "testing",
            "SESSION_COOKIE_SECURE": "",
        }
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app("testing")

        with app.test_client() as client:
            # Trigger a session write by hitting the login page then posting credentials
            response = client.post(
                "/auth/login",
                data={"username": "admin", "password": "wrongpassword"},
                follow_redirects=False,
            )
            # The session cookie (if emitted) must carry HttpOnly
            set_cookie_header = response.headers.get("Set-Cookie", "")
            # If a cookie was set, verify it has HttpOnly
            if set_cookie_header:
                assert "HttpOnly" in set_cookie_header

            # Regardless of login outcome, config values must be set
            assert app.config["SESSION_COOKIE_HTTPONLY"] is True
            assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_session_cookie_config_values_accessible_via_test_client(self):
        """App config values are correct when accessed through a test-client context."""
        boot_env = {**_BASE_ENV, "FLASK_ENV": "testing"}
        with patch.dict(os.environ, boot_env, clear=False):
            app = create_app("testing")

        with app.test_client():
            assert app.config["SESSION_COOKIE_HTTPONLY"] is True
            assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
            assert app.config["SESSION_COOKIE_SECURE"] is False
