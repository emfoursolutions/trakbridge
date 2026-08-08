# ABOUTME: TDD tests for CSRF protection being enabled by default with bearer-auth exemptions.
# ABOUTME: Verifies session-authed POSTs require a valid CSRF token and bearer-authed POSTs do not.

import os
from unittest.mock import patch

import pytest

from app import create_app

# Minimal env required to boot without real infrastructure
_BASE_ENV = {
    "SECRET_KEY": "test-secret-key-for-csrf-tests",
    "TRAKBRIDGE_ENCRYPTION_KEY": "test-encryption-key-for-testing-12345",
    "DATABASE_URL": "sqlite:///:memory:",
    "DB_TYPE": "",
    "FLASK_ENV": "testing",
}


@pytest.fixture(scope="module")
def csrf_app():
    """Flask app for CSRF tests — identical bootstrap to the rest of the suite."""
    with patch.dict(os.environ, _BASE_ENV, clear=False):
        app = create_app("testing")
    return app


@pytest.fixture
def csrf_client(csrf_app):
    """Unauthenticated test client."""
    return csrf_app.test_client()


@pytest.fixture
def csrf_authed_client(csrf_app, csrf_client):
    """
    Authenticated test client with a valid Flask session.

    Creates a real user + session in the in-memory DB so that
    require_permission / require_auth decorators pass.
    """
    from database import db
    from models.user import AuthProvider, User, UserRole

    with csrf_app.app_context():
        db.create_all()

        # Avoid duplicate user across repeated invocations
        user = User.query.filter_by(username="csrftestadmin").first()
        if not user:
            user = User(
                username="csrftestadmin",
                email="csrftestadmin@test.com",
                full_name="CSRF Test Admin",
                role=UserRole.ADMIN,
                auth_provider=AuthProvider.LOCAL,
            )
            user.set_password("AdminPass123!")
            db.session.add(user)
            db.session.commit()

        from unittest.mock import patch as _patch

        with _patch(
            "config.authentication_loader.load_authentication_config",
            return_value={
                "session": {
                    "lifetime_hours": 8,
                    "cleanup_interval_minutes": 60,
                    "secure_cookies": False,
                },
                "provider_priority": ["local"],
                "providers": {
                    "local": {
                        "enabled": True,
                        "password_policy": {
                            "min_length": 8,
                            "require_uppercase": True,
                            "require_lowercase": True,
                            "require_numbers": True,
                            "require_special": False,
                        },
                    }
                },
            },
        ):
            from services.auth.auth_manager import AuthenticationManager

            manager = AuthenticationManager()
            sess = manager.create_session(user)

        with csrf_client.session_transaction() as flask_sess:
            flask_sess["session_id"] = sess.session_id
            flask_sess["user_id"] = user.id

    return csrf_client


# ---------------------------------------------------------------------------
# WTF_CSRF_CHECK_DEFAULT must be True
# ---------------------------------------------------------------------------


class TestCSRFDefaultEnabled:
    """The global CSRF check must be enabled by default."""

    def test_wtf_csrf_check_default_is_true(self, csrf_app):
        """WTF_CSRF_CHECK_DEFAULT must be True (or absent — Flask-WTF defaults to True)."""
        value = csrf_app.config.get("WTF_CSRF_CHECK_DEFAULT", True)
        assert value is True, (
            f"WTF_CSRF_CHECK_DEFAULT is {value!r}; expected True. "
            "CSRF protection is globally disabled!"
        )


# ---------------------------------------------------------------------------
# Session-authed POST without token → 400
# ---------------------------------------------------------------------------


class TestSessionAuthCSRFRequired:
    """Session-authenticated POSTs must be rejected without a valid CSRF token."""

    def test_session_post_without_csrf_token_returns_400(
        self, csrf_authed_client, csrf_app
    ):
        """
        RED test: POST to a session-authed route without a CSRF token must return 400.

        /auth/api/logout is session-protected and does not exempt CSRF.
        We hit the login page (GET) first so the Flask session is initialised,
        then POST without any CSRF token to verify the 400 rejection.
        """
        # GET login page to warm up the session (no CSRF token in the GET)
        csrf_authed_client.get("/auth/login")

        response = csrf_authed_client.post(
            "/auth/api/logout",
            content_type="application/json",
            headers={},  # Explicitly no X-CSRFToken
        )
        # Flask-WTF returns 400 when CSRF is missing and enabled
        assert response.status_code == 400, (
            f"Expected 400 (CSRF rejected), got {response.status_code}. "
            "CSRF enforcement may not be active."
        )


# ---------------------------------------------------------------------------
# Session-authed POST with valid token → success
# ---------------------------------------------------------------------------


