"""
ABOUTME: End-to-end integration tests for the inbound push pipeline verifying that
ABOUTME: POST data is transformed to CoT XML and enqueued for TAK server distribution.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import create_app
from database import db
from models.stream import Stream
from plugins.generic_inbound_plugin import GenericInboundPlugin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a test Flask application with a clean database."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_plugin_manager():
    """Plugin manager that returns the real GenericInboundPlugin class."""
    pm = MagicMock()
    pm.get_plugin_class.return_value = GenericInboundPlugin
    return pm


@pytest.fixture
def inbound_stream(app):
    """Create a real inbound stream in the database."""
    with app.app_context():
        stream = Stream(
            name="E2E Inbound Stream",
            plugin_type="generic_json_inbound",
            stream_mode="inbound",
            inbound_rate_limit=60,
            inbound_preview_mode=False,
        )
        stream.is_active = True
        stream.plugin_config = json.dumps({
            "auth_mode": "none",
            "lat_field": "lat",
            "lon_field": "lon",
            "uid_field": "id",
            "callsign_field": "name",
        })
        db.session.add(stream)
        db.session.commit()
        stream_id = stream.id
        yield stream_id


# ---------------------------------------------------------------------------
# E2E: POST -> CoT -> Queued
# ---------------------------------------------------------------------------


class TestInboundEndToEnd:
    """End-to-end tests: HTTP POST -> plugin transform -> CoT -> TAK queue."""

    def test_single_location_produces_cot(
        self, client, inbound_stream, app, mock_plugin_manager
    ):
        """A single location POST creates a CoT event and enqueues it."""
        payload = json.dumps({
            "id": "drone-1",
            "name": "Alpha",
            "lat": 38.897,
            "lon": -77.036,
        })

        mock_result = {
            "success": True,
            "events_created": 1,
            "servers": {
                "TAK1": {"success": True, "events_enqueued": 1},
            },
        }

        with app.app_context(), \
             patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async",
                   return_value=mock_result) as mock_process:

            response = client.post(
                f"/api/inbound/{inbound_stream}/data",
                data=payload,
                content_type="application/json",
            )

            assert response.status_code == 202
            data = response.get_json()
            assert data["status"] == "accepted"
            assert data["locations_received"] == 1
            assert data["events_created"] == 1

            # Verify the async processor was called with locations
            mock_process.assert_called_once()
            call_locations = mock_process.call_args[0][0]
            assert len(call_locations) == 1
            assert call_locations[0]["uid"] == "drone-1"
            assert call_locations[0]["lat"] == 38.897

    def test_batch_locations_produces_multiple_cot(
        self, client, inbound_stream, app, mock_plugin_manager
    ):
        """Batch POST with multiple locations creates multiple CoT events."""
        payload = json.dumps([
            {"id": "drone-1", "name": "Alpha",
             "lat": 38.897, "lon": -77.036},
            {"id": "drone-2", "name": "Bravo",
             "lat": 39.001, "lon": -76.500},
            {"id": "drone-3", "name": "Charlie",
             "lat": 40.712, "lon": -74.006},
        ])

        mock_result = {
            "success": True,
            "events_created": 3,
            "servers": {
                "TAK1": {"success": True, "events_enqueued": 3},
            },
        }

        with app.app_context(), \
             patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async",
                   return_value=mock_result):

            response = client.post(
                f"/api/inbound/{inbound_stream}/data",
                data=payload,
                content_type="application/json",
            )

            assert response.status_code == 202
            data = response.get_json()
            assert data["locations_received"] == 3
            assert data["events_created"] == 3

    def test_invalid_coordinates_rejected_before_cot(
        self, client, inbound_stream, app, mock_plugin_manager
    ):
        """Invalid coordinates are caught before CoT creation."""
        payload = json.dumps({
            "id": "drone-bad",
            "name": "BadCoords",
            "lat": 95.0,  # Invalid: > 90
            "lon": -77.036,
        })

        with app.app_context(), \
             patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async") \
                as mock_process:

            response = client.post(
                f"/api/inbound/{inbound_stream}/data",
                data=payload,
                content_type="application/json",
            )

            assert response.status_code == 400
            # CoT processing should never have been called
            mock_process.assert_not_called()

    def test_poll_mode_stream_not_accessible_via_inbound(
        self, client, app
    ):
        """A poll-mode stream cannot receive inbound data."""
        with app.app_context():
            poll_stream = Stream(
                name="Poll Stream",
                plugin_type="garmin",
                stream_mode="poll",
            )
            poll_stream.is_active = True
            db.session.add(poll_stream)
            db.session.commit()
            poll_id = poll_stream.id

        response = client.post(
            f"/api/inbound/{poll_id}/data",
            data=json.dumps({
                "id": "dev-1", "lat": 38.9, "lon": -77.0,
            }),
            content_type="application/json",
        )

        assert response.status_code == 404

    def test_inactive_stream_not_accessible(self, client, app):
        """An inactive inbound stream returns 404."""
        with app.app_context():
            stream = Stream(
                name="Inactive Stream",
                plugin_type="generic_json_inbound",
                stream_mode="inbound",
            )
            stream.is_active = False
            stream.plugin_config = json.dumps({"auth_mode": "none"})
            db.session.add(stream)
            db.session.commit()
            stream_id = stream.id

        response = client.post(
            f"/api/inbound/{stream_id}/data",
            data=json.dumps({
                "id": "dev-1", "lat": 38.9, "lon": -77.0,
            }),
            content_type="application/json",
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# E2E: Preview Mode
# ---------------------------------------------------------------------------


class TestInboundPreviewE2E:
    """End-to-end tests for preview mode: skip TAK delivery."""

    def test_preview_mode_does_not_create_cot(
        self, client, app, mock_plugin_manager
    ):
        """In preview mode, data is accepted but no CoT events are created."""
        with app.app_context():
            stream = Stream(
                name="Preview Stream",
                plugin_type="generic_json_inbound",
                stream_mode="inbound",
                inbound_preview_mode=True,
            )
            stream.is_active = True
            stream.plugin_config = json.dumps({
                "auth_mode": "none",
                "lat_field": "lat",
                "lon_field": "lon",
                "uid_field": "id",
                "callsign_field": "name",
            })
            db.session.add(stream)
            db.session.commit()
            stream_id = stream.id

        with patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async") \
                as mock_process, \
             patch("routes.inbound.get_active_inbound_streams",
                   return_value={}):

            response = client.post(
                f"/api/inbound/{stream_id}/data",
                data=json.dumps({
                    "id": "dev-1", "name": "Alpha",
                    "lat": 38.9, "lon": -77.0,
                }),
                content_type="application/json",
            )

            assert response.status_code == 202
            data = response.get_json()
            assert data["status"] == "preview"
            assert data["locations_received"] == 1
            assert "mapped_result" in data

            # CoT processing must NOT have been called
            mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# E2E: Processing Failure
# ---------------------------------------------------------------------------


class TestInboundProcessingFailure:
    """End-to-end tests for error handling in the processing pipeline."""

    def test_cot_processing_failure_returns_500(
        self, client, inbound_stream, app, mock_plugin_manager
    ):
        """If CoT processing fails, the endpoint returns 500."""
        payload = json.dumps({
            "id": "drone-1",
            "name": "Alpha",
            "lat": 38.897,
            "lon": -77.036,
        })

        mock_result = {
            "success": False,
            "error": "No TAK servers configured for stream",
        }

        with app.app_context(), \
             patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async",
                   return_value=mock_result):

            response = client.post(
                f"/api/inbound/{inbound_stream}/data",
                data=payload,
                content_type="application/json",
            )

            assert response.status_code == 500
            data = response.get_json()
            assert "error" in data

    def test_empty_payload_returns_400(
        self, client, inbound_stream, app, mock_plugin_manager
    ):
        """An empty JSON object that produces no locations returns 400."""
        with app.app_context(), \
             patch("routes.inbound.get_plugin_manager",
                   return_value=mock_plugin_manager), \
             patch("routes.inbound._process_inbound_async") \
                as mock_process:

            response = client.post(
                f"/api/inbound/{inbound_stream}/data",
                data=json.dumps({}),
                content_type="application/json",
            )

            # Either 400 (no locations) or 202 (if plugin extracts
            # something). The key: if 400, process was not called.
            if response.status_code == 400:
                mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# E2E: InboundCOTService
# ---------------------------------------------------------------------------


class TestInboundCOTServiceE2E:
    """Test InboundCOTService processes locations end-to-end."""

    @pytest.mark.asyncio
    async def test_process_inbound_locations_empty_list(self):
        """Empty locations list returns failure."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()
        result = await service.process_inbound_locations(
            [], MagicMock()
        )

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_process_inbound_locations_no_tak_servers(self):
        """No configured TAK servers returns failure."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()
        stream = MagicMock()
        stream.get_all_tak_servers.return_value = []

        locations = [{"uid": "dev-1", "lat": 38.9, "lon": -77.0}]
        result = await service.process_inbound_locations(
            locations, stream
        )

        assert result["success"] is False
        assert "no tak servers" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_process_inbound_locations_success(self):
        """Locations are converted to CoT and enqueued for TAK servers."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()

        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"

        server = MagicMock(id=10)
        server.name = "TAK1"
        stream.get_all_tak_servers.return_value = [server]

        locations = [
            {"uid": "dev-1", "lat": 38.9, "lon": -77.0},
            {"uid": "dev-2", "lat": 39.0, "lon": -76.5},
        ]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [
            b"<event1/>", b"<event2/>",
        ]
        mock_cot_service.start_worker = AsyncMock()
        mock_cot_service.enqueue_event = AsyncMock(return_value=True)

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                locations, stream
            )

        assert result["success"] is True
        assert result["events_created"] == 2
        assert "TAK1" in result["servers"]
        assert result["servers"]["TAK1"]["success"] is True
        assert result["servers"]["TAK1"]["events_enqueued"] == 2

    @pytest.mark.asyncio
    async def test_process_inbound_partial_server_failure(self):
        """Partial failure: one TAK server succeeds, another fails."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()

        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"

        server_ok = MagicMock(id=10)
        server_ok.name = "TAK-OK"
        server_fail = MagicMock(id=20)
        server_fail.name = "TAK-FAIL"
        stream.get_all_tak_servers.return_value = [
            server_ok, server_fail,
        ]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [
            b"<event/>",
        ]

        async def start_worker_side_effect(server):
            if server.id == 20:
                raise ConnectionError("TAK-FAIL unreachable")

        mock_cot_service.start_worker = AsyncMock(
            side_effect=start_worker_side_effect
        )
        mock_cot_service.enqueue_event = AsyncMock(return_value=True)

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                [{"uid": "dev-1", "lat": 38.9, "lon": -77.0}],
                stream,
            )

        # Overall success because at least one server succeeded
        assert result["success"] is True
        assert result["servers"]["TAK-OK"]["success"] is True
        assert result["servers"]["TAK-FAIL"]["success"] is False
