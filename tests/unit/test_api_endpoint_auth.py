"""
ABOUTME: Test authentication requirements for protected API endpoints
ABOUTME: Validates that endpoints requiring auth reject unauthenticated reqs
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
    def test_protected_endpoints_reject_unauthenticated(
        self, client, endpoint, method
    ):
        """Test that protected endpoints reject unauthenticated requests.

        The require_auth decorator returns 401 when request.is_json or
        request.content_type == 'application/json', and 302 (redirect to
        login) for plain HTML/browser-style requests. Both responses confirm
        auth is enforced — we accept either so GET requests without a JSON
        body are also covered correctly.
        """
        if method == "GET":
            response = client.get(endpoint)
        elif method == "POST":
            response = client.post(endpoint, json={})

        assert response.status_code in (302, 401), (
            f"{endpoint} should return 302 or 401 for unauthenticated "
            f"request, got {response.status_code}"
        )

    def test_status_endpoint_allows_unauthenticated(self, client, db_session):
        """Test that /api/status remains accessible without authentication.

        Requires db_session because the handler queries the streams table;
        without it, an earlier test's teardown leaves no tables and this
        test 500s in full-suite runs.
        """
        response = client.get(self.PUBLIC_ENDPOINT)
        assert response.status_code == 200, (
            f"{self.PUBLIC_ENDPOINT} should return 200 for unauthenticated "
            f"request, got {response.status_code}"
        )

    def test_protected_endpoint_with_auth(self, authenticated_client, app):
        """Test that a protected endpoint is accessible with authentication.

        The health endpoint may return 503 in test environments where real
        services are unavailable, but must not return 401/403 (auth errors)
        for an authenticated request.
        """
        client = authenticated_client("admin")
        response = client.get("/api/health/detailed")

        # Auth passed if we did not get 401 (unauthorized) or 403 (forbidden).
        # 503 is expected in test env when health sub-checks can't reach real
        # services.
        assert response.status_code not in (401, 403), (
            f"/api/health/detailed should not return auth error for an "
            f"authenticated request, got {response.status_code}"
        )
        data = response.get_json()
        assert data is not None
        assert isinstance(data, dict)

    def test_mgrs_conversion_latlon_auth_accepted(
        self, authenticated_client, app
    ):
        """Test that authenticated requests reach /api/convert-latlon-to-mgrs.

        The unauthenticated rejection for this endpoint is already covered by
        test_protected_endpoints_reject_unauthenticated. This test verifies
        that a valid session is not refused (i.e. auth does not return 401).
        A 400 (bad request) is fine — it means the endpoint was reached and
        only the payload was invalid.
        """
        auth_client = authenticated_client("admin")
        response = auth_client.post(
            "/api/convert-latlon-to-mgrs",
            json={"latitude": 0, "longitude": 0},
        )
        assert response.status_code != 401, (
            f"/api/convert-latlon-to-mgrs returned 401 for an authenticated "
            f"request — auth is broken, got {response.status_code}"
        )

    def test_mgrs_conversion_mgrslat_auth_accepted(
        self, authenticated_client, app
    ):
        """Test that authenticated requests reach /api/convert-mgrs-to-latlon.

        The unauthenticated rejection for this endpoint is already covered by
        test_protected_endpoints_reject_unauthenticated. This test verifies
        that a valid session is not refused (i.e. auth does not return 401).
        A 400 (bad request) is fine — it means the endpoint was reached and
        only the payload was invalid.
        """
        auth_client = authenticated_client("admin")
        response = auth_client.post(
            "/api/convert-mgrs-to-latlon",
            json={"mgrs": "31UEQ0000000000"},
        )
        assert response.status_code != 401, (
            f"/api/convert-mgrs-to-latlon returned 401 for an authenticated "
            f"request — auth is broken, got {response.status_code}"
        )
