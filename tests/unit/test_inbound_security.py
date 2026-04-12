"""
ABOUTME: Security-focused unit tests for the inbound HTTP endpoint covering API key masking,
ABOUTME: coordinate bounds rejection, payload size limits, content-type validation, IP allowlist, and rate limiting.
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_stream():
    """Create a mock inbound stream with default security settings."""
    stream = MagicMock()
    stream.id = 42
    stream.name = "Security Test Stream"
    stream.stream_mode = "inbound"
    stream.is_active = True
    stream.plugin_type = "generic_inbound"
    stream.cot_type = "a-f-G-U-C"
    stream.cot_stale_time = 300
    stream.cot_type_mode = "stream"
    stream.inbound_api_key = "secret-key-abc123"
    stream.inbound_rate_limit = 60
    stream.inbound_ip_allowlist = None
    stream.inbound_preview_mode = False
    stream.enable_callsign_mapping = False
    server = MagicMock(id=10, name="TAK1")
    stream.get_all_tak_servers.return_value = [server]
    stream.get_plugin_config.return_value = {
        "api_key": "secret-key-abc123",
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


# ---------------------------------------------------------------------------
# API Key Masking
# ---------------------------------------------------------------------------


class TestAPIKeyMasking:
    """Test that API keys are never logged in plaintext."""

    def test_mask_short_key(self):
        """Keys with 4 or fewer chars are fully masked."""
        from routes.inbound import _mask_api_key

        assert _mask_api_key("abc") == "****"
        assert _mask_api_key("abcd") == "****"

    def test_mask_normal_key(self):
        """Keys longer than 4 chars show only last 4."""
        from routes.inbound import _mask_api_key

        assert _mask_api_key("secret-key-abc123") == "****c123"

    def test_mask_empty_key(self):
        """Empty or None keys are fully masked."""
        from routes.inbound import _mask_api_key

        assert _mask_api_key("") == "****"
        assert _mask_api_key(None) == "****"

    def test_auth_failure_masks_key_in_logs(
        self, client, mock_stream, mock_plugin, mock_plugin_manager, caplog
    ):
        """Auth failure log message masks the API key."""
        mock_plugin.validate_inbound_request.return_value = (
            False,
            "Invalid API key",
        )

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             caplog.at_level(logging.WARNING, logger="routes.inbound"):
            mock_db.session.get.return_value = mock_stream

            client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer secret-key-abc123"},
            )

            # Verify the full key never appears in any log message
            for record in caplog.records:
                assert "secret-key-abc123" not in record.message

            # Verify only masked form appears
            auth_records = [
                r for r in caplog.records if "auth failed" in r.message.lower()
            ]
            assert len(auth_records) >= 1
            assert "****c123" in auth_records[0].message


# ---------------------------------------------------------------------------
# Coordinate Bounds Validation
# ---------------------------------------------------------------------------


class TestCoordinateBoundsRejection:
    """Test that invalid coordinates are rejected."""

    def test_latitude_too_high(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Latitude above 90 is rejected with 400."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "lat": 91.0, "lon": -77.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 91.0, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "latitude" in data["error"].lower()

    def test_latitude_too_low(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Latitude below -90 is rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "lat": -91.0, "lon": -77.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": -91.0, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400

    def test_longitude_too_high(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Longitude above 180 is rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "lat": 38.9, "lon": 181.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": 181.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "longitude" in data["error"].lower()

    def test_longitude_too_low(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Longitude below -180 is rejected."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "lat": 38.9, "lon": -181.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -181.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400

    def test_valid_boundary_coordinates(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Coordinates at exactly +-90/+-180 are valid."""
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "lat": 90.0, "lon": 180.0},
            {"uid": "dev-2", "lat": -90.0, "lon": -180.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 2, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps([
                    {"id": "dev-1", "lat": 90.0, "lon": 180.0},
                    {"id": "dev-2", "lat": -90.0, "lon": -180.0},
                ]),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 202

    def test_validate_coordinates_helper_valid(self):
        """_validate_coordinates returns None for valid locations."""
        from routes.inbound import _validate_coordinates

        result = _validate_coordinates([
            {"lat": 0, "lon": 0},
            {"lat": 45.5, "lon": -122.7},
        ])
        assert result is None

    def test_validate_coordinates_helper_invalid_lat(self):
        """_validate_coordinates returns error for bad latitude."""
        from routes.inbound import _validate_coordinates

        result = _validate_coordinates([{"lat": 95.0, "lon": 0}])
        assert result is not None
        assert "latitude" in result.lower()

    def test_validate_coordinates_helper_invalid_lon(self):
        """_validate_coordinates returns error for bad longitude."""
        from routes.inbound import _validate_coordinates

        result = _validate_coordinates([{"lat": 0, "lon": 200.0}])
        assert result is not None
        assert "longitude" in result.lower()

    def test_validate_coordinates_helper_none_skipped(self):
        """_validate_coordinates skips None lat/lon (optional fields)."""
        from routes.inbound import _validate_coordinates

        result = _validate_coordinates([
            {"lat": None, "lon": None},
            {"lat": 38.9, "lon": None},
        ])
        assert result is None


# ---------------------------------------------------------------------------
# Payload Size Limits
# ---------------------------------------------------------------------------


class TestPayloadSizeLimits:
    """Test that oversized payloads are rejected."""

    def test_oversized_content_length_rejected(self, client):
        """Request body exceeding 1 MB returns 413 (checked before DB lookup)."""
        # Flask test client sets Content-Length from actual data,
        # so we send a real oversized body to trigger the check.
        oversized = b"x" * (1_048_576 + 1)

        response = client.post(
            "/api/inbound/42/data",
            data=oversized,
            content_type="application/json",
        )

        assert response.status_code == 413
        data = response.get_json()
        assert "too large" in data["error"].lower()

    def test_oversized_body_rejected(self, client, mock_stream, mock_plugin_manager):
        """Request body exceeding 1 MB returns 413 even without Content-Length."""
        # Generate a body just over 1 MB
        oversized = b"x" * (1_048_576 + 1)

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=oversized,
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 413

    def test_max_locations_per_request(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """More than 100 locations per request returns 400."""
        mock_plugin.transform_payload.return_value = [
            {"uid": f"dev-{i}", "lat": 38.9, "lon": -77.0}
            for i in range(101)
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "too many" in data["error"].lower()

    def test_exactly_100_locations_accepted(self, client, mock_stream, mock_plugin, mock_plugin_manager):
        """Exactly 100 locations is within limits and accepted."""
        mock_plugin.transform_payload.return_value = [
            {"uid": f"dev-{i}", "lat": 38.9, "lon": -77.0}
            for i in range(100)
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 100, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 202


# ---------------------------------------------------------------------------
# Content-Type Validation
# ---------------------------------------------------------------------------


class TestContentTypeValidation:
    """Test that unsupported Content-Types are rejected."""

    def test_unsupported_content_type_rejected(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Unsupported Content-Type returns 415."""
        mock_plugin.get_accepted_content_types.return_value = ["application/json"]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"<xml>data</xml>",
                content_type="application/xml",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 415
            data = response.get_json()
            assert "unsupported" in data["error"].lower()

    def test_content_type_parameters_stripped(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Content-Type parameters like charset are stripped before comparison."""
        mock_plugin.get_accepted_content_types.return_value = ["application/json"]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json; charset=utf-8",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 202

    def test_content_type_case_insensitive(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Content-Type matching is case-insensitive."""
        mock_plugin.get_accepted_content_types.return_value = ["application/json"]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="Application/JSON",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 202


# ---------------------------------------------------------------------------
# IP Allowlist
# ---------------------------------------------------------------------------


class TestIPAllowlist:
    """Test IP-based access restrictions."""

    def test_no_allowlist_allows_all(self):
        """No allowlist configured means all IPs are allowed."""
        from routes.inbound import _check_ip_allowlist

        assert _check_ip_allowlist(None, "192.168.1.100") is True
        assert _check_ip_allowlist("", "10.0.0.1") is True

    def test_ip_in_cidr_allowed(self):
        """IP within a configured CIDR range is allowed."""
        from routes.inbound import _check_ip_allowlist

        allowlist = json.dumps(["192.168.1.0/24"])
        assert _check_ip_allowlist(allowlist, "192.168.1.50") is True

    def test_ip_outside_cidr_blocked(self):
        """IP outside all configured CIDRs is blocked."""
        from routes.inbound import _check_ip_allowlist

        allowlist = json.dumps(["192.168.1.0/24"])
        assert _check_ip_allowlist(allowlist, "10.0.0.1") is False

    def test_multiple_cidrs(self):
        """Multiple CIDRs — any match is sufficient."""
        from routes.inbound import _check_ip_allowlist

        allowlist = json.dumps(["192.168.1.0/24", "10.0.0.0/8"])
        assert _check_ip_allowlist(allowlist, "10.5.5.5") is True
        assert _check_ip_allowlist(allowlist, "172.16.0.1") is False

    def test_exact_ip(self):
        """Exact IP (single-host CIDR) works."""
        from routes.inbound import _check_ip_allowlist

        allowlist = json.dumps(["203.0.113.42/32"])
        assert _check_ip_allowlist(allowlist, "203.0.113.42") is True
        assert _check_ip_allowlist(allowlist, "203.0.113.43") is False

    def test_malformed_allowlist_fails_closed(self):
        """Malformed JSON allowlist denies access (fail closed)."""
        from routes.inbound import _check_ip_allowlist

        assert _check_ip_allowlist("not-json", "192.168.1.1") is False

    def test_invalid_cidr_fails_closed(self):
        """Invalid CIDR in allowlist denies access (fail closed)."""
        from routes.inbound import _check_ip_allowlist

        allowlist = json.dumps(["not-a-cidr"])
        assert _check_ip_allowlist(allowlist, "192.168.1.1") is False

    def test_ip_allowlist_returns_404(
        self, client, mock_stream, mock_plugin_manager
    ):
        """IP blocked by allowlist returns 404 (anti-enumeration)."""
        # Allow only 10.0.0.0/8 — Flask test client uses 127.0.0.1
        mock_stream.inbound_ip_allowlist = json.dumps(["10.0.0.0/8"])

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 404


# ---------------------------------------------------------------------------
# Anti-Enumeration (identical error responses)
# ---------------------------------------------------------------------------


class TestAntiEnumeration:
    """Test that different failure modes return identical responses."""

    def test_nonexistent_stream_returns_404(self, client):
        """Non-existent stream ID returns 404."""
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None

            response = client.post(
                "/api/inbound/99999/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
            )

            assert response.status_code == 404
            data = response.get_json()
            assert data == {"error": "Not found"}

    def test_inactive_stream_returns_same_404(self, client, mock_stream):
        """Inactive stream returns identical 404 (not 403 or other)."""
        mock_stream.is_active = False

        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
            )

            assert response.status_code == 404
            data = response.get_json()
            assert data == {"error": "Not found"}

    def test_poll_mode_stream_returns_same_404(self, client, mock_stream):
        """Poll-mode stream returns identical 404."""
        mock_stream.stream_mode = "poll"

        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
            )

            assert response.status_code == 404
            data = response.get_json()
            assert data == {"error": "Not found"}

    def test_auth_failure_returns_same_404(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Auth failure returns identical 404 response body."""
        mock_plugin.validate_inbound_request.return_value = (
            False,
            "Invalid API key",
        )

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer wrong-key"},
            )

            assert response.status_code == 404
            data = response.get_json()
            assert data == {"error": "Not found"}

    def test_all_failure_responses_identical(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """All non-found/auth failure paths produce the exact same JSON body."""
        expected_body = {"error": "Not found"}

        # Case 1: stream not found
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None
            r1 = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
            )

        # Case 2: stream inactive
        mock_stream.is_active = False
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = mock_stream
            r2 = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
            )
        mock_stream.is_active = True

        # Case 3: auth failed
        mock_plugin.validate_inbound_request.return_value = (False, "bad key")
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream
            r3 = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
            )

        # All must have the same status code and body
        assert r1.status_code == r2.status_code == r3.status_code == 404
        assert r1.get_json() == r2.get_json() == r3.get_json() == expected_body


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test per-stream sliding-window rate limiting."""

    def test_is_rate_limited_within_limit(self):
        """Requests within the limit are not throttled."""
        from routes.inbound import _is_rate_limited, _rate_limit_buckets

        # Clean slate for this test
        _rate_limit_buckets.pop(9999, None)
        assert _is_rate_limited(9999, 5) is False
        _rate_limit_buckets.pop(9999, None)

    def test_is_rate_limited_exceeds_limit(self):
        """Exceeding the limit triggers rate limiting."""
        from routes.inbound import _is_rate_limited, _rate_limit_buckets

        stream_id = 9998
        _rate_limit_buckets.pop(stream_id, None)

        # Fill to capacity
        for _ in range(5):
            assert _is_rate_limited(stream_id, 5) is False

        # Next should be limited
        assert _is_rate_limited(stream_id, 5) is True

        _rate_limit_buckets.pop(stream_id, None)

    def test_zero_rate_limit_disables(self):
        """Rate limit of 0 means no limiting."""
        from routes.inbound import _is_rate_limited

        assert _is_rate_limited(9997, 0) is False

    def test_negative_rate_limit_disables(self):
        """Negative rate limit means no limiting."""
        from routes.inbound import _is_rate_limited

        assert _is_rate_limited(9996, -1) is False

    def test_none_rate_limit_disables(self):
        """None rate limit means no limiting."""
        from routes.inbound import _is_rate_limited

        assert _is_rate_limited(9995, None) is False

    def test_rate_limit_returns_429(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Exceeding rate limit via the HTTP endpoint returns 429."""
        from routes.inbound import _rate_limit_buckets

        # Use a unique stream ID to avoid cross-test contamination
        test_stream_id = 7777
        mock_stream.id = test_stream_id
        mock_stream.inbound_rate_limit = 1  # 1 per minute
        _rate_limit_buckets.pop(test_stream_id, None)

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1, "servers": {},
             }):
            mock_db.session.get.return_value = mock_stream

            # First request should succeed
            r1 = client.post(
                f"/api/inbound/{test_stream_id}/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )
            assert r1.status_code == 202

            # Second request should hit rate limit
            r2 = client.post(
                f"/api/inbound/{test_stream_id}/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )
            assert r2.status_code == 429
            data = r2.get_json()
            assert "rate limit" in data["error"].lower()

        _rate_limit_buckets.pop(test_stream_id, None)


# ---------------------------------------------------------------------------
# Transform Failure
# ---------------------------------------------------------------------------


class TestTransformFailure:
    """Test error handling when payload transformation fails."""

    def test_transform_exception_returns_400(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Plugin transform_payload raising an exception returns 400."""
        mock_plugin.transform_payload.side_effect = ValueError("Bad JSON")

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"not-json",
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "transform failed" in data["error"].lower()

    def test_empty_locations_returns_400(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Plugin returning empty locations list returns 400."""
        mock_plugin.transform_payload.return_value = []

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            data = response.get_json()
            assert "no locations" in data["error"].lower()


# ---------------------------------------------------------------------------
# No Stack Traces in Responses
# ---------------------------------------------------------------------------


class TestNoStackTracesInResponses:
    """Test that error responses never contain stack traces."""

    def test_transform_error_no_traceback(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Transform errors return generic message, not exception details."""
        mock_plugin.transform_payload.side_effect = RuntimeError(
            "Internal details: database unavailable at /var/lib/data"
        )

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/data",
                data=b"{}",
                content_type="application/json",
                headers={"Authorization": "Bearer test-key"},
            )

            assert response.status_code == 400
            body = response.get_data(as_text=True)
            # Should NOT contain internal paths or traceback keywords
            assert "/var/lib/" not in body
            assert "Traceback" not in body
            assert "database unavailable" not in body
