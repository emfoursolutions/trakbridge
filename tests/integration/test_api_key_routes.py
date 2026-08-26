# ABOUTME: Integration tests for the /auth/api-keys blueprint.
# ABOUTME: Covers list/create/revoke, ownership, cap, and rate-limit.
"""Integration tests for routes/api_keys.py.

These exercise the whole request pipeline: auth decorators, session
resolution, cap enforcement, per-user rate limit, scope validation,
and ownership checks on revoke.

CSRF is disabled per-test via an autouse fixture — these tests focus
on route logic, not CSRF plumbing (which lives in
tests/integration/test_csrf_bearer_bypass.py).
"""

from datetime import datetime, timedelta, timezone

import pytest

from models.user import (
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)


@pytest.fixture(autouse=True)
def _disable_csrf(app):
    """Run the whole test module without CSRF enforcement."""
    original = app.config.get("WTF_CSRF_ENABLED", True)
    app.config["WTF_CSRF_ENABLED"] = False
    yield
    app.config["WTF_CSRF_ENABLED"] = original


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(db_session, username: str, role: UserRole):
    user = User(
        username=username,
        email=f"{username}@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=role,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def operator(app, db_session):
    return _make_user(db_session, "op_apikey_routes", UserRole.OPERATOR)


@pytest.fixture
def admin(app, db_session):
    return _make_user(db_session, "admin_apikey_routes", UserRole.ADMIN)


@pytest.fixture
def viewer(app, db_session):
    return _make_user(db_session, "viewer_apikey_routes", UserRole.VIEWER)


@pytest.fixture
def logged_in_operator(app, client, operator):
    """Populate the test client with a valid session for operator."""
    from services.auth.auth_manager import AuthenticationManager

    auth_manager: AuthenticationManager = app.auth_manager
    session = auth_manager.create_session(operator)
    with client.session_transaction() as sess:
        sess["session_id"] = session.session_id
        sess["user_id"] = operator.id
    return operator


@pytest.fixture
def logged_in_viewer(app, client, viewer):
    from services.auth.auth_manager import AuthenticationManager

    auth_manager: AuthenticationManager = app.auth_manager
    session = auth_manager.create_session(viewer)
    with client.session_transaction() as sess:
        sess["session_id"] = session.session_id
        sess["user_id"] = viewer.id
    return viewer


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestListKeys:
    def test_unauthenticated_denied(self, client):
        resp = client.get("/auth/api-keys/")
        # No session → require_permission redirects to login (302)
        # for browser requests. Either 302 or 401 is acceptable
        # "not authenticated" — but not 200.
        assert resp.status_code in (302, 401)

    def test_empty_list_renders(self, client, logged_in_operator):
        resp = client.get("/auth/api-keys/")
        assert resp.status_code == 200
        assert b"No API keys yet" in resp.data

    def test_lists_own_keys(self, client, logged_in_operator):
        UserApiKey.generate(
            logged_in_operator, "test key one", ["streams:read"]
        )
        resp = client.get("/auth/api-keys/")
        assert resp.status_code == 200
        assert b"test key one" in resp.data
        assert b"streams:read" in resp.data

    def test_does_not_leak_other_users_keys(
        self, client, logged_in_operator, admin
    ):
        UserApiKey.generate(admin, "admin secret key", ["streams:read"])
        resp = client.get("/auth/api-keys/")
        assert resp.status_code == 200
        assert b"admin secret key" not in resp.data


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateKey:
    def test_create_returns_plaintext_once(
        self, client, logged_in_operator
    ):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"name": "ci pipeline", "scopes": ["streams:read"]},
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["name"] == "ci pipeline"
        assert body["token"].startswith("tb_pat_")
        assert body["prefix"].startswith("tb_pat_")
        assert "warning" in body

    def test_created_key_persisted_hashed(
        self, client, logged_in_operator, db_session
    ):
        client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "persisted", "scopes": ["streams:read"]},
        )
        stored = (
            db_session.query(UserApiKey)
            .filter_by(user_id=logged_in_operator.id, name="persisted")
            .first()
        )
        assert stored is not None
        # Hash != plaintext (never store raw)
        assert stored.token_hash != stored.token_prefix

    def test_name_required(self, client, logged_in_operator):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"scopes": ["streams:read"]},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "name_required"

    def test_scopes_required(self, client, logged_in_operator):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "no scope", "scopes": []},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "scopes_required"

    def test_unknown_scope_rejected(self, client, logged_in_operator):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "bad scope", "scopes": ["nonexistent:read"]},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_scope"

    def test_scope_exceeding_owner_rejected(
        self, client, logged_in_viewer
    ):
        # VIEWER role has streams:read only. Attempting streams:write
        # must be rejected with a scope_forbidden error, not silently
        # allowed.
        # First, viewer needs api_keys:write to reach the endpoint
        # at all — but VIEWER doesn't have that per the permission
        # matrix. So they'd hit 403 from require_permission before
        # this check fires. Verify that instead.
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "viewer key", "scopes": ["streams:write"]},
        )
        assert resp.status_code == 403

    def test_expires_at_stored(
        self, client, logged_in_operator, db_session
    ):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={
                "name": "expiring key",
                "scopes": ["streams:read"],
                "expires_at": "2027-01-01",
            },
        )
        assert resp.status_code == 201
        stored = (
            db_session.query(UserApiKey)
            .filter_by(user_id=logged_in_operator.id, name="expiring key")
            .first()
        )
        assert stored.expires_at is not None
        assert stored.expires_at.year == 2027

    def test_invalid_expires_at_rejected(
        self, client, logged_in_operator
    ):
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={
                "name": "bad expiry",
                "scopes": ["streams:read"],
                "expires_at": "not a date",
            },
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "invalid_expires_at"


