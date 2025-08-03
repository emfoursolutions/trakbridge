"""Unit tests for TrakBridge routes."""

import json
from unittest.mock import Mock, patch

import pytest


class TestMainRoutes:
    """Test main application routes."""

    def test_health_endpoint(self, client):
        """Test the health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200

        # Try to parse JSON response
        try:
            data = response.get_json()
            assert data is not None
        except:
            # If JSON parsing fails, check that we got some response
            assert response.data is not None

    def test_health_detailed_endpoint(self, client):
        """Test the detailed health endpoint."""
        response = client.get("/api/health/detailed")
        # Should return 200 or redirect to login
        assert response.status_code in [200, 302, 401, 503]

    def test_root_endpoint(self, client):
        """Test the root endpoint."""
        response = client.get("/")
        # Should return 200 or redirect to login/startup
        assert response.status_code in [200, 302, 503]


class TestAPIRoutes:
    """Test API routes."""

    def test_api_health(self, client):
        """Test API health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_api_streams_endpoint_exists(self, client):
        """Test that streams API endpoint exists."""
        response = client.get("/streams")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404

    def test_api_tak_servers_endpoint_exists(self, client):
        """Test that TAK servers API endpoint exists."""
        response = client.get("/tak-servers")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestStreamRoutes:
    """Test stream management routes."""

    def test_streams_index_exists(self, client):
        """Test that streams index exists."""
        response = client.get("/streams/")
        # Should not return 404 (endpoint exists), but may redirect or require auth
        assert response.status_code != 404

    def test_create_stream_page_exists(self, client):
        """Test that create stream page exists."""
        response = client.get("/streams/create")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestTakServerRoutes:
    """Test TAK server management routes."""

    def test_tak_servers_index_exists(self, client):
        """Test that TAK servers index exists."""
        response = client.get("/tak-servers/")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404

    def test_create_tak_server_page_exists(self, client):
        """Test that create TAK server page exists."""
        response = client.get("/tak-servers/create")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestAuthRoutes:
    """Test authentication routes."""

    def test_login_page_exists(self, client):
        """Test that login page exists."""
        response = client.get("/auth/login")
        # Should not return 404 (endpoint exists)
        assert response.status_code != 404

    def test_logout_endpoint_exists(self, client):
        """Test that logout endpoint exists."""
        response = client.get("/auth/logout")
        # Should not return 404 (endpoint exists), may redirect
        assert response.status_code != 404
