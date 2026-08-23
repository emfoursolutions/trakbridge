# ABOUTME: Verifies security requirements are correctly derived per endpoint.
# ABOUTME: Public endpoints get []; require_auth-decorated get sessionAuth.
"""Per-endpoint security requirement derivation."""

from services.openapi_service import build_spec_dict


def test_health_endpoints_are_public(app):
    with app.app_context():
        spec = build_spec_dict(app)
    # /health, /health/ready, /health/live are documented as public
    # via ``security: []`` in their docstrings.
    for path in ("/api/health", "/api/health/ready", "/api/health/live"):
        op = spec["paths"][path]["get"]
        assert op.get("security") == [], (path, op.get("security"))


def test_authenticated_health_endpoints_use_session_auth(app):
    with app.app_context():
        spec = build_spec_dict(app)
    # These endpoints are decorated with @require_auth or
    # @require_permission and should inherit sessionAuth.
    for path in (
        "/api/health/detailed",
        "/api/health/database",
        "/api/health/configuration",
        "/api/health/plugins",
    ):
        op = spec["paths"][path]["get"]
        assert {"sessionAuth": []} in (op.get("security") or []), (
            path,
            op.get("security"),
        )


def test_status_endpoint_is_public(app):
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/status"]["get"]
    assert op.get("security") == []


def test_version_endpoint_is_public(app):
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/version"]["get"]
    assert op.get("security") == []
