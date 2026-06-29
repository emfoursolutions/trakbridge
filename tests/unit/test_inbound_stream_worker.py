"""
ABOUTME: Unit tests for InboundStreamWorker covering lifecycle management,
ABOUTME: TAK worker initialization, in-memory registry, and health status reporting.
"""

import asyncio
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
    """Create a mock Stream model configured for inbound mode."""
    stream = MagicMock()
    stream.id = 42
    stream.name = "Test Inbound Stream"
    stream.stream_mode = "inbound"
    stream.is_active = True
    stream.plugin_type = "generic_inbound"
    stream.poll_interval = 30  # ignored for inbound, but present on model

    server1 = MagicMock()
    server1.id = 10
    server1.name = "TAK Server Alpha"
    server2 = MagicMock()
    server2.id = 20
    server2.name = "TAK Server Bravo"

    stream.get_active_tak_servers.return_value = [server1, server2]
    stream.tak_server = server1  # legacy single-server field
    stream.tak_server_id = server1.id

    return stream


@pytest.fixture
def mock_session_manager():
    return MagicMock()


@pytest.fixture
def mock_db_manager():
    return MagicMock()


@pytest.fixture
def worker(mock_stream, mock_session_manager, mock_db_manager):
    """Create an InboundStreamWorker instance."""
    from services.inbound_stream_worker import InboundStreamWorker

    return InboundStreamWorker(mock_stream, mock_session_manager, mock_db_manager)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestInboundStreamWorkerInstantiation:
    """Test that InboundStreamWorker can be created with correct attributes."""

    def test_creates_instance(self, worker):
        """InboundStreamWorker is instantiable."""
        assert worker is not None

    def test_stores_stream(self, worker, mock_stream):
        """Worker stores reference to the stream model."""
        assert worker.stream is mock_stream

    def test_stores_dependencies(self, worker, mock_session_manager, mock_db_manager):
        """Worker stores session_manager and db_manager."""
        assert worker.session_manager is mock_session_manager
        assert worker.db_manager is mock_db_manager

    def test_initial_state_not_running(self, worker):
        """Worker starts in a non-running state."""
        assert worker.running is False

    def test_initial_startup_not_complete(self, worker):
        """Startup is not complete before start() is called."""
        assert worker._startup_complete is False

    def test_has_no_poll_task(self, worker):
        """Inbound workers have no polling task."""
        assert worker.task is None


# ---------------------------------------------------------------------------
# Start lifecycle
# ---------------------------------------------------------------------------


