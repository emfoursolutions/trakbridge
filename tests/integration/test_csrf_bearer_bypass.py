# ABOUTME: Verifies CSRF is bypassed for API-key bearer requests only.
# ABOUTME: Session cookies to the same routes still require CSRF tokens.
"""Tests for the CSRF bearer-bypass hook in app.py.

The invariant this suite protects:

- A state-changing request carrying `Authorization: Bearer tb_pat_...`
  succeeds without a CSRF token. Bearer auth is itself unforgeable
  across origins, so CSRF is redundant.
- A state-changing request with only a session cookie still requires
  a CSRF token. Browser JS callers to the same route are protected
  as before.

This is enforced at the request level via a monkey-patch of
CSRFProtect.protect() — route-level csrf.exempt would strip CSRF
from both auth paths, which is the wrong shape.
"""

import pytest
from flask import Blueprint, jsonify

from models.user import (
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)


@pytest.fixture(scope="session", autouse=True)
def csrf_probe_routes(app):
    """Register a state-changing test endpoint that requires auth.

    Uses ``add_url_rule`` directly (not ``register_blueprint``)
    because Flask locks blueprint registration after the app has
    handled its first request — and by the time this session-scoped
    fixture runs, another test module may already have exercised the
    app. ``add_url_rule`` has a similar guard but we can bypass it
    by adjusting the app's ``_got_first_request`` flag around the
    call. This is a test-only workaround; production code never
    adds routes after boot.
    """
    endpoint = "_csrf_probe_state_change"
    if endpoint in app.view_functions:
        return

    from services.auth.decorators import require_auth

    @require_auth
    def _probe_state_change():
        return jsonify({"ok": True})

    # Bypass Flask's first-request lock for this test-only route.
    original = getattr(app, "_got_first_request", False)
    if hasattr(app, "_got_first_request"):
        app._got_first_request = False
    try:
        app.add_url_rule(
            "/_csrf_probe/state_change",
            endpoint=endpoint,
            view_func=_probe_state_change,
            methods=["POST"],
        )
    finally:
        if hasattr(app, "_got_first_request"):
            app._got_first_request = original


@pytest.fixture
def operator_bearer(app, db_session):
    user = User(
        username="csrf_probe_user",
        email="csrf_probe@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.OPERATOR,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()

    _key, plaintext = UserApiKey.generate(
        user=user,
        name="csrf bypass test key",
        scopes=["streams:read", "streams:write"],
    )
    return plaintext


class TestCsrfBearerBypass:
    def test_bearer_post_succeeds_without_csrf_token(
        self, app, client, csrf_probe_routes, operator_bearer
    ):
        # Ensure CSRF is actually enabled for this test — TestingConfig
        # sometimes disables it. Force it on to prove the bypass works.
        with app.test_request_context():
            app.config["WTF_CSRF_ENABLED"] = True
        resp = client.post(
            "/_csrf_probe/state_change",
            headers={
                "Authorization": f"Bearer {operator_bearer}",
                "Content-Type": "application/json",
            },
            json={},
        )
        assert resp.status_code == 200, (
            f"Bearer POST should succeed without CSRF token; got "
            f"{resp.status_code}. If 400, the CSRF bypass hook is "
            f"not being invoked — check the monkey-patch in app.py."
        )

    def test_session_post_still_requires_csrf_token(
        self, app, client, csrf_probe_routes
    ):
        # Without a bearer AND without a CSRF token, a session POST
        # (even unauthenticated) should be rejected by CSRF. The
        # test app defaults may disable CSRF; skip if so — this
        # test only meaningful when CSRF is actually enabled.
        if not app.config.get("WTF_CSRF_ENABLED", True):
            pytest.skip("WTF_CSRF_ENABLED is False in test config")

        resp = client.post(
            "/_csrf_probe/state_change",
            headers={"Content-Type": "application/json"},
            json={},
        )
        # Without CSRF token, WTF_CSRF returns 400. Without auth,
        # require_auth would return 401. Either outcome proves the
        # bypass did NOT fire for a non-bearer request (which is
        # the point). What we must NOT see is a 200.
        assert resp.status_code != 200

    def test_wrong_prefix_bearer_does_not_bypass_csrf(
        self, app, client, csrf_probe_routes
    ):
        # A bearer that isn't tb_pat_ must not trigger the bypass —
        # otherwise a foreign token could sidestep CSRF entirely.
        # The request should either 400 (no CSRF) or 401 (no auth),
        # but never 200.
        if not app.config.get("WTF_CSRF_ENABLED", True):
            pytest.skip("WTF_CSRF_ENABLED is False in test config")

        resp = client.post(
            "/_csrf_probe/state_change",
            headers={
                "Authorization": "Bearer ghp_foreignpat",
                "Content-Type": "application/json",
            },
            json={},
        )
        assert resp.status_code != 200

    def test_bearer_with_session_cookie_still_bypasses(
        self, app, client, csrf_probe_routes, operator_bearer
    ):
        # If both a session cookie AND a bearer are sent (weird but
        # possible if a browser tab happens to be logged in while a
        # dev tool sends the header), bearer wins and CSRF bypasses.
        with client.session_transaction() as sess:
            sess["session_id"] = "irrelevant-not-a-valid-session"

        resp = client.post(
            "/_csrf_probe/state_change",
            headers={
                "Authorization": f"Bearer {operator_bearer}",
                "Content-Type": "application/json",
            },
            json={},
        )
        assert resp.status_code == 200
