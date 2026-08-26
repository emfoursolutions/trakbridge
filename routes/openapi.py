# ABOUTME: Serves the generated OpenAPI 3.1 spec and Swagger UI page.
# ABOUTME: Cached per-app so spec generation only runs once at boot.
"""
File: routes/openapi.py

Description:
    Publishes the machine-readable OpenAPI 3.1 specification at
    /api/openapi.json and an interactive Swagger UI at /api/docs.

    Both endpoints require authentication (session cookie or
    tb_pat_ bearer token). Every legitimate consumer is already
    authenticated for some other reason:

    - Browser users are logged into the UI.
    - Scripted integrators hold an API key from /auth/api-keys.

    Auth-gating removes TrakBridge from anonymous-scanner
    reconnaissance without penalising any real caller. It also
    keeps the docs consistent with the rest of the admin surface
    (`/admin/*`, `/auth/api-keys/*`) which is not publicly
    browsable either.

    The spec is generated once per app instance and cached in
    ``current_app.extensions`` — regenerating it on every request
    would walk the URL map and re-parse every YAML docstring,
    which is unnecessary for a spec that only changes with a
    code deploy.

Author: Emfour Solutions
Created: 2026-08-17
"""

from flask import Blueprint, current_app, jsonify, render_template

from services.auth import require_auth
from services.logging_service import get_module_logger
from services.openapi_service import build_spec_dict

logger = get_module_logger(__name__)

bp = Blueprint("openapi", __name__)

_CACHE_KEY = "trakbridge_openapi_spec"


def _get_cached_spec():
    ext = current_app.extensions
    spec = ext.get(_CACHE_KEY)
    if spec is None:
        spec = build_spec_dict(current_app)
        ext[_CACHE_KEY] = spec
    return spec


@bp.route("/openapi.json")
@require_auth
def spec_json():
    """Return the OpenAPI 3.1 spec as JSON."""
    return jsonify(_get_cached_spec())


@bp.route("/docs")
@require_auth
def swagger_ui():
    """Render the Swagger UI page."""
    return render_template("openapi/swagger_ui.html")