class TestSessionAuthCSRFWithToken:
    """Session-authenticated POSTs must succeed when a valid CSRF token is supplied."""

    def test_session_post_with_csrf_token_succeeds(
        self, csrf_authed_client, csrf_app
    ):
        """
        GREEN test: POST to a session-authed route WITH a valid CSRF token must succeed.

        Flask-WTF stores a raw token in session["csrf_token"] and validates the
        signed version (URLSafeTimedSerializer with salt "wtf-csrf-token") sent
        in the X-CSRFToken header.  We:
        1. Trigger a GET so Flask-WTF populates session["csrf_token"].
        2. Read that raw token from the session.
        3. Sign it the same way Flask-WTF does and supply it in the header.
        """
        from itsdangerous import URLSafeTimedSerializer

        # GET login page — renders {{ csrf_token() }} which calls generate_csrf()
        # and stores the raw token in the session.
        csrf_authed_client.get("/auth/login")

        # Read the raw session token Flask-WTF set during the GET.
        with csrf_authed_client.session_transaction() as flask_sess:
            raw_token = flask_sess.get("csrf_token")

        # If the login page did not call generate_csrf() (e.g. template didn't
        # render it), inject a known raw token directly into the session.
        if raw_token is None:
            import hashlib
            raw_token = hashlib.sha1(b"test-csrf-seed").hexdigest()
            with csrf_authed_client.session_transaction() as flask_sess:
                flask_sess["csrf_token"] = raw_token

        # Build the signed token exactly as generate_csrf() does.
        secret_key = csrf_app.secret_key
        s = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
        signed_token = s.dumps(raw_token)

        response = csrf_authed_client.post(
            "/auth/api/logout",
            content_type="application/json",
            headers={"X-CSRFToken": signed_token},
        )

        # 200 success or 401 (user not found in this isolated test app) are fine.
        # 400 means CSRF rejection — that must not happen.
        assert response.status_code != 400, (
            f"Got 400 CSRF rejection even with a valid signed token present. "
            f"Status: {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Bearer-authed (exempt) endpoint succeeds without CSRF token
# ---------------------------------------------------------------------------


class TestBearerAuthCSRFExempt:
    """Inbound data endpoint (bearer-token authenticated) must not require a CSRF token."""

    def test_bearer_authed_inbound_endpoint_succeeds_without_csrf(
        self, csrf_client, csrf_app
    ):
        """
        GREEN test: POST to an exempted bearer-auth route must NOT return 400 CSRF rejection.

        The /api/inbound/<id>/data endpoint uses plugin.validate_inbound_request()
        (bearer-token auth) and must be exempt from CSRF.

        A 404 response is acceptable here (stream ID 99999 doesn't exist);
        a 400 with a CSRF error body is the failure condition.
        """
        with csrf_app.app_context():
            response = csrf_client.post(
                "/api/inbound/99999/data",
                content_type="application/json",
                data=b'{"test": true}',
                headers={},  # No CSRF token at all
            )
        # Must not be a CSRF 400 (exempt route)
        assert response.status_code != 400 or _is_not_csrf_rejection(response), (
            f"Got 400 that appears to be a CSRF rejection on an exempt route. "
            f"Body: {response.data[:200]}"
        )
        # Expected: 404 (stream not found) — confirm it's not a CSRF 400
        assert response.status_code in (404, 413, 429, 415, 400), (
            f"Unexpected status {response.status_code}"
        )
        # If it IS a 400, it must not be about CSRF
        if response.status_code == 400:
            assert _is_not_csrf_rejection(response), (
                f"CSRF rejection on bearer-authed exempt route! Body: {response.data[:200]}"
            )


def _is_not_csrf_rejection(response) -> bool:
    """Return True if the 400 response is NOT a CSRF rejection."""
    body = response.data.decode("utf-8", errors="replace").lower()
    return "csrf" not in body and "token" not in body


# ---------------------------------------------------------------------------
# MGRS conversion endpoints are exempt (optional-auth utility endpoints)
# ---------------------------------------------------------------------------


class TestOptionalAuthExemptEndpoints:
    """MGRS conversion endpoints (optional-auth) must not require CSRF tokens."""

    def test_convert_latlon_to_mgrs_exempt_from_csrf(self, csrf_client, csrf_app):
        """POST /api/convert-latlon-to-mgrs must not reject requests without CSRF token."""
        with csrf_app.app_context():
            response = csrf_client.post(
                "/api/convert-latlon-to-mgrs",
                content_type="application/json",
                json={"lat": 37.7749, "lon": -122.4194},
                headers={},  # No CSRF token
            )
        assert response.status_code != 400 or _is_not_csrf_rejection(response), (
            f"CSRF rejection on exempt MGRS route. Body: {response.data[:200]}"
        )

    def test_convert_mgrs_to_latlon_exempt_from_csrf(self, csrf_client, csrf_app):
        """POST /api/convert-mgrs-to-latlon must not reject requests without CSRF token."""
        with csrf_app.app_context():
            response = csrf_client.post(
                "/api/convert-mgrs-to-latlon",
                content_type="application/json",
                json={"mgrs": "38SMB4484"},
                headers={},  # No CSRF token
            )
        assert response.status_code != 400 or _is_not_csrf_rejection(response), (
            f"CSRF rejection on exempt MGRS route. Body: {response.data[:200]}"
        )
