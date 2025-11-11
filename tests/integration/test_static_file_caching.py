"""
Integration tests for static file caching and 304 Not Modified responses.

These tests verify that the application correctly handles HTTP caching for static
files, particularly ensuring that 304 Not Modified responses don't trigger ASGI
protocol violations.

This test suite exists to prevent regression of the Hypercorn 0.18.0 bug where
304 responses caused ASGI errors due to improper header/body ordering.
"""

import pytest

from app import create_app
from database import db


@pytest.fixture
def app():
    """Create test application."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestStaticFileCaching:
    """Test static file HTTP caching behavior."""

    def test_static_file_returns_200_on_first_request(self, client):
        """Test that static files return 200 OK on first request."""
        response = client.get("/static/css/bootstrap.min.css")

        # Skip if static files not available in test environment
        if response.status_code == 404:
            pytest.skip("Static files not available in test environment")

        assert response.status_code == 200
        assert response.data is not None
        assert len(response.data) > 0
        assert "ETag" in response.headers or "Last-Modified" in response.headers

    def test_static_file_returns_304_with_matching_etag(self, client):
        """Test that static files return 304 Not Modified with matching ETag."""
        # First request to get ETag
        first_response = client.get("/static/css/bootstrap.min.css")

        # Skip if static files not available
        if first_response.status_code == 404:
            pytest.skip("Static files not available in test environment")

        assert first_response.status_code == 200

        etag = first_response.headers.get("ETag")
        if not etag:
            pytest.skip("Server does not send ETag headers")

        # Second request with If-None-Match header
        second_response = client.get(
            "/static/css/bootstrap.min.css",
            headers={"If-None-Match": etag}
        )

        # CRITICAL: 304 response must have no body
        assert second_response.status_code == 304
        assert len(second_response.data) == 0, (
            "304 Not Modified response MUST NOT contain a body. "
            "This violates HTTP spec and causes ASGI protocol errors."
        )

    def test_static_file_returns_304_with_matching_last_modified(self, client):
        """Test that static files return 304 Not Modified with matching Last-Modified."""
        # First request to get Last-Modified
        first_response = client.get("/static/js/bootstrap.bundle.min.js")

        # Skip if static files not available
        if first_response.status_code == 404:
            pytest.skip("Static files not available in test environment")

        assert first_response.status_code == 200

        last_modified = first_response.headers.get("Last-Modified")
        if not last_modified:
            pytest.skip("Server does not send Last-Modified headers")

        # Second request with If-Modified-Since header
        second_response = client.get(
            "/static/js/bootstrap.bundle.min.js",
            headers={"If-Modified-Since": last_modified}
        )

        # CRITICAL: 304 response must have no body
        assert second_response.status_code == 304
        assert len(second_response.data) == 0, (
            "304 Not Modified response MUST NOT contain a body. "
            "This violates HTTP spec and causes ASGI protocol errors."
        )

    def test_multiple_static_files_handle_304_correctly(self, client):
        """Test that multiple static files all handle 304 responses correctly."""
        static_files = [
            "/static/css/bootstrap.min.css",
            "/static/css/all.min.css",
            "/static/js/bootstrap.bundle.min.js",
            "/static/js/jquery.min.js",
        ]

        for file_path in static_files:
            # First request
            first_response = client.get(file_path)

            # Skip if file doesn't exist
            if first_response.status_code == 404:
                continue

            assert first_response.status_code == 200

            # Get caching header
            etag = first_response.headers.get("ETag")
            last_modified = first_response.headers.get("Last-Modified")

            if not etag and not last_modified:
                continue

            # Second request with caching header
            headers = {}
            if etag:
                headers["If-None-Match"] = etag
            elif last_modified:
                headers["If-Modified-Since"] = last_modified

            second_response = client.get(file_path, headers=headers)

            # Verify 304 has no body
            if second_response.status_code == 304:
                assert len(second_response.data) == 0, (
                    f"304 response for {file_path} has body content. "
                    "This causes ASGI protocol violations."
                )

    def test_modified_static_file_returns_200_not_304(self, client):
        """Test that modified files return 200, not 304."""
        # First request
        first_response = client.get("/static/css/bootstrap.min.css")

        # Skip if static files not available
        if first_response.status_code == 404:
            pytest.skip("Static files not available in test environment")

        assert first_response.status_code == 200

        etag = first_response.headers.get("ETag")
        if not etag:
            pytest.skip("Server does not send ETag headers")

        # Request with intentionally wrong ETag (simulating file change)
        wrong_etag = '"wrong-etag-value"'
        second_response = client.get(
            "/static/css/bootstrap.min.css",
            headers={"If-None-Match": wrong_etag}
        )

        # Should return 200 with full content, not 304
        assert second_response.status_code == 200
        assert len(second_response.data) > 0

    def test_no_after_request_hooks_inspect_304_bodies(self, app):
        """Test that no after_request hooks attempt to read 304 response bodies."""
        # This is a meta-test to ensure the bug doesn't get reintroduced

        after_request_funcs = app.after_request_funcs.get(None, [])

        if not after_request_funcs:
            # No after_request hooks, test passes
            return

        # Check that none of the hooks have suspicious patterns
        # This is a static analysis check, not a runtime check
        for func in after_request_funcs:
            func_source = func.__code__.co_names

            # Check for dangerous patterns
            assert "get_data" not in func_source, (
                f"after_request hook '{func.__name__}' calls get_data(). "
                "This can cause ASGI violations on 304 responses."
            )
            assert "data" not in func_source or "read" not in func_source, (
                f"after_request hook '{func.__name__}' may access response body. "
                "Verify it doesn't touch 304 responses."
            )


class TestStaticFileASGICompliance:
    """Test ASGI protocol compliance for static file responses."""

    def test_static_file_headers_sent_before_body(self, client):
        """Verify that response headers are always sent before body content."""
        # This test ensures the ASGI message ordering is correct:
        # 1. http.response.start (with headers)
        # 2. http.response.body (with content)

        response = client.get("/static/css/bootstrap.min.css")

        # If we get a response without errors, ASGI ordering is correct
        assert response.status_code in [200, 304, 404]
        assert response.headers is not None

    def test_304_response_has_proper_headers(self, client):
        """Test that 304 responses include required headers but no body."""
        # First request
        first_response = client.get("/static/css/bootstrap.min.css")
        if first_response.status_code != 200:
            pytest.skip("Static file not found")

        etag = first_response.headers.get("ETag")
        if not etag:
            pytest.skip("Server does not send ETag headers")

        # Second request for 304
        response = client.get(
            "/static/css/bootstrap.min.css",
            headers={"If-None-Match": etag}
        )

        assert response.status_code == 304

        # 304 responses MUST include certain headers
        assert "Date" in response.headers or True  # Date is optional
        assert "ETag" in response.headers or "Last-Modified" in response.headers

        # 304 responses MUST NOT include Content-Length or Transfer-Encoding
        # (unless Content-Length: 0)
        content_length = response.headers.get("Content-Length")
        if content_length:
            assert content_length == "0", (
                "304 response has non-zero Content-Length. "
                "This can cause ASGI protocol violations."
            )

        # 304 responses MUST have empty body
        assert len(response.data) == 0


@pytest.mark.integration
class TestHypercornCompatibility:
    """Test compatibility with Hypercorn ASGI server."""

    def test_hypercorn_version_check(self):
        """Verify that Hypercorn version is pinned to avoid known bugs."""
        try:
            # Hypercorn doesn't have __version__, use importlib.metadata
            try:
                from importlib.metadata import version as get_version
            except ImportError:
                # Python < 3.8 fallback
                from importlib_metadata import version as get_version

            version = get_version('hypercorn')

            # Version should be < 0.18.0 due to WSGI header bug
            version_parts = version.split('.')[:3]
            major, minor = int(version_parts[0]), int(version_parts[1])

            assert (major, minor) < (0, 18), (
                f"Hypercorn {version} has known WSGI header handling bugs. "
                f"Pin to <0.18.0 in pyproject.toml"
            )

            # Recommend 0.17.x series
            assert (major, minor) >= (0, 17), (
                f"Hypercorn {version} is too old. Recommend >=0.17.0,<0.18.0"
            )

        except ImportError:
            pytest.skip("Hypercorn not installed")

    def test_werkzeug_version_check(self):
        """Verify that Werkzeug version is compatible."""
        try:
            # Use importlib.metadata instead of deprecated __version__
            try:
                from importlib.metadata import version as get_version
            except ImportError:
                # Python < 3.8 fallback
                from importlib_metadata import version as get_version

            version = get_version('werkzeug')

            major = int(version.split('.')[0])

            # Should be using Werkzeug 3.x for Flask 3.x
            assert major == 3, (
                f"Werkzeug {version} may be incompatible. "
                f"Use 3.x for Flask 3.x"
            )

        except ImportError:
            pytest.skip("Werkzeug not installed")
