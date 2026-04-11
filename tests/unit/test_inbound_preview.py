"""
ABOUTME: Unit tests for Phase 5 capture & preview mode covering the ring buffer
ABOUTME: in InboundStreamWorker, preview-mode routing in the data endpoint, and preview API endpoints.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure the inbound stream registry is empty before and after each test."""
    from services.inbound_stream_worker import _active_inbound_streams, _registry_lock

    with _registry_lock:
        _active_inbound_streams.clear()
    yield
    with _registry_lock:
        _active_inbound_streams.clear()


@pytest.fixture
def mock_stream():
    """Create a mock inbound stream in preview mode."""
    stream = MagicMock()
    stream.id = 42
    stream.name = "Preview Stream"
    stream.stream_mode = "inbound"
    stream.is_active = True
    stream.plugin_type = "generic_inbound"
    stream.cot_type = "a-f-G-U-C"
    stream.cot_stale_time = 300
    stream.cot_type_mode = "stream"
    stream.inbound_api_key = "test-api-key-123"
    stream.inbound_rate_limit = 60
    stream.inbound_ip_allowlist = None
    stream.inbound_preview_mode = True
    stream.enable_callsign_mapping = False
    server = MagicMock(id=10, name="TAK1")
    stream.get_all_tak_servers.return_value = [server]
    stream.tak_server = server
    stream.tak_server_id = server.id
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


@pytest.fixture
def worker(mock_stream):
    """Create an InboundStreamWorker instance."""
    from services.inbound_stream_worker import InboundStreamWorker

    return InboundStreamWorker(mock_stream, MagicMock(), MagicMock())


# ---------------------------------------------------------------------------
# Capture buffer — ring buffer behavior
# ---------------------------------------------------------------------------


class TestCaptureBuffer:
    """Test the in-memory ring buffer on InboundStreamWorker."""

    def test_buffer_starts_empty(self, worker):
        """Capture buffer is empty on creation."""
        assert worker.get_captured_payloads() == []

    def test_capture_stores_entry(self, worker):
        """capture_payload() adds an entry to the buffer."""
        worker.capture_payload(
            raw_body=b'{"lat": 38.9}',
            content_type="application/json",
            headers={"Authorization": "Bearer ****1234"},
            source_ip="10.0.0.1",
            mapped_result=[{"uid": "d1", "lat": 38.9, "lon": -77.0}],
        )

        payloads = worker.get_captured_payloads()
        assert len(payloads) == 1

    def test_capture_entry_structure(self, worker):
        """Captured entry contains expected fields."""
        worker.capture_payload(
            raw_body=b'{"lat": 38.9}',
            content_type="application/json",
            headers={"Host": "localhost"},
            source_ip="10.0.0.1",
            mapped_result=[{"uid": "d1", "lat": 38.9, "lon": -77.0}],
        )

        entry = worker.get_captured_payloads()[0]
        assert "raw_body" in entry
        assert "content_type" in entry
        assert "headers" in entry
        assert "source_ip" in entry
        assert "received_at" in entry
        assert "mapped_result" in entry

    def test_capture_masks_auth_header(self, worker):
        """Authorization header is masked in captured entries."""
        worker.capture_payload(
            raw_body=b"{}",
            content_type="application/json",
            headers={"Authorization": "Bearer super-secret-key-9999"},
            source_ip="10.0.0.1",
            mapped_result=[],
        )

        entry = worker.get_captured_payloads()[0]
        auth_value = entry["headers"].get("Authorization", "")
        assert "super-secret-key-9999" not in auth_value
        assert "****" in auth_value

    def test_buffer_ring_evicts_oldest(self, worker):
        """Buffer evicts oldest entries when max count (10) is reached."""
        for i in range(12):
            worker.capture_payload(
                raw_body=f'{{"seq": {i}}}'.encode(),
                content_type="application/json",
                headers={},
                source_ip="10.0.0.1",
                mapped_result=[{"uid": f"d{i}"}],
            )

        payloads = worker.get_captured_payloads()
        assert len(payloads) == 10
        # Oldest two (seq 0, 1) should have been evicted
        first_body = payloads[0]["raw_body"]
        assert b'"seq": 2' in first_body

    def test_buffer_size_cap(self, worker):
        """Buffer evicts oldest when cumulative size exceeds ~100KB."""
        # Each payload is ~20KB, so 6 of them exceed 100KB
        big_body = b"x" * 20_000
        for i in range(6):
            worker.capture_payload(
                raw_body=big_body,
                content_type="application/octet-stream",
                headers={},
                source_ip="10.0.0.1",
                mapped_result=[],
            )

        payloads = worker.get_captured_payloads()
        total_size = sum(len(p["raw_body"]) for p in payloads)
        assert total_size <= 102_400  # 100KB cap

    def test_clear_buffer(self, worker):
        """clear_captured_payloads() empties the buffer."""
        worker.capture_payload(
            raw_body=b"{}",
            content_type="application/json",
            headers={},
            source_ip="10.0.0.1",
            mapped_result=[],
        )
        assert len(worker.get_captured_payloads()) == 1

        worker.clear_captured_payloads()
        assert len(worker.get_captured_payloads()) == 0

    def test_get_returns_copy(self, worker):
        """get_captured_payloads() returns a copy, not the internal list."""
        worker.capture_payload(
            raw_body=b"{}",
            content_type="application/json",
            headers={},
            source_ip="10.0.0.1",
            mapped_result=[],
        )

        payloads = worker.get_captured_payloads()
        payloads.clear()
        # Internal buffer should be unaffected
        assert len(worker.get_captured_payloads()) == 1

    def test_stop_clears_buffer(self, worker):
        """Stopping the worker clears the capture buffer."""
        worker.capture_payload(
            raw_body=b"{}",
            content_type="application/json",
            headers={},
            source_ip="10.0.0.1",
            mapped_result=[],
        )

        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        import asyncio

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            asyncio.get_event_loop().run_until_complete(worker.start())
            asyncio.get_event_loop().run_until_complete(worker.stop())

        assert len(worker.get_captured_payloads()) == 0


