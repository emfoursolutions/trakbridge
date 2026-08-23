# ABOUTME: Smoke tests for /api/openapi.json and /api/docs endpoints.
# ABOUTME: Confirms both work without authentication and return sensible bodies.
"""End-to-end HTTP checks for the documentation endpoints."""

import json


def test_openapi_json_returns_valid_spec(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    payload = json.loads(response.data)
    assert payload["openapi"].startswith("3.1")
    assert "/api/health" in payload["paths"]


def test_docs_page_renders_swagger_ui(client):
    response = client.get("/api/docs")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "SwaggerUIBundle" in body
    assert "/api/openapi.json" in body


def test_docs_endpoints_do_not_require_auth(client):
    # No session cookie sent; both should succeed.
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200
