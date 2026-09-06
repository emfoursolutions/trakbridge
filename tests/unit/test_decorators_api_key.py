# ABOUTME: Tests for API-key auth wiring in services/auth/decorators.py.
# ABOUTME: Covers bearer resolution, scope enforcement, and session_only.
"""Tests for the API-key decorator changes landed in commit 4."""

import pytest
from flask import Blueprint, jsonify

from models.user import (
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)
from services.auth.decorators import (
    get_current_user,
    require_auth,
    require_permission,
    session_only,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operator_user(app, db_session):
    user = User(
        username="operator_apikey",
        email="operator_apikey@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.OPERATOR,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def read_only_key(operator_user):
    key, plaintext = UserApiKey.generate(
        user=operator_user,
        name="read only",
        scopes=["streams:read"],
    )
    return key, plaintext


@pytest.fixture
def write_key(operator_user):
    key, plaintext = UserApiKey.generate(
        user=operator_user,
        name="read+write",
        scopes=["streams:read", "streams:write"],
    )
    return key, plaintext


@pytest.fixture(scope="session", autouse=True)
def probe_routes(app):
    """Register throwaway endpoints on the app for decorator exercise.

    Uses ``add_url_rule`` directly (not ``register_blueprint``)
    because Flask locks blueprint registration after the app has
    handled its first request — and by the time this session-scoped
    fixture runs, another test module may already have exercised the
    app. ``add_url_rule`` has a similar guard but we can bypass it
    by adjusting the app's ``_got_first_request`` flag around the
    call. This is a test-only workaround; production code never
    adds routes after boot.
    """
    if "_probe_require_auth" in app.view_functions:
        return

    @require_auth
    def _probe_require_auth():
        user = get_current_user()
        return jsonify({"ok": True, "user": user.username})

    @require_permission("streams", "read")
    def _probe_streams_read():
        return jsonify({"ok": True})

    @require_permission("streams", "write")
    def _probe_streams_write():
        return jsonify({"ok": True})

    @session_only
    @require_auth
    def _probe_session_only():
        return jsonify({"ok": True})

    original = getattr(app, "_got_first_request", False)
    if hasattr(app, "_got_first_request"):
        app._got_first_request = False
    try:
        app.add_url_rule(
            "/_probe/require_auth",
            endpoint="_probe_require_auth",
            view_func=_probe_require_auth,
        )
        app.add_url_rule(
            "/_probe/streams_read",
            endpoint="_probe_streams_read",
            view_func=_probe_streams_read,
        )
        app.add_url_rule(
            "/_probe/streams_write",
            endpoint="_probe_streams_write",
            view_func=_probe_streams_write,
            methods=["POST"],
        )
        app.add_url_rule(
            "/_probe/session_only",
            endpoint="_probe_session_only",
            view_func=_probe_session_only,
        )
    finally:
        if hasattr(app, "_got_first_request"):
            app._got_first_request = original

    # POST endpoint needs CSRF exemption because our test client
    # won't have a CSRF token. Bearer bypass (commit 6) covers the
    # bearer-authenticated tests; this handles session-cookie-less
    # POST for the scope-enforcement tests.
    app.csrf.exempt(app.view_functions["_probe_streams_write"])


# ---------------------------------------------------------------------------
# Bearer resolution in get_current_user
# ---------------------------------------------------------------------------


class TestBearerResolution:
    def test_valid_bearer_authenticates(
        self, app, client, probe_routes, read_only_key
    ):
        _key, plaintext = read_only_key
        resp = client.get(
            "/_probe/require_auth",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["user"] == "operator_apikey"

    def test_no_header_falls_through_to_session(
        self, app, client, probe_routes
    ):
        # No session cookie, no bearer → 401 (JSON path).
        resp = client.get(
            "/_probe/require_auth",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_wrong_prefix_falls_through_to_session(
        self, app, client, probe_routes
    ):
        # A foreign bearer must not authenticate; no session either
        # → 401 (JSON path).
        resp = client.get(
            "/_probe/require_auth",
            headers={
                "Authorization": "Bearer ghp_foreignpat",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_invalid_bearer_returns_401(
        self, app, client, probe_routes
    ):
        # Well-formed tb_pat_ token that doesn't exist in the DB.
        resp = client.get(
            "/_probe/require_auth",
            headers={
                "Authorization": "Bearer tb_pat_" + "x" * 43,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_revoked_key_returns_401(
        self, app, client, probe_routes, read_only_key, db_session
    ):
        key, plaintext = read_only_key
        key.revoke()
        db_session.commit()
        resp = client.get(
            "/_probe/require_auth",
            headers={
                "Authorization": f"Bearer {plaintext}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Scope enforcement in require_permission
# ---------------------------------------------------------------------------


class TestScopeEnforcement:
    def test_key_with_matching_scope_allowed(
        self, app, client, probe_routes, read_only_key
    ):
        _key, plaintext = read_only_key
        resp = client.get(
            "/_probe/streams_read",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 200

    def test_key_missing_scope_denied(
        self, app, client, probe_routes, read_only_key
    ):
        # streams:read key hitting streams:write endpoint → 403.
        _key, plaintext = read_only_key
        resp = client.post(
            "/_probe/streams_write",
            headers={
                "Authorization": f"Bearer {plaintext}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert "streams:write" in body.get("message", "")

    def test_key_with_write_scope_allowed_on_write(
        self, app, client, probe_routes, write_key
    ):
        _key, plaintext = write_key
        resp = client.post(
            "/_probe/streams_write",
            headers={
                "Authorization": f"Bearer {plaintext}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200

    def test_key_scope_intersected_with_owner_permission(
        self, app, client, probe_routes, write_key, db_session
    ):
        # Even if a key claims streams:write, demoting its owner to
        # VIEWER must strip that permission — user.can_access is the
        # first gate before the scope check.
        key, plaintext = write_key
        key.user.role = UserRole.VIEWER
        db_session.commit()
        resp = client.post(
            "/_probe/streams_write",
            headers={
                "Authorization": f"Bearer {plaintext}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# session_only decorator
# ---------------------------------------------------------------------------


class TestSessionOnly:
    def test_bearer_denied_on_session_only(
        self, app, client, probe_routes, write_key
    ):
        _key, plaintext = write_key
        resp = client.get(
            "/_probe/session_only",
            headers={
                "Authorization": f"Bearer {plaintext}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["error"] == "Session required"

    def test_bearer_denied_logs_audit(
        self, app, client, probe_routes, write_key, caplog
    ):
        _key, plaintext = write_key
        import logging
        with caplog.at_level(logging.WARNING):
            client.get(
                "/_probe/session_only",
                headers={
                    "Authorization": f"Bearer {plaintext}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        assert any(
            "session_only_denied" in rec.message for rec in caplog.records
        )

    def test_invalid_bearer_also_denied_early(
        self, app, client, probe_routes
    ):
        # A bearer token that isn't in the DB must ALSO get 401 from
        # session_only, not fall through to @require_auth's 302
        # redirect. Integrators need a consistent "bearer not
        # accepted here" signal regardless of whether the specific
        # token happens to be valid.
        resp = client.get(
            "/_probe/session_only",
            headers={
                "Authorization": "Bearer tb_pat_" + "x" * 43,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        assert resp.get_json()["error"] == "Session required"


# ---------------------------------------------------------------------------
# _openapi_security markers
# ---------------------------------------------------------------------------


class TestOpenapiSecurityMarkers:
    def test_require_auth_declares_both(self):
        from services.auth.decorators import require_auth

        @require_auth
        def _f():
            pass

        assert _f._openapi_security == [
            {"sessionAuth": []},
            {"bearerAuth": []},
        ]

    def test_require_permission_declares_both(self):
        @require_permission("streams", "read")
        def _f():
            pass

        assert _f._openapi_security == [
            {"sessionAuth": []},
            {"bearerAuth": []},
        ]

    def test_session_only_declares_session_only(self):
        @session_only
        def _f():
            pass

        assert _f._openapi_security == [{"sessionAuth": []}]
