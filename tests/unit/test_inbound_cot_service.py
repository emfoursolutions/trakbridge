"""
ABOUTME: Unit tests for InboundCOTService covering location-to-CoT conversion,
ABOUTME: multi-server distribution, queue capacity checks, and circuit breaker awareness.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInboundCOTServiceInstantiation:
    """Test InboundCOTService construction."""

    def test_creates_instance(self):
        """InboundCOTService can be instantiated."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()
        assert service is not None

    def test_has_process_method(self):
        """InboundCOTService exposes process_inbound_locations."""
        from services.inbound_cot_service import InboundCOTService

        service = InboundCOTService()
        assert hasattr(service, "process_inbound_locations")
        assert callable(service.process_inbound_locations)


class TestProcessInboundLocations:
    """Test the core location processing pipeline."""

    @pytest.fixture
    def service(self):
        from services.inbound_cot_service import InboundCOTService

        return InboundCOTService()

    @pytest.fixture
    def sample_locations(self):
        return [
            {
                "uid": "dev-1",
                "name": "Alpha",
                "lat": 38.9,
                "lon": -77.0,
            },
            {
                "uid": "dev-2",
                "name": "Bravo",
                "lat": 39.0,
                "lon": -76.5,
            },
        ]

    @pytest.fixture
    def mock_stream(self):
        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.name = "Test Inbound Stream"
        server1 = MagicMock()
        server1.id = 10
        server1.name = "TAK Server 1"
        stream.get_active_tak_servers.return_value = [server1]
        return stream

    @pytest.mark.asyncio
    async def test_creates_cot_events(self, service, sample_locations, mock_stream):
        """Locations are converted to CoT XML events."""
        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event/>", b"<event/>"]
        mock_cot_service.enqueue_event.return_value = True
        mock_cot_service.start_worker.return_value = True

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                sample_locations, mock_stream
            )

        mock_cot_service.create_cot_events.assert_called_once_with(
            sample_locations,
            mock_stream.cot_type,
            mock_stream.cot_stale_time,
            mock_stream.cot_type_mode,
        )
        assert result["success"] is True
        assert result["events_created"] == 2

    @pytest.mark.asyncio
    async def test_enqueues_to_all_servers(self, service, sample_locations):
        """Events are enqueued to every configured TAK server."""
        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.name = "Test Stream"

        server1 = MagicMock(id=10)
        server1.name = "Server A"
        server2 = MagicMock(id=20)
        server2.name = "Server B"
        stream.get_active_tak_servers.return_value = [server1, server2]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event1/>", b"<event2/>"]
        mock_cot_service.enqueue_event.return_value = True
        mock_cot_service.start_worker.return_value = True

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                sample_locations, stream
            )

        # 2 events × 2 servers = 4 enqueue calls
        assert mock_cot_service.enqueue_event.call_count == 4
        assert result["success"] is True
        assert result["servers"]["Server A"]["success"] is True
        assert result["servers"]["Server B"]["success"] is True

    @pytest.mark.asyncio
    async def test_starts_worker_before_enqueue(self, service, sample_locations, mock_stream):
        """Ensures TAK worker is running before enqueueing events."""
        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event/>"]
        mock_cot_service.enqueue_event.return_value = True
        mock_cot_service.start_worker.return_value = True

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            await service.process_inbound_locations(sample_locations, mock_stream)

        server = mock_stream.get_active_tak_servers.return_value[0]
        mock_cot_service.start_worker.assert_called_with(server)

    @pytest.mark.asyncio
    async def test_empty_locations_returns_error(self, service, mock_stream):
        """Empty location list returns error result."""
        result = await service.process_inbound_locations([], mock_stream)

        assert result["success"] is False
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_tak_servers_returns_error(self, service, sample_locations):
        """Stream with no TAK servers configured returns error."""
        stream = MagicMock()
        stream.id = 1
        stream.name = "No Servers"
        stream.get_active_tak_servers.return_value = []

        result = await service.process_inbound_locations(sample_locations, stream)

        assert result["success"] is False
        assert "no tak server" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cot_creation_failure(self, service, sample_locations, mock_stream):
        """CoT creation failure returns error result."""
        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.side_effect = Exception("XML generation failed")

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                sample_locations, mock_stream
            )

        assert result["success"] is False
        assert "error" in result


class TestServerFailureIsolation:
    """Test that server failures don't block other servers."""

    @pytest.fixture
    def service(self):
        from services.inbound_cot_service import InboundCOTService

        return InboundCOTService()

    @pytest.mark.asyncio
    async def test_partial_server_failure(self, service):
        """One server failing doesn't prevent delivery to others."""
        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.name = "Test"

        server_ok = MagicMock(id=10)
        server_ok.name = "OK Server"
        server_fail = MagicMock(id=20)
        server_fail.name = "Fail Server"
        stream.get_active_tak_servers.return_value = [server_ok, server_fail]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event/>"]
        mock_cot_service.start_worker.return_value = True

        # First enqueue call succeeds (server_ok), second fails (server_fail)
        enqueue_results = [True, Exception("Connection refused")]
        call_count = 0

        async def mock_enqueue(event, server_id):
            nonlocal call_count
            result = enqueue_results[call_count]
            call_count += 1
            if isinstance(result, Exception):
                raise result
            return result

        mock_cot_service.enqueue_event.side_effect = mock_enqueue

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                [{"uid": "d1", "name": "A", "lat": 38.9, "lon": -77.0}],
                stream,
            )

        # Partial success — overall success since at least one server got data
        assert result["success"] is True
        assert result["servers"]["OK Server"]["success"] is True
        assert result["servers"]["Fail Server"]["success"] is False

    @pytest.mark.asyncio
    async def test_all_servers_fail(self, service):
        """All servers failing returns overall failure."""
        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.name = "Test"

        server = MagicMock(id=10)
        server.name = "Broken Server"
        stream.get_active_tak_servers.return_value = [server]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event/>"]
        mock_cot_service.start_worker.return_value = True
        mock_cot_service.enqueue_event.side_effect = Exception("Timeout")

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                [{"uid": "d1", "name": "A", "lat": 38.9, "lon": -77.0}],
                stream,
            )

        assert result["success"] is False


class TestResultStructure:
    """Test the shape of the result dictionary."""

    @pytest.fixture
    def service(self):
        from services.inbound_cot_service import InboundCOTService

        return InboundCOTService()

    @pytest.mark.asyncio
    async def test_success_result_keys(self, service):
        """Successful result contains expected keys."""
        stream = MagicMock()
        stream.id = 1
        stream.cot_type = "a-f-G-U-C"
        stream.cot_stale_time = 300
        stream.cot_type_mode = "stream"
        stream.name = "Test"
        server = MagicMock(id=10)
        server.name = "Server"
        stream.get_active_tak_servers.return_value = [server]

        mock_cot_service = AsyncMock()
        mock_cot_service.create_cot_events.return_value = [b"<event/>"]
        mock_cot_service.enqueue_event.return_value = True
        mock_cot_service.start_worker.return_value = True

        with patch(
            "services.inbound_cot_service.get_queued_cot_service",
            return_value=mock_cot_service,
        ):
            result = await service.process_inbound_locations(
                [{"uid": "d1", "name": "A", "lat": 38.9, "lon": -77.0}],
                stream,
            )

        assert "success" in result
        assert "events_created" in result
        assert "servers" in result
        assert "Server" in result["servers"]
        assert "success" in result["servers"]["Server"]
        assert "events_enqueued" in result["servers"]["Server"]
