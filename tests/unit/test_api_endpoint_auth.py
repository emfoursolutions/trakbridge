"""
ABOUTME: Test authentication requirements for protected API endpoints
ABOUTME: Validates that endpoints requiring auth reject unauthenticated requests with 401
"""

import pytest


class TestEndpointAuthRequirements:
    """Test that endpoints properly enforce authentication requirements."""

    # Endpoints that should require authentication
    PROTECTED_ENDPOINTS = [
        ("/api/health/detailed", "GET"),
        ("/api/health/database", "GET"),
        ("/api/health/configuration", "GET"),
        ("/api/health/circuit-breakers", "GET"),
        ("/api/health/recovery", "GET"),
        ("/api/monitoring/dashboard", "GET"),
        ("/api/convert-latlon-to-mgrs", "POST"),
        ("/api/convert-mgrs-to-latlon", "POST"),
    ]

    # Endpoint that should remain accessible without auth (minimal probe)
    PUBLIC_ENDPOINT = "/api/status"

    @pytest.mark.parametrize("endpoint,method", PROTECTED_ENDPOINTS)
    def test_protected_endpoints_reject_unauthenticated(self, client, endpoint, method):
        """Test that protected endpoints return 401 for unauthenticated requests."""
        if method == "GET":
            response = client.get(endpoint)
        elif method == "POST":
            response = client.post(endpoint, json={})

        assert response.status_code == 401, (
            f"{endpoint} should return 401 for unauthenticated request, got {response.status_code}"
        )

    def test_status_endpoint_allows_unauthenticated(self, client):
        """Test that /api/status remains accessible without authentication."""
        response = client.get(self.PUBLIC_ENDPOINT)
        assert response.status_code == 200, (
            f"{self.PUBLIC_ENDPOINT} should return 200 for unauthenticated request, got {response.status_code}"
        )

    def test_protected_endpoint_with_auth(self, authenticated_client, app):
        """Test that protected endpoint is accessible with authentication."""
        client = authenticated_client("admin")
        response = client.get("/api/health/detailed")

        assert response.status_code == 200, (
            f"/api/health/detailed should return 200 for authenticated request, got {response.status_code}"
        )
        # Verify response has expected structure
        data = response.get_json()
        assert data is not None
        assert isinstance(data, dict)

    def test_mgrs_conversion_latlon_protected(self, client, authenticated_client, app):
        """Test that /api/convert-latlon-to-mgrs requires authentication."""
        # Unauthenticated should be 401
        response = client.post("/api/convert-latlon-to-mgrs", json={"latitude": 0, "longitude": 0})
        assert response.status_code == 401

        # Authenticated should work (or at least not return 401)
        auth_client = authenticated_client("admin")
        response = auth_client.post("/api/convert-latlon-to-mgrs", json={"latitude": 0, "longitude": 0})
        assert response.status_code != 401

    def test_mgrs_conversion_mgrslat_protected(self, client, authenticated_client, app):
        """Test that /api/convert-mgrs-to-latlon requires authentication."""
        # Unauthenticated should be 401
        response = client.post("/api/convert-mgrs-to-latlon", json={"mgrs": "31UEQ0000000000"})
        assert response.status_code == 401

        # Authenticated should work (or at least not return 401)
        auth_client = authenticated_client("admin")
        response = auth_client.post("/api/convert-mgrs-to-latlon", json={"mgrs": "31UEQ0000000000"})
        assert response.status_code != 401