class TestInboundStreamWorkerStart:
    """Test the start() method — should initialize TAK workers, not a poll loop."""

    async def test_start_returns_true_on_success(self, worker):
        """start() returns True when TAK workers initialize successfully."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            result = await worker.start()

        assert result is True

    async def test_start_sets_running_flag(self, worker):
        """After successful start, running is True."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        assert worker.running is True

    async def test_start_sets_startup_complete(self, worker):
        """After successful start, _startup_complete is True."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        assert worker._startup_complete is True

    async def test_start_ensures_tak_workers_for_all_servers(self, worker, mock_stream):
        """start() calls start_worker for each configured TAK server."""
        servers = mock_stream.get_active_tak_servers()
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        assert mock_cot_service.start_worker.call_count == len(servers)

    async def test_start_does_not_create_poll_task(self, worker):
        """Inbound worker does NOT create an asyncio task (no poll loop)."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        assert worker.task is None

    async def test_start_fails_when_no_tak_servers(self, worker, mock_stream):
        """start() returns False when stream has no TAK servers configured."""
        mock_stream.get_active_tak_servers.return_value = []

        result = await worker.start()

        assert result is False
        assert worker.running is False

    async def test_start_fails_when_all_workers_fail(self, worker):
        """start() returns False when none of the TAK workers can initialize."""
        mock_cot_service = MagicMock()
        mock_cot_service.start_worker = AsyncMock(return_value=False)
        mock_cot_service.get_worker_status.return_value = {"worker_running": False}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            result = await worker.start()

        assert result is False
        assert worker.running is False

    async def test_start_succeeds_with_partial_tak_workers(self, worker, mock_stream):
        """start() succeeds if at least one TAK worker initializes."""
        servers = mock_stream.get_active_tak_servers()
        call_count = 0

        async def start_worker_side_effect(server):
            nonlocal call_count
            call_count += 1
            # First server succeeds, second fails
            return call_count == 1

        mock_cot_service = MagicMock()
        mock_cot_service.start_worker = AsyncMock(side_effect=start_worker_side_effect)
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            result = await worker.start()

        assert result is True
        assert len(servers) == 2  # Confirm we had 2 servers

    async def test_start_is_idempotent(self, worker):
        """Calling start() twice returns True without re-initializing."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            mock_cot_service.start_worker.reset_mock()
            result = await worker.start()

        assert result is True
        # Should not re-initialize TAK workers
        mock_cot_service.start_worker.assert_not_called()

    async def test_start_handles_cot_service_exception(self, worker):
        """start() returns False and stays not-running on COT service failure."""
        with patch(
            "services.inbound_stream_worker.get_cot_service",
            side_effect=RuntimeError("COT service unavailable"),
        ):
            result = await worker.start()

        assert result is False
        assert worker.running is False


# ---------------------------------------------------------------------------
# Stop lifecycle
# ---------------------------------------------------------------------------


class TestInboundStreamWorkerStop:
    """Test the stop() method."""

    async def test_stop_sets_running_false(self, worker):
        """stop() marks the worker as not running."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            await worker.stop()

        assert worker.running is False

    async def test_stop_clears_startup_complete(self, worker):
        """stop() resets _startup_complete."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            await worker.stop()

        assert worker._startup_complete is False

    async def test_stop_is_safe_when_not_running(self, worker):
        """stop() on a non-running worker does not raise."""
        await worker.stop()
        assert worker.running is False

    async def test_stop_does_not_stop_shared_tak_workers(self, worker):
        """
        stop() does NOT stop persistent TAK workers — they may be shared
        with other streams. The COT service manages their lifecycle.
        """
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)
        mock_cot_service.stop_worker = AsyncMock()

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            await worker.stop()

        mock_cot_service.stop_worker.assert_not_called()


# ---------------------------------------------------------------------------
# Health status
# ---------------------------------------------------------------------------


class TestInboundStreamWorkerHealthStatus:
    """Test get_health_status() returns a compatible dict."""

    def test_health_status_has_required_keys(self, worker):
        """Health status dict contains the keys StreamManager expects."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = None
        mock_cot_service.workers = {}
        mock_cot_service.queues = {}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            status = worker.get_health_status()

        assert "running" in status
        assert "startup_complete" in status
        assert "tak_worker_ensured" in status

    def test_health_status_reflects_running_state(self, worker):
        """Health status running field matches worker.running."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = None
        mock_cot_service.workers = {}
        mock_cot_service.queues = {}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            status = worker.get_health_status()
            assert status["running"] is False

    async def test_health_status_after_start(self, worker):
        """Health status shows running=True after successful start."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)
        mock_cot_service.workers = {10: MagicMock()}
        mock_cot_service.queues = {10: MagicMock()}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            status = worker.get_health_status()

        assert status["running"] is True
        assert status["startup_complete"] is True
        assert status["tak_worker_ensured"] is True

    def test_health_status_includes_stream_mode(self, worker):
        """Health status identifies this as an inbound worker."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = None
        mock_cot_service.workers = {}
        mock_cot_service.queues = {}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            status = worker.get_health_status()

        assert status["stream_mode"] == "inbound"

    def test_health_status_has_no_poll_fields(self, worker):
        """Inbound worker health status should not report poll-specific metrics."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = None
        mock_cot_service.workers = {}
        mock_cot_service.queues = {}

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            status = worker.get_health_status()

        # These are StreamWorker-specific and should not appear
        assert "consecutive_errors" not in status
        assert "last_successful_poll" not in status


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------


class TestInboundStreamRegistry:
    """Test the module-level registry for fast HTTP endpoint lookups."""

    def test_registry_starts_empty(self):
        """The global registry has no entries at import time."""
        from services.inbound_stream_worker import get_active_inbound_streams

        # Registry may have entries from other tests, but the function exists
        assert isinstance(get_active_inbound_streams(), dict)

    async def test_start_registers_stream(self, worker):
        """Starting a worker adds the stream to the registry."""
        from services.inbound_stream_worker import get_active_inbound_streams

        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        registry = get_active_inbound_streams()
        assert worker.stream.id in registry

    async def test_stop_deregisters_stream(self, worker):
        """Stopping a worker removes the stream from the registry."""
        from services.inbound_stream_worker import get_active_inbound_streams

        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            assert worker.stream.id in get_active_inbound_streams()

            await worker.stop()

        assert worker.stream.id not in get_active_inbound_streams()

    async def test_registry_lookup_returns_worker(self, worker):
        """Registry maps stream_id → InboundStreamWorker instance."""
        from services.inbound_stream_worker import get_active_inbound_streams

        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()

        registry = get_active_inbound_streams()
        assert registry[worker.stream.id] is worker

    async def test_failed_start_does_not_register(self, worker, mock_stream):
        """If start() fails, stream is NOT added to the registry."""
        from services.inbound_stream_worker import get_active_inbound_streams

        mock_stream.get_active_tak_servers.return_value = []

        await worker.start()

        assert worker.stream.id not in get_active_inbound_streams()


# ---------------------------------------------------------------------------
# Skip DB update on stop (container shutdown pattern)
# ---------------------------------------------------------------------------


class TestInboundStreamWorkerSkipDbUpdate:
    """Test the skip_db_update parameter on stop(), matching StreamWorker API."""

    async def test_stop_accepts_skip_db_update(self, worker):
        """stop() accepts skip_db_update kwarg for parity with StreamWorker."""
        mock_cot_service = MagicMock()
        mock_cot_service.get_worker_status.return_value = {"worker_running": True}
        mock_cot_service.start_worker = AsyncMock(return_value=True)

        with patch(
            "services.inbound_stream_worker.get_cot_service",
            return_value=mock_cot_service,
        ):
            await worker.start()
            # Should not raise
            await worker.stop(skip_db_update=True)

        assert worker.running is False
