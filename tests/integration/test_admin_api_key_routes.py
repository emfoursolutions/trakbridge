# ABOUTME: Integration tests for the /admin/api-keys blueprint.
# ABOUTME: Cross-user list, admin-any-key revoke, non-admin refused.
"""Integration tests for routes/admin_api_keys.py.

Verifies that only admins can reach the cross-user page, that they
see keys belonging to any user, that they can revoke any key, and
that admin-cross-user revocation emits the WARNING-level audit line.
"""

import logging

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
    original = app.config.get("WTF_CSRF_ENABLED", True)
    app.config["WTF_CSRF_ENABLED"] = False
    yield
    app.config["WTF_CSRF_ENABLED"] = original


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


def _login(app, client, user):
    from services.auth.auth_manager import AuthenticationManager

    auth_manager: AuthenticationManager = app.auth_manager
    session = auth_manager.create_session(user)
    with client.session_transaction() as sess:
        sess["session_id"] = session.session_id
        sess["user_id"] = user.id


@pytest.fixture
def admin(app, db_session):
    return _make_user(db_session, "admin_cross_user", UserRole.ADMIN)


@pytest.fixture
def operator(app, db_session):
    return _make_user(db_session, "op_cross_user", UserRole.OPERATOR)


@pytest.fixture
def viewer(app, db_session):
    return _make_user(db_session, "viewer_cross_user", UserRole.VIEWER)


class TestListAllKeys:
    def test_unauthenticated_denied(self, client):
        resp = client.get("/admin/api-keys/")
        assert resp.status_code in (302, 401)

    def test_non_admin_denied(self, app, client, operator):
        _login(app, client, operator)
        resp = client.get("/admin/api-keys/")
        # admin_required denies with 403 for JSON or the "Permission
        # denied" HTML page.
        assert resp.status_code == 403

    def test_admin_sees_all_users_keys(
        self, app, client, admin, operator, viewer
    ):
        UserApiKey.generate(operator, "op key", ["streams:read"])
        UserApiKey.generate(viewer, "viewer key", ["streams:read"])
        UserApiKey.generate(admin, "admin key", ["streams:read"])

        _login(app, client, admin)
        resp = client.get("/admin/api-keys/")
        assert resp.status_code == 200
        assert b"op key" in resp.data
        assert b"viewer key" in resp.data
        assert b"admin key" in resp.data
        # Owner column shows every user
        assert b"op_cross_user" in resp.data
        assert b"viewer_cross_user" in resp.data
        assert b"admin_cross_user" in resp.data


class TestAdminRevoke:
    def test_admin_can_revoke_any_users_key(
        self, app, client, admin, operator, db_session
    ):
        key, _ = UserApiKey.generate(
            operator, "target key", ["streams:read"]
        )
        _login(app, client, admin)
        resp = client.post(
            f"/admin/api-keys/{key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        db_session.refresh(key)
        assert key.revoked_at is not None
        assert key.is_active is False

    def test_admin_revoke_logs_warning_audit(
        self, app, client, admin, operator, caplog
    ):
        key, _ = UserApiKey.generate(
            operator, "audit target", ["streams:read"]
        )
        _login(app, client, admin)
        with caplog.at_level(logging.WARNING):
            client.post(
                f"/admin/api-keys/{key.id}/revoke",
                headers={"Content-Type": "application/json"},
            )
        # The cross-user variant emits a WARNING line specifically
        # tagged with action=admin_cross_user so log-aggregation
        # rules can distinguish it from a self-revoke.
        assert any(
            "action=admin_cross_user" in rec.message
            and rec.levelno == logging.WARNING
            for rec in caplog.records
        )

    def test_admin_revoke_nonexistent_returns_404(
        self, app, client, admin
    ):
        _login(app, client, admin)
        resp = client.post(
            "/admin/api-keys/999999/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404

    def test_admin_revoke_of_already_revoked_is_idempotent(
        self, app, client, admin, operator, db_session
    ):
        key, _ = UserApiKey.generate(
            operator, "already revoked", ["streams:read"]
        )
        key.revoke()
        db_session.commit()

        _login(app, client, admin)
        resp = client.post(
            f"/admin/api-keys/{key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        # No error, still 200 — but no double-revoke happens.
        assert resp.status_code == 200

    def test_non_admin_cannot_revoke_others_key_via_admin_route(
        self, app, client, operator, viewer, db_session
    ):
        # An operator (non-admin) hitting the admin revoke endpoint
        # must be denied even for a key they own — the admin URL is
        # for admins, full stop.
        key, _ = UserApiKey.generate(
            operator, "own key via admin url", ["streams:read"]
        )
        _login(app, client, operator)
        resp = client.post(
            f"/admin/api-keys/{key.id}/revoke",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403
        db_session.refresh(key)
        assert key.revoked_at is None
