# ABOUTME: Verifies security requirements are correctly derived per endpoint.
# ABOUTME: Public endpoints get []; require_auth-decorated get sessionAuth.
"""Per-endpoint security requirement derivation."""

from services.openapi_service import build_spec_dict


def test_bare_health_endpoint_is_public(app):
    """/api/health is the single canonical unauth container probe (T1.5)."""
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/health"]["get"]
    assert op.get("security") == [], op.get("security")


def test_readiness_and_liveness_endpoints_require_auth(app):
    """T1.5 — /health/ready and /health/live now require a token.

    Orchestrators/monitors already carry a service credential; the bare
    unauth probe is /api/health. Both should advertise sessionAuth OR
    bearerAuth in the OpenAPI spec, derived from
    @api_key_or_auth_required.
    """
    with app.app_context():
        spec = build_spec_dict(app)
    for path in ("/api/health/ready", "/api/health/live"):
        op = spec["paths"][path]["get"]
        security = op.get("security") or []
        assert {"sessionAuth": []} in security, (path, security)
        assert {"bearerAuth": []} in security, (path, security)


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


def test_status_endpoint_requires_auth(app):
    """T1.5 — /api/status now requires a token (was @optional_auth)."""
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/status"]["get"]
    security = op.get("security") or []
    assert {"sessionAuth": []} in security, security
    assert {"bearerAuth": []} in security, security


def test_version_endpoint_requires_auth(app):
    """T1.5 — /api/version now requires a token so the version is not a
    ready-made fingerprint for drive-by scans."""
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/version"]["get"]
    security = op.get("security") or []
    assert {"sessionAuth": []} in security, security
    assert {"bearerAuth": []} in security, security


def test_inbound_data_endpoint_uses_bearer_auth(app):
    with app.app_context():
        spec = build_spec_dict(app)
    op = spec["paths"]["/api/inbound/{stream_id}/data"]["post"]
    # bearerAuth is declared in the docstring, so it wins over any
    # derived value. Assert the declared value is present.
    assert {"bearerAuth": []} in (op.get("security") or []), op.get(
        "security"
    )


def test_inbound_preview_endpoints_require_auth(app):
    """T1.1 — preview endpoints are now @api_key_or_auth_required.

    They accept session cookie or tb_pat_ bearer; the earlier
    stream-identity-only gate was insufficient.
    """
    with app.app_context():
        spec = build_spec_dict(app)
    for method, path in (
        ("get", "/api/inbound/{stream_id}/preview"),
        ("delete", "/api/inbound/{stream_id}/preview"),
        ("post", "/api/inbound/{stream_id}/preview/remap"),
    ):
        op = spec["paths"][path][method]
        security = op.get("security") or []
        assert {"sessionAuth": []} in security, (method, path, security)
        assert {"bearerAuth": []} in security, (method, path, security)
