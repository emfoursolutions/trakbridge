# ABOUTME: Builds the TrakBridge OpenAPI 3.1 spec from the Flask route table.
# ABOUTME: Filters to an in-scope allowlist; derives security from decorators.
"""
File: services/openapi_service.py

Description:
    Generates the OpenAPI 3.1 specification for TrakBridge's public JSON
    API. Uses apispec's FlaskPlugin to read YAML from view function
    docstrings and MarshmallowPlugin to resolve schema references. Only
    endpoints in IN_SCOPE_PATHS are included in the spec; every other
    Flask route (admin, auth, HTML) is filtered out. Per-operation
    ``security`` is derived from the ``_openapi_security`` marker set by
    decorators in ``services/auth/decorators.py`` when the docstring
    does not declare its own ``security`` block.

Author: Emfour Solutions
Created: 2026-08-17
"""

from __future__ import annotations

import re
import warnings
from typing import Any, Dict, Iterable, Set, Tuple

from apispec import APISpec
from apispec import yaml_utils
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask import Flask

from schemas import ALL_SCHEMAS
from services.version import get_version

# Every path in this set must have a documented operation. Coverage
# tests assert equality between this set and the paths present in the
# generated spec, so it is the single source of truth for scope.
#
# Paths use OpenAPI-style `{name}` placeholders. Flask's `<int:name>`
# and `<name>` converters are normalised to `{name}` before comparison.
IN_SCOPE_PATHS: Set[Tuple[str, str]] = {
    # Phase A — health, status, version
    ("GET", "/api/status"),
    ("GET", "/api/health"),
    ("GET", "/api/health/detailed"),
    ("GET", "/api/health/ready"),
    ("GET", "/api/health/live"),
    ("GET", "/api/health/database"),
    ("GET", "/api/health/plugins"),
    ("GET", "/api/health/configuration"),
    ("GET", "/api/version"),
    # Phase B — streams
    ("GET", "/api/streams/stats"),
    ("GET", "/api/streams/status"),
    ("GET", "/api/streams/{stream_id}/config"),
    ("GET", "/api/streams/{stream_id}/export-config"),
    ("GET", "/api/streams/{stream_id}/callsign-mappings"),
    ("POST", "/api/streams/discover-trackers"),
    # Phase B — plugins
    ("GET", "/api/plugins/metadata"),
    ("GET", "/api/plugins/categories"),
    ("GET", "/api/plugins/by-category/{category}"),
    ("GET", "/api/plugins/categorized"),
    ("GET", "/api/plugins/category-statistics"),
    ("GET", "/api/plugins/{plugin_type}/available-fields"),
}


_FLASK_CONVERTER_RE = re.compile(r"<(?:[a-zA-Z_][a-zA-Z0-9_]*:)?([^>]+)>")


def _flask_path_to_openapi(rule: str) -> str:
    """Convert a Flask URL rule to an OpenAPI path template."""
    return _FLASK_CONVERTER_RE.sub(r"{\1}", rule)


def _derive_security(view_func) -> Any:
    """Return the security requirement list marked on the view.

    Walks the ``__wrapped__`` chain in case there are stacked
    decorators, returning the first ``_openapi_security`` marker
    found. Returns ``None`` if no marker exists.
    """
    fn = view_func
    seen: Set[int] = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        if hasattr(fn, "_openapi_security"):
            return fn._openapi_security
        fn = getattr(fn, "__wrapped__", None)
    return None


def _methods_for(app: Flask, view_func) -> Set[str]:
    """Return the lowercase HTTP methods handled by a view function."""
    methods: Set[str] = set()
    for rule in app.url_map.iter_rules():
        if app.view_functions.get(rule.endpoint) is view_func:
            for method in rule.methods or ():
                if method not in {"HEAD", "OPTIONS"}:
                    methods.add(method.lower())
    return methods


def _operations_for(view_func, methods: Set[str]) -> Dict[str, Any]:
    """Parse the view's docstring and map it onto its methods.

    Docstrings use a single method-agnostic YAML block after ``---``.
    That block is applied to every HTTP method the route serves,
    which is the common case for our endpoints (one route = one
    method, or a GET/DELETE pair that shares the same contract).
    """
    doc = view_func.__doc__ or ""
    parsed = yaml_utils.load_yaml_from_docstring(doc)
    if not parsed:
        return {}
    return {method: dict(parsed) for method in methods}


def _iter_in_scope_rules(app: Flask) -> Iterable[Tuple[str, str, Any]]:
    """Yield (method, openapi_path, view_func) for in-scope routes."""
    for rule in app.url_map.iter_rules():
        view_func = app.view_functions.get(rule.endpoint)
        if view_func is None:
            continue
        openapi_path = _flask_path_to_openapi(rule.rule)
        for method in rule.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            if (method, openapi_path) in IN_SCOPE_PATHS:
                yield method, openapi_path, view_func