# ---------------------------------------------------------------------------
# Preview mode — data endpoint skips TAK distribution
# ---------------------------------------------------------------------------


class TestPreviewModeDataEndpoint:
    """Test that the data endpoint buffers instead of distributing in preview mode."""

    def test_preview_mode_returns_202(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Preview mode returns 202 Accepted."""
        mock_stream.inbound_preview_mode = True

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._get_worker_for_stream", return_value=MagicMock()):
            mock_db.session.get.return_value = mock_stream
            mock_db.session.commit = MagicMock()

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 202

    def test_preview_mode_does_not_call_process_async(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Preview mode does NOT call _process_inbound_async (no TAK distribution)."""
        mock_stream.inbound_preview_mode = True

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async") as mock_process, \
             patch("routes.inbound._get_worker_for_stream", return_value=MagicMock()):
            mock_db.session.get.return_value = mock_stream
            mock_db.session.commit = MagicMock()

            client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            mock_process.assert_not_called()

    def test_preview_response_includes_mapped_result(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Preview response body includes the mapped locations for debugging."""
        mock_stream.inbound_preview_mode = True
        mock_plugin.transform_payload.return_value = [
            {"uid": "dev-1", "name": "Alpha", "lat": 38.9, "lon": -77.0},
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._get_worker_for_stream", return_value=MagicMock()):
            mock_db.session.get.return_value = mock_stream
            mock_db.session.commit = MagicMock()

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            data = response.get_json()
            assert data["status"] == "preview"
            assert "mapped_result" in data
            assert len(data["mapped_result"]) == 1
            assert data["mapped_result"][0]["uid"] == "dev-1"

    def test_preview_mode_captures_payload(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Preview mode calls capture_payload on the worker."""
        mock_stream.inbound_preview_mode = True
        mock_worker = MagicMock()

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker):
            mock_db.session.get.return_value = mock_stream
            mock_db.session.commit = MagicMock()

            client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            mock_worker.capture_payload.assert_called_once()

    def test_live_mode_still_distributes(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """When preview mode is off, normal TAK distribution proceeds."""
        mock_stream.inbound_preview_mode = False

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async", return_value={
                 "success": True, "events_created": 1,
                 "servers": {"TAK1": {"success": True, "events_enqueued": 1}},
             }):
            mock_db.session.get.return_value = mock_stream
            mock_db.session.commit = MagicMock()

            response = client.post(
                "/api/inbound/42/data",
                data=json.dumps({"id": "dev-1", "lat": 38.9, "lon": -77.0}),
                content_type="application/json",
                headers={"Authorization": "Bearer test-api-key-123"},
            )

            assert response.status_code == 202
            assert response.get_json()["status"] == "accepted"


# ---------------------------------------------------------------------------
# Preview API endpoints
# ---------------------------------------------------------------------------


class TestGetPreview:
    """Test GET /api/inbound/<stream_id>/preview."""

    def test_get_preview_returns_captured_payloads(
        self, client, mock_stream, mock_plugin_manager
    ):
        """GET preview returns the capture buffer contents."""
        mock_worker = MagicMock()
        mock_worker.get_captured_payloads.return_value = [
            {
                "raw_body": b'{"lat": 38.9}',
                "content_type": "application/json",
                "headers": {},
                "source_ip": "10.0.0.1",
                "received_at": "2026-04-11T12:00:00Z",
                "mapped_result": [{"uid": "d1", "lat": 38.9}],
            }
        ]

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker):
            mock_db.session.get.return_value = mock_stream

            response = client.get("/api/inbound/42/preview")

            assert response.status_code == 200
            data = response.get_json()
            assert "payloads" in data
            assert len(data["payloads"]) == 1

    def test_get_preview_nonexistent_stream_returns_404(self, client):
        """GET preview for nonexistent stream returns 404."""
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None

            response = client.get("/api/inbound/9999/preview")
            assert response.status_code == 404

    def test_get_preview_non_inbound_returns_404(self, client, mock_stream):
        """GET preview for poll-mode stream returns 404."""
        mock_stream.stream_mode = "poll"

        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = mock_stream

            response = client.get("/api/inbound/42/preview")
            assert response.status_code == 404

    def test_get_preview_no_worker_returns_empty(self, client, mock_stream):
        """GET preview when no worker is active returns empty list."""
        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=None):
            mock_db.session.get.return_value = mock_stream

            response = client.get("/api/inbound/42/preview")

            assert response.status_code == 200
            data = response.get_json()
            assert data["payloads"] == []


