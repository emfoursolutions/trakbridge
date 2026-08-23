# ABOUTME: Serves the generated OpenAPI 3.1 spec and Swagger UI page.
# ABOUTME: Cached per-app so spec generation only runs once at boot.
"""
File: routes/openapi.py

Description:
    Publishes the machine-readable OpenAPI 3.1 specification at
    /api/openapi.json and an interactive Swagger UI at /api/docs.
    Both endpoints are public (no authentication) so external
    integrators can inspect the API contract without credentials.

    The spec is generated once per app instance and cached in
    ``current_app.extensions`` — regenerating it on every request
    would walk the URL map and re-parse every YAML docstring, which is
    unnecessary for a spec that only changes with a code deploy.

Author: Emfour Solutions
Created: 2026-08-17
"""

from flask import Blueprint, current_app, jsonify, render_template

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
def spec_json():
    """Return the OpenAPI 3.1 spec as JSON."""
    return jsonify(_get_cached_spec())


@bp.route("/docs")
def swagger_ui():
    """Render the Swagger UI page."""
    return render_template("openapi/swagger_ui.html")
