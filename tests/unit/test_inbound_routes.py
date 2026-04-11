"""
ABOUTME: Unit tests for the inbound HTTP endpoint covering authentication, validation,
ABOUTME: rate limiting, anti-enumeration, payload processing, and error handling.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_stream():
    """Create a mock inbound stream."""
    stream = MagicMock()
    stream.id = 42
    stream.name = "Test Inbound"
    stream.stream_mode = "inbound"
    stream.is_active = True
    stream.plugin_type = "generic_inbound"
    stream.cot_type = "a-f-G-U-C"
    stream.cot_stale_time = 300
    stream.cot_type_mode = "stream"
    stream.inbound_api_key = "test-api-key-123"
    stream.inbound_rate_limit = 60
    stream.inbound_ip_allowlist = None
    stream.inbound_preview_mode = False
    stream.enable_callsign_mapping = False
    server = MagicMock(id=10, name="TAK1")
    stream.get_all_tak_servers.return_value = [server]
    stream.get_plugin_config.return_value = {
        "api_key": "test-api-key-123",
        "auth_mode": "api_key",
    }
    return stream


@pytest.fixture
def mock_plugin():
    """Create a mock inbound plugin."""
    plugin = MagicMock()
    plugin.plugin_name = "generic_inbound"
    plugin.validate_inbound_request.return_value = (True, None)
    plugin.transform_payload.return_value = [
        {"uid": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0},
    ]
    plugin.get_accepted_content_types.return_value = ["application/json"]
    return plugin


@pytest.fixture
def mock_plugin_manager(mock_plugin):
    """Create a mock plugin manager that returns our mock plugin."""
    pm = MagicMock()
    pm.get_plugin_class.return_value = MagicMock(return_value=mock_plugin)
    return pm


class TestInboundEndpointAuth:
    """Test authentication on the inbound endpoint."""

    def test_valid_request(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Valid request with correct auth returns 202."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {"TAK1": {"success": True, "events_enqueued": 1}},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 202

    def test_auth_failure_returns_404(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Auth failure returns 404 (anti-enumeration: same as not-found)."""
        mock_plugin.validate_inbound_request.return_value = (False, "Invalid API key")

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer wrong-key"},
            )

            # Anti-enumeration: auth failure returns same code as not-found
            assert response.status_code == 404

    def test_stream_not_found_returns_404(self, client):
        """Non-existent stream returns 404."""
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None

            response = client.post(
                "/api/inbound/9999/data",
                data=json.dumps({"id": "dev-1"}),
                content_type="application/json",
                headers={"Authorization": "Bearer anything"},
            )

            assert response.status_code == 404

    def test_identical_error_for_not_found_and_auth_fail(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Not-found and auth-fail responses are identical to prevent enumeration."""
        # Request for non-existent stream
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None
            not_found_resp = client.post(
                "/api/inbound/9999/data",
                data=b"{}",
                content_type="application/json",
                headers={"Authorization": "Bearer x"},
            )

        # Request with bad auth
        mock_plugin.validate_inbound_request.return_value = (False, "Invalid API key")
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream
            auth_fail_resp = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
                headers={"Authorization": "Bearer wrong"},
            )

        assert not_found_resp.status_code == auth_fail_resp.status_code
        nf_body = not_found_resp.get_json()
        af_body = auth_fail_resp.get_json()
        assert nf_body["error"] == af_body["error"]


class TestStreamValidation:
    """Test stream state validation."""

    def test_inactive_stream_returns_404(self, client, mock_stream, mock_plugin_manager):
        """Inactive stream returns 404."""
        mock_stream.is_active = False

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 404

    def test_poll_mode_stream_returns_404(self, client, mock_stream, mock_plugin_manager):
        """Poll-mode stream returns 404 on inbound endpoint."""
        mock_stream.stream_mode = "poll"

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 404


class TestPayloadValidation:
    """Test request body validation."""

    def test_payload_too_large(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Payload exceeding size limit returns 413."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound.MAX_PAYLOAD_BYTES", 100):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"x" * 200,
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 413

    def test_unsupported_content_type(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Unsupported content type returns 415."""
        mock_plugin.get_accepted_content_types.return_value = ["application/json"]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"<xml/>",
                content_type="application/xml",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 415

    def test_transform_failure_returns_400(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Plugin transform_payload raising ValueError returns 400."""
        mock_plugin.transform_payload.side_effect = ValueError("Invalid JSON")

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"not json",
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 400


class TestLocationValidation:
    """Test coordinate and location validation."""

    def test_invalid_latitude_rejected(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Latitude outside ±90 is rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "d1", "name": "Bad", "lat": 91.0, "lon": -77.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"lat": 91.0, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 400
            assert "coordinate" in response.get_json()["error"].lower()

    def test_invalid_longitude_rejected(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Longitude outside ±180 is rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "d1", "name": "Bad", "lat": 38.9, "lon": 181.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"lat": 38.9, "lon": 181.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 400

    def test_too_many_locations_rejected(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """More than MAX_LOCATIONS_PER_REQUEST locations are rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": f"d{i}", "name": f"Dev{i}", "lat": 38.0 + i * 0.01, "lon": -77.0}
            for i in range(200)
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound.MAX_LOCATIONS_PER_REQUEST", 100):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps([{"id": f"d{i}"} for i in range(200)]),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 400


class TestIPAllowlist:
    """Test IP allowlist enforcement."""

    def test_allowed_ip_passes(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Request from allowed IP succeeds."""
        mock_stream.inbound_ip_allowlist = json.dumps(["127.0.0.0/8"])

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 202

    def test_blocked_ip_returns_404(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Request from non-allowed IP returns 404 (anti-enumeration)."""
        mock_stream.inbound_ip_allowlist = json.dumps(["10.0.0.0/8"])

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1"}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            # Anti-enumeration: blocked IP same response as not-found
            assert response.status_code == 404

    def test_null_allowlist_allows_all(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Null IP allowlist allows all IPs."""
        mock_stream.inbound_ip_allowlist = None

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 202


class TestSuccessfulProcessing:
    """Test the happy path."""

    def test_response_includes_server_status(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Successful response includes per-server delivery status."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True,
                 "events_created": 1,
                 "servers": {"TAK1": {"success": True, "events_enqueued": 1}},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            data = response.get_json()
            assert data["events_created"] == 1
            assert "servers" in data

    def test_updates_stream_stats(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Successful request updates stream statistics."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            mock_stream.update_stats.assert_called_once()


class TestProcessingFailure:
    """Test error paths in the processing pipeline."""

    def test_cot_service_failure_returns_500(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Internal error during CoT processing returns 500."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": False, "error": "CoT creation failed",
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "d1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 500
