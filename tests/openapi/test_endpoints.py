# ABOUTME: HTTP tests for /api/openapi.json and /api/docs.
# ABOUTME: Verifies auth-gated access — both session and bearer paths.
"""End-to-end HTTP checks for the documentation endpoints.

Both endpoints require authentication as of the docs auth-gate.
Session cookies (browser UI) and tb_pat_ bearer tokens (scripted
integrations) both work.
"""

import json

import pytest

from models.user import (
    AccountStatus,
    AuthProvider,
    User,
    UserApiKey,
    UserRole,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def local_user(app, db_session):
    user = User(
        username="docs_auth_user",
        email="docs_auth_user@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.USER,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def logged_in_client(app, client, local_user):
    """Populate the test client with a valid session cookie."""
    from services.auth.auth_manager import AuthenticationManager

    auth_manager: AuthenticationManager = app.auth_manager
    session = auth_manager.create_session(local_user)
    with client.session_transaction() as sess:
        sess["session_id"] = session.session_id
        sess["user_id"] = local_user.id
    return client


@pytest.fixture
def bearer_token(local_user):
    _key, plaintext = UserApiKey.generate(
        user=local_user,
        name="docs test key",
        scopes=["api:read"],
    )
    return plaintext


# ---------------------------------------------------------------------------
# Anonymous access — must be denied
# ---------------------------------------------------------------------------


def test_docs_endpoints_require_auth(client):
    """No session, no bearer → both endpoints refuse the request.

    Either 302 (browser redirect to login) or 401 (JSON) is
    acceptable — but not 200. This is the primary regression
    guard against accidentally opening the docs back up.
    """
    for path in ("/api/openapi.json", "/api/docs"):
        resp = client.get(path)
        assert resp.status_code in (302, 401), (
            f"{path} returned {resp.status_code}; expected 302 or "
            f"401. Missing @require_auth?"
        )


# ---------------------------------------------------------------------------
# Session cookie path
# ---------------------------------------------------------------------------


def test_openapi_json_via_session(logged_in_client):
    response = logged_in_client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    payload = json.loads(response.data)
    assert payload["openapi"].startswith("3.1")
    assert "/api/health" in payload["paths"]


def test_docs_page_via_session(logged_in_client):
    response = logged_in_client.get("/api/docs")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "SwaggerUIBundle" in body
    assert "/api/openapi.json" in body


# ---------------------------------------------------------------------------
# Bearer token path (scripted integrations)
# ---------------------------------------------------------------------------


def test_openapi_json_via_bearer(client, bearer_token):
    """Scripted tooling can grab the spec with a tb_pat_ token."""
    response = client.get(
        "/api/openapi.json",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200
    payload = json.loads(response.data)
    assert payload["openapi"].startswith("3.1")


def test_docs_page_via_bearer(client, bearer_token):
    """A bearer holder can also render the Swagger UI page (though
    the UI then relies on the browser session for its own fetch of
    /api/openapi.json — so real usage is browser-with-session)."""
    response = client.get(
        "/api/docs",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200