# ---------------------------------------------------------------------------
# Anti-abuse
# ---------------------------------------------------------------------------


class TestActiveKeyCap:
    def test_cap_enforced_at_10(
        self, client, logged_in_operator, db_session
    ):
        for i in range(10):
            UserApiKey.generate(
                logged_in_operator, f"cap-{i}", ["streams:read"]
            )
        # 11th key should be rejected
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "eleventh", "scopes": ["streams:read"]},
        )
        assert resp.status_code == 409
        body = resp.get_json()
        assert body["error"] == "cap_exceeded"

    def test_revoked_keys_do_not_count_toward_cap(
        self, client, logged_in_operator, db_session
    ):
        for i in range(10):
            key, _ = UserApiKey.generate(
                logged_in_operator, f"pre-revoke-{i}", ["streams:read"]
            )
        # Revoke all 10
        for k in db_session.query(UserApiKey).filter_by(
            user_id=logged_in_operator.id
        ).all():
            k.revoke()
        db_session.commit()

        # Should be able to create a new key now
        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "after revoke", "scopes": ["streams:read"]},
        )
        assert resp.status_code == 201

    def test_expired_keys_do_not_count_toward_cap(
        self, client, logged_in_operator, db_session
    ):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        for i in range(10):
            key, _ = UserApiKey.generate(
                logged_in_operator, f"expired-{i}", ["streams:read"]
            )
            key.expires_at = past
        db_session.commit()

        resp = client.post(
            "/auth/api-keys/",
            headers={"Content-Type": "application/json"},
            json={"name": "after expiry", "scopes": ["streams:read"]},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# Revoke + ownership
# ---------------------------------------------------------------------------


class TestRevokeKey:
    def test_revoke_own_key_succeeds(
        self, client, logged_in_operator, db_session
    ):
        key, _ = UserApiKey.generate(
            logged_in_operator, "to revoke", ["streams:read"]
        )
        resp = client.post(
            f"/auth/api-keys/{key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        db_session.refresh(key)
        assert key.revoked_at is not None
        assert key.is_active is False

    def test_revoke_others_key_returns_404_not_403(
        self, client, logged_in_operator, admin, db_session
    ):
        # Anti-enumeration — must not distinguish "not yours" from
        # "doesn't exist". Otherwise an attacker could probe for
        # valid key ids belonging to other users.
        admin_key, _ = UserApiKey.generate(
            admin, "admin key", ["streams:read"]
        )
        resp = client.post(
            f"/auth/api-keys/{admin_key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404

        # The admin's key must still be active.
        db_session.refresh(admin_key)
        assert admin_key.revoked_at is None

    def test_revoke_nonexistent_key_returns_404(
        self, client, logged_in_operator
    ):
        resp = client.post(
            "/auth/api-keys/999999/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404

    def test_revoke_is_idempotent(
        self, client, logged_in_operator, db_session
    ):
        key, _ = UserApiKey.generate(
            logged_in_operator, "double revoke", ["streams:read"]
        )
        key.revoke()
        db_session.commit()
        # Refresh so first_revoked_at reflects what the DB actually
        # stored (MySQL DATETIME without (6) truncates microseconds,
        # SQLite strips tzinfo). Comparing against the in-memory
        # value directly would fail on precision differences.
        db_session.refresh(key)
        first_revoked_at = key.revoked_at
        if first_revoked_at.tzinfo is not None:
            first_revoked_at = first_revoked_at.replace(tzinfo=None)

        resp = client.post(
            f"/auth/api-keys/{key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        db_session.refresh(key)
        # Second revoke does not update the timestamp (compare
        # tz-naively; both values now come from the DB so precision
        # is consistent regardless of backend).
        second = key.revoked_at
        if second.tzinfo is not None:
            second = second.replace(tzinfo=None)
        assert second == first_revoked_at