def _schema_name(schema_cls) -> str:
    """Match MarshmallowPlugin's default resolver (strips 'Schema')."""
    name = schema_cls.__name__
    if name.endswith("Schema"):
        name = name[:-6] or name
    return name


def _register_schemas(spec: APISpec) -> None:
    """Pre-register top-level schemas under their resolved names.

    MarshmallowPlugin's default resolver strips the ``Schema``
    suffix from class names when auto-registering via Nested()
    references. We must use the same naming here — otherwise a
    schema registered manually as ``ComponentHealthSchema`` will
    collide with the plugin's later ``ComponentHealth`` entry.

    The warning suppression covers the benign "added twice" case
    when a nested schema is later re-registered while resolving
    a parent schema during ``spec.path``.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r".*has already been added to the spec.*",
            category=UserWarning,
        )
        for schema_cls in ALL_SCHEMAS:
            name = _schema_name(schema_cls)
            if name in spec.components.schemas:
                continue
            spec.components.schema(name, schema=schema_cls)


def _register_security_schemes(spec: APISpec) -> None:
    spec.components.security_scheme(
        "sessionAuth",
        {
            "type": "apiKey",
            "in": "cookie",
            "name": "session",
            "description": (
                "Server-side session cookie set on login via "
                "/auth/login. State-changing requests must also send "
                "the CSRF token in the X-CSRFToken header (see "
                "csrfToken scheme). Session cookies use HttpOnly and "
                "SameSite=Lax."
            ),
        },
    )
    spec.components.security_scheme(
        "csrfToken",
        {
            "type": "apiKey",
            "in": "header",
            "name": "X-CSRFToken",
            "description": (
                "CSRF token from the <meta name='csrf-token'> element "
                "rendered on every HTML page. Required alongside "
                "sessionAuth for POST/PUT/PATCH/DELETE requests."
            ),
        },
    )
    spec.components.security_scheme(
        "bearerAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque",
            "description": (
                "Opaque bearer token validated by the target stream's "
                "inbound plugin. Used exclusively by /api/inbound."
            ),
        },
    )
    spec.components.security_scheme(
        "apiKeyAuth",
        {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Long-lived API key (planned). Declared where the "
                "api_key_or_auth_required decorator is used, but "
                "server-side validation is not yet implemented."
            ),
        },
    )


def _build_info() -> Dict[str, Any]:
    return {
        "title": "TrakBridge API",
        "version": get_version(),
        "description": (
            "OpenAPI 3.1 specification for the public TrakBridge JSON "
            "API. Covers health/monitoring, streams, plugins, inbound "
            "stream ingestion, and coordinate conversion utilities. "
            "Admin, auth, and HTML routes are intentionally out of "
            "scope. See docs/API_REFERENCE.md for prose docs."
        ),
        "contact": {
            "name": "TrakBridge Project",
            "url": "https://github.com/emfoursolutions/trakbridge",
        },
        "license": {"name": "Apache-2.0"},
    }


def build_spec_dict(app: Flask) -> Dict[str, Any]:
    """Build and return the OpenAPI spec as a plain dict.

    This is what /api/openapi.json serves. The result is not cached
    here; call sites should cache on ``app.extensions`` if needed.
    """
    spec = APISpec(
        title="TrakBridge API",
        version=get_version(),
        openapi_version="3.1.0",
        info=_build_info(),
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
    )

    _register_security_schemes(spec)

    _register_schemas(spec)

    # Group in-scope rules by view function so a route serving
    # multiple HTTP methods (e.g. GET and DELETE) is added once with
    # both operations. Our convention: docstrings use a single YAML
    # block with method-agnostic keys (tags, security, responses),
    # and it is applied to every method the route accepts.
    seen_views: Set[int] = set()
    with app.test_request_context():
        for method, _, view_func in _iter_in_scope_rules(app):
            key = id(view_func)
            if key in seen_views:
                continue
            seen_views.add(key)
            operations = _operations_for(view_func, methods=_methods_for(
                app, view_func
            ))
            spec.path(view=view_func, app=app, operations=operations)

    spec_dict = spec.to_dict()
    _inject_derived_security(spec_dict, app)
    return spec_dict


def _inject_derived_security(
    spec_dict: Dict[str, Any], app: Flask
) -> None:
    """Fill in ``security`` from decorator markers where absent."""
    paths = spec_dict.setdefault("paths", {})
    for method, openapi_path, view_func in _iter_in_scope_rules(app):
        operations = paths.get(openapi_path)
        if not operations:
            continue
        op = operations.get(method.lower())
        if not op or "security" in op:
            continue
        derived = _derive_security(view_func)
        if derived is not None:
            op["security"] = derived
