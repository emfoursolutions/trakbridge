# ABOUTME: Guards that every admin/credential route is @session_only decorated.
# ABOUTME: Walks the URL map so new admin routes fail CI if not opted in.
"""Coverage tests for the @session_only decorator across the app.

Two guarantees this suite enforces:

1. Every route in the "session-required" set (admin, plugin admin,
   cot_types, credential mutation, logout) refuses API-key bearer
   auth with 401. This is the runtime check.

2. Every route whose URL falls under a session-only prefix is
   decorated with @session_only. This is the static structural
   check — walks Flask's URL map so a newly-added
   /admin/<foo> route lands a CI failure if the author forgets
   the decorator.
"""

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
def admin_user(app, db_session):
    """An admin so bearer requests reach the session_only check
    (rather than short-circuiting on missing role)."""
    user = User(
        username="admin_session_only",
        email="admin_session_only@example.com",
        auth_provider=AuthProvider.LOCAL,
        role=UserRole.ADMIN,
        status=AccountStatus.ACTIVE,
    )
    user.set_password("Correct-Horse-Battery-9!")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_bearer(admin_user):
    """An API key belonging to an admin with a broad scope.

    Any endpoint that refuses this bearer is proving @session_only is
    on — an admin's full-scope key is the strongest test.
    """
    _key, plaintext = UserApiKey.generate(
        user=admin_user,
        name="admin session-only test key",
        scopes=[
            "streams:read",
            "streams:write",
            "streams:delete",
            "tak_servers:read",
            "tak_servers:write",
            "api:read",
            "api:write",
            "api_keys:read",
            "api_keys:write",
            "api_keys:delete",
        ],
    )
    return plaintext


# ---------------------------------------------------------------------------
# Static structural check — walk the URL map
# ---------------------------------------------------------------------------


# URL prefixes that MUST have @session_only on every route that
# matches. Order matters only for the "which prefix owns this route"
# reporting in test failures — for enforcement it's just membership.
SESSION_ONLY_PREFIXES = (
    "/admin/",           # routes/admin.py, plugin_admin.py, cot_types.py
    "/auth/admin/",      # user management under auth blueprint
    "/auth/change-password",
    "/auth/force-password-change",
    "/auth/profile/edit",
    "/auth/logout",
    "/auth/api/logout",
)


# Endpoints that fall under a session-only URL prefix but are
# legitimately open to bearer auth. Each entry MUST have a comment
# justifying the exemption — the URL prefix is a heuristic, not a
# security boundary, and exceptions require conscious sign-off.
SESSION_ONLY_EXEMPT_ENDPOINTS = frozenset({
    # CoT type enumeration is static reference data (built-in CoT
    # affiliation/category listing). Lives under /admin only because
    # that's where the browser nav places it. No state mutation, no
    # PII, no credentials — external integrators want to query it
    # for the same reasons they query /api/plugins/categories.
    "cot_types.list_cot_types",
    "cot_types.get_cot_export_data",
})


def _has_session_only_marker(view_func) -> bool:
    """Walk the wrapper chain and check for the session_only marker."""
    fn = view_func
    seen = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        # session_only sets _openapi_security = [{"sessionAuth": []}]
        # (bearerAuth deliberately omitted). This is our marker.
        marker = getattr(fn, "_openapi_security", None)
        if marker == [{"sessionAuth": []}]:
            return True
        fn = getattr(fn, "__wrapped__", None)
    return False


def _iter_session_only_rules(app):
    """Yield rules whose URL should be @session_only."""
    for rule in app.url_map.iter_rules():
        if any(rule.rule.startswith(p) for p in SESSION_ONLY_PREFIXES):
            yield rule


def test_all_session_only_routes_are_decorated(app):
    """Every /admin/*, credential, and logout endpoint carries @session_only.

    This is the guardrail that catches newly-added admin routes
    where the author forgot the decorator.
    """
    undecorated = []
    for rule in _iter_session_only_rules(app):
        if rule.endpoint in SESSION_ONLY_EXEMPT_ENDPOINTS:
            continue
        view = app.view_functions.get(rule.endpoint)
        if view is None:
            continue
        if not _has_session_only_marker(view):
            undecorated.append(f"{rule.endpoint}  {rule.rule}")
    assert not undecorated, (
        "The following routes match a session-only URL prefix but "
        "are missing @session_only. Add the decorator ABOVE "
        "@require_auth / @require_permission / @admin_required.\n\n"
        + "\n".join(undecorated)
    )


# ---------------------------------------------------------------------------
# Runtime check — hit a sample of the endpoints with bearer auth
# ---------------------------------------------------------------------------


# Representative endpoints from each session-only surface. We hit
# every URL in the structural check indirectly via the marker walk;
# these HTTP checks prove the marker actually causes a 401 at runtime.
RUNTIME_PROBE_ENDPOINTS = (
    ("GET", "/admin/system_info"),
    ("GET", "/admin/plugins/"),
    ("GET", "/auth/change-password"),
    ("GET", "/auth/profile/edit"),
    ("GET", "/auth/logout"),
    ("GET", "/auth/admin/users"),
)


@pytest.mark.parametrize("method,url", RUNTIME_PROBE_ENDPOINTS)
def test_bearer_rejected_at_runtime(app, client, admin_bearer, method, url):
    """Even an admin-owned full-scope key is refused at these URLs."""
    resp = client.open(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {admin_bearer}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 401, (
        f"{method} {url} should refuse bearer auth even with a "
        f"full-scope admin key, got {resp.status_code}. Missing "
        f"@session_only decorator?"
    )
