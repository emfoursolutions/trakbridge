# ABOUTME: Validates the generated OpenAPI spec against the 3.1 schema.
# ABOUTME: Also asserts core spec shape (openapi version, info, paths).
"""Verify the OpenAPI spec is well-formed and conforms to 3.1."""

from openapi_spec_validator import validate

from services.openapi_service import build_spec_dict


def test_spec_is_valid_openapi_31(app):
    with app.app_context():
        spec = build_spec_dict(app)
    validate(spec)
    assert spec["openapi"].startswith("3.1"), spec["openapi"]


def test_spec_has_expected_top_level_shape(app):
    with app.app_context():
        spec = build_spec_dict(app)
    assert "info" in spec
    assert spec["info"]["title"] == "TrakBridge API"
    assert "paths" in spec
    assert "components" in spec
    schemes = spec["components"]["securitySchemes"]
    assert set(schemes.keys()) == {
        "sessionAuth",
        "csrfToken",
        "bearerAuth",
        "apiKeyAuth",
    }
