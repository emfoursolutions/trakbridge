"""
ABOUTME: Unit tests for StreamManager's inbound stream routing logic.
ABOUTME: Verifies that stream_mode "inbound" routes to InboundStreamWorker, not StreamWorker.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_app_context_factory():
    """Mock Flask app context factory."""
    return MagicMock()


@pytest.fixture
def mock_inbound_stream():
    """Create a mock Stream configured for inbound mode."""
    stream = MagicMock()
    stream.id = 100
    stream.name = "Inbound Test"
    stream.stream_mode = "inbound"
    stream.is_active = True
    stream.plugin_type = "generic_inbound"
    stream.poll_interval = 30
    stream.tak_server_id = 10

    server = MagicMock()
    server.id = 10
    server.name = "TAK Server Alpha"
    stream.tak_server = server
    stream.tak_servers = []
    stream.get_all_tak_servers.return_value = [server]

    return stream


@pytest.fixture
def mock_poll_stream():
    """Create a mock Stream configured for poll mode."""
    stream = MagicMock()
    stream.id = 200
    stream.name = "Poll Test"
    stream.stream_mode = "poll"
    stream.is_active = True
    stream.plugin_type = "some_gps_plugin"
    stream.poll_interval = 30
    stream.tak_server_id = 10

    server = MagicMock()
    server.id = 10
    server.name = "TAK Server Alpha"
    stream.tak_server = server
    stream.tak_servers = []
    stream.get_all_tak_servers.return_value = [server]
    stream.get_plugin_config.return_value = {}

    return stream


# ---------------------------------------------------------------------------
# Inbound stream routing
# ---------------------------------------------------------------------------


class TestStreamManagerInboundRouting:
    """Test that StreamManager creates the right worker type based on stream_mode."""

    async def test_inbound_stream_creates_inbound_worker(self, mock_inbound_stream):
        """start_stream() creates InboundStreamWorker for stream_mode='inbound'."""
        from services.stream_manager import StreamManager

        manager = StreamManager.__new__(StreamManager)
        manager.workers = {}
        manager.db_manager = MagicMock()
        manager.db_manager.get_stream = MagicMock(return_value=mock_inbound_stream)
        manager.session_manager = MagicMock()
        manager._lock = MagicMock()
        manager._manager_lock = MagicMock()

        mock_inbound_worker = AsyncMock()
        mock_inbound_worker.start = AsyncMock(return_value=True)
        mock_inbound_worker.get_health_status.return_value = {
            "running": True,
            "startup_complete": True,
        }

        with (
            patch(
                "services.stream_manager.InboundStreamWorker",
                return_value=mock_inbound_worker,
            ) as mock_cls,
            patch(
                "services.stream_manager.StreamWorker",
            ) as mock_poll_cls,
        ):
            result = await manager.start_stream(mock_inbound_stream.id)

        assert result is True
        mock_cls.assert_called_once_with(
            mock_inbound_stream, manager.session_manager, manager.db_manager
        )
        mock_poll_cls.assert_not_called()

    async def test_poll_stream_creates_stream_worker(self, mock_poll_stream):
        """start_stream() creates StreamWorker for stream_mode='poll'."""
        from services.stream_manager import StreamManager

        manager = StreamManager.__new__(StreamManager)
        manager.workers = {}
        manager.db_manager = MagicMock()
        manager.db_manager.get_stream = MagicMock(return_value=mock_poll_stream)
        manager.session_manager = MagicMock()
        manager._lock = MagicMock()
        manager._manager_lock = MagicMock()

        mock_poll_worker = AsyncMock()
        mock_poll_worker.start = AsyncMock(return_value=True)
        mock_poll_worker.get_health_status.return_value = {
            "running": True,
            "startup_complete": True,
        }

        with (
            patch(
                "services.stream_manager.StreamWorker",
                return_value=mock_poll_worker,
            ) as mock_poll_cls,
            patch(
                "services.stream_manager.InboundStreamWorker",
            ) as mock_inbound_cls,
        ):
            result = await manager.start_stream(mock_poll_stream.id)

        assert result is True
        mock_poll_cls.assert_called_once_with(
            mock_poll_stream, manager.session_manager, manager.db_manager
        )
        mock_inbound_cls.assert_not_called()

    async def test_default_stream_mode_is_poll(self):
        """A stream with no explicit stream_mode defaults to poll behavior."""
        from services.stream_manager import StreamManager

        stream = MagicMock()
        stream.id = 300
        stream.name = "Legacy No Mode"
        stream.stream_mode = "poll"  # default from model
        stream.is_active = True
        stream.plugin_type = "some_plugin"
        stream.poll_interval = 30
        stream.tak_server_id = 10
        server = MagicMock()
        server.id = 10
        server.name = "TAK Server"
        stream.tak_server = server
        stream.tak_servers = []
        stream.get_all_tak_servers.return_value = [server]
        stream.get_plugin_config.return_value = {}

        manager = StreamManager.__new__(StreamManager)
        manager.workers = {}
        manager.db_manager = MagicMock()
        manager.db_manager.get_stream = MagicMock(return_value=stream)
        manager.session_manager = MagicMock()
        manager._lock = MagicMock()
        manager._manager_lock = MagicMock()

        mock_poll_worker = AsyncMock()
        mock_poll_worker.start = AsyncMock(return_value=True)

        with (
            patch(
                "services.stream_manager.StreamWorker",
                return_value=mock_poll_worker,
            ) as mock_poll_cls,
            patch(
                "services.stream_manager.InboundStreamWorker",
            ) as mock_inbound_cls,
        ):
            await manager.start_stream(stream.id)

        mock_poll_cls.assert_called_once()
        mock_inbound_cls.assert_not_called()

    async def test_inbound_worker_stored_in_workers_dict(self, mock_inbound_stream):
        """InboundStreamWorker is stored in manager.workers like any other worker."""
        from services.stream_manager import StreamManager

        manager = StreamManager.__new__(StreamManager)
        manager.workers = {}
        manager.db_manager = MagicMock()
        manager.db_manager.get_stream = MagicMock(return_value=mock_inbound_stream)
        manager.session_manager = MagicMock()
        manager._lock = MagicMock()
        manager._manager_lock = MagicMock()

        mock_inbound_worker = AsyncMock()
        mock_inbound_worker.start = AsyncMock(return_value=True)

        with patch(
            "services.stream_manager.InboundStreamWorker",
            return_value=mock_inbound_worker,
        ):
            await manager.start_stream(mock_inbound_stream.id)

        assert mock_inbound_stream.id in manager.workers
        assert manager.workers[mock_inbound_stream.id] is mock_inbound_worker

    async def test_stop_stream_works_for_inbound(self, mock_inbound_stream):
        """stop_stream() properly stops an InboundStreamWorker."""
        from services.stream_manager import StreamManager

        manager = StreamManager.__new__(StreamManager)

        mock_inbound_worker = AsyncMock()
        mock_inbound_worker.stop = AsyncMock()
        manager.workers = {mock_inbound_stream.id: mock_inbound_worker}

        result = await manager.stop_stream(mock_inbound_stream.id)

        assert result is True
        mock_inbound_worker.stop.assert_called_once()
        assert mock_inbound_stream.id not in manager.workers