class TestDeletePreview:
    """Test DELETE /api/inbound/<stream_id>/preview."""

    def test_delete_clears_buffer(self, client, mock_stream):
        """DELETE preview clears the capture buffer."""
        mock_worker = MagicMock()

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker):
            mock_db.session.get.return_value = mock_stream

            response = client.delete("/api/inbound/42/preview")

            assert response.status_code == 200
            mock_worker.clear_captured_payloads.assert_called_once()

    def test_delete_nonexistent_stream_returns_404(self, client):
        """DELETE preview for nonexistent stream returns 404."""
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None

            response = client.delete("/api/inbound/9999/preview")
            assert response.status_code == 404


class TestRemapPreview:
    """Test POST /api/inbound/<stream_id>/preview/remap."""

    def test_remap_reprocesses_with_alternate_config(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Remap re-runs transform_payload against captured payloads with new config."""
        captured = [
            {
                "raw_body": b'{"latitude": 38.9, "longitude": -77.0, "device_id": "d1"}',
                "content_type": "application/json",
                "headers": {},
                "source_ip": "10.0.0.1",
                "received_at": "2026-04-11T12:00:00Z",
                "mapped_result": [{"uid": "d1", "lat": 38.9}],
            }
        ]

        mock_worker = MagicMock()
        mock_worker.get_captured_payloads.return_value = captured

        # The re-mapped plugin returns different results with new config
        remap_plugin = MagicMock()
        remap_plugin.transform_payload.return_value = [
            {"uid": "d1", "name": "Device1", "lat": 38.9, "lon": -77.0},
        ]
        remap_plugin_class = MagicMock(return_value=remap_plugin)
        mock_pm = MagicMock()
        mock_pm.get_plugin_class.return_value = remap_plugin_class

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker), \
             patch("routes.inbound.get_plugin_manager", return_value=mock_pm):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/preview/remap",
                data=json.dumps({
                    "plugin_config": {"lat_field": "latitude", "lon_field": "longitude"},
                }),
                content_type="application/json",
            )

            assert response.status_code == 200
            data = response.get_json()
            assert "results" in data
            assert len(data["results"]) == 1

    def test_remap_does_not_save_config(
        self, client, mock_stream, mock_plugin, mock_plugin_manager
    ):
        """Remap does NOT persist config changes to the stream."""
        mock_worker = MagicMock()
        mock_worker.get_captured_payloads.return_value = [
            {
                "raw_body": b'{"lat": 38.9}',
                "content_type": "application/json",
                "headers": {},
                "source_ip": "10.0.0.1",
                "received_at": "2026-04-11T12:00:00Z",
                "mapped_result": [],
            }
        ]

        remap_plugin = MagicMock()
        remap_plugin.transform_payload.return_value = []
        remap_plugin_class = MagicMock(return_value=remap_plugin)
        mock_pm = MagicMock()
        mock_pm.get_plugin_class.return_value = remap_plugin_class

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker), \
             patch("routes.inbound.get_plugin_manager", return_value=mock_pm):
            mock_db.session.get.return_value = mock_stream

            client.post(
                "/api/inbound/42/preview/remap",
                data=json.dumps({"plugin_config": {"lat_field": "new_path"}}),
                content_type="application/json",
            )

            # stream.set_plugin_config or db.session.commit should NOT have been called
            # to persist config changes
            mock_db.session.commit.assert_not_called()

    def test_remap_empty_buffer_returns_empty(
        self, client, mock_stream, mock_plugin_manager
    ):
        """Remap with empty buffer returns empty results."""
        mock_worker = MagicMock()
        mock_worker.get_captured_payloads.return_value = []

        with patch("routes.inbound.db") as mock_db, \
             patch("routes.inbound._get_worker_for_stream", return_value=mock_worker), \
             patch("routes.inbound.get_plugin_manager", return_value=mock_plugin_manager):
            mock_db.session.get.return_value = mock_stream

            response = client.post(
                "/api/inbound/42/preview/remap",
                data=json.dumps({"plugin_config": {}}),
                content_type="application/json",
            )

            assert response.status_code == 200
            assert response.get_json()["results"] == []

    def test_remap_nonexistent_stream_returns_404(self, client):
        """Remap for nonexistent stream returns 404."""
        with patch("routes.inbound.db") as mock_db:
            mock_db.session.get.return_value = None

            response = client.post(
                "/api/inbound/9999/preview/remap",
                data=json.dumps({"plugin_config": {}}),
                content_type="application/json",
            )
            assert response.status_code == 404
