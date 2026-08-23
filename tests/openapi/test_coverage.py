# ABOUTME: Asserts every in-scope route has a documented operation.
# ABOUTME: Regressions here mean a route was added without a YAML docstring.
"""Coverage check: IN_SCOPE_PATHS must equal spec's documented paths."""

from services.openapi_service import IN_SCOPE_PATHS, build_spec_dict


def _documented_operations(spec):
    return {
        (method.upper(), path)
        for path, ops in spec.get("paths", {}).items()
        for method in ops
        if method in {"get", "post", "put", "delete", "patch"}
    }


def test_every_in_scope_route_is_documented(app):
    with app.app_context():
        spec = build_spec_dict(app)
    documented = _documented_operations(spec)
    missing = IN_SCOPE_PATHS - documented
    assert not missing, f"Undocumented in-scope routes: {sorted(missing)}"


def test_no_undeclared_paths_in_spec(app):
    with app.app_context():
        spec = build_spec_dict(app)
    documented = _documented_operations(spec)
    extra = documented - IN_SCOPE_PATHS
    assert not extra, f"Spec has routes not in IN_SCOPE_PATHS: {sorted(extra)}"
