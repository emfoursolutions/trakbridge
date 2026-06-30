"""
ABOUTME: Unit tests for StreamManager's stale worker reaping behaviour.
ABOUTME: stop_stream must clean the registry on failure; health check must
ABOUTME: reap workers belonging to inactive streams instead of warning forever.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def manager():
    """Construct a StreamManager with the DB and external bits mocked out."""
    from services.stream_manager import StreamManager

    with (
        patch("services.stream_manager.DatabaseManager") as db_mgr_cls,
        patch("services.stream_manager.SessionManager") as session_mgr_cls,
    ):
        db_mgr_cls.return_value = MagicMock()
        session_mgr_cls.return_value = MagicMock()
        mgr = StreamManager(app_context_factory=MagicMock())
        mgr._shutdown_event = asyncio.Event()
        mgr._loop = asyncio.get_event_loop()
        return mgr


def _healthy_worker():
    worker = MagicMock()
    worker.get_health_status = MagicMock(
        return_value={
            "running": True,
            "task_done": False,
            "task_cancelled": False,
            "consecutive_errors": 0,
        }
    )
    return worker


def _stalled_worker():
    """A worker that returns 'task_done=True' (Slack-style ghost)."""
    worker = MagicMock()
    worker.get_health_status = MagicMock(
        return_value={
            "running": True,
            "startup_complete": True,
            "consecutive_errors": 0,
            "last_successful_poll": None,
            "tak_worker_ensured": True,
            "task_done": True,
            "task_cancelled": False,
        }
    )
    return worker


# ---------------------------------------------------------------------------
# stop_stream registry-cleanup tests
# ---------------------------------------------------------------------------


class TestStopStreamRegistryCleanup:
    async def test_happy_path_removes_worker_from_registry(self, manager):
        worker = _healthy_worker()
        worker.stop = AsyncMock(return_value=None)
        manager.workers[42] = worker

        ok = await manager.stop_stream(42)

        assert ok is True
        assert 42 not in manager.workers

    async def test_worker_stop_raising_still_clears_registry(self, manager):
        worker = _healthy_worker()
        worker.stop = AsyncMock(side_effect=RuntimeError("boom"))
        manager.workers[42] = worker

        await manager.stop_stream(42)

        # Even when the worker.stop() raises, the registry must drop the
        # entry; otherwise the health check perpetually warns about a
        # half-stopped worker.
        assert 42 not in manager.workers

    async def test_worker_stop_timing_out_still_clears_registry(self, manager):
        worker = _healthy_worker()

        async def hang(skip_db_update=False):
            await asyncio.sleep(60)

        worker.stop = AsyncMock(side_effect=hang)
        manager.workers[42] = worker

        # Use a tight wait_for via patch so the test stays fast
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            await manager.stop_stream(42)

        assert 42 not in manager.workers


# ---------------------------------------------------------------------------
# health-check ghost-reaping tests
# ---------------------------------------------------------------------------


def _set_stream_active_state(manager, stream_id, *, exists, is_active):
    """Configure db_manager.get_stream to return an active/inactive stream."""

    def get_stream(sid):
        if sid == stream_id and exists:
            stream = MagicMock()
            stream.id = sid
            stream.is_active = is_active
            return stream
        return None

    manager.db_manager.get_stream.side_effect = get_stream


class TestHealthCheckReapsGhosts:
    async def test_ghost_worker_for_inactive_stream_is_reaped_not_warned(
        self, manager, caplog
    ):
        worker = _stalled_worker()
        manager.workers[2] = worker
        _set_stream_active_state(manager, 2, exists=True, is_active=False)

        with caplog.at_level("INFO", logger="services.stream_manager"):
            await manager._reap_or_warn_unhealthy()

        # Reaped, not warned
        assert 2 not in manager.workers
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warnings, (
            f"Ghost workers for inactive streams must not warn; got: "
            f"{[r.message for r in warnings]}"
        )

    async def test_ghost_worker_for_deleted_stream_is_reaped(self, manager):
        worker = _stalled_worker()
        manager.workers[99] = worker
        _set_stream_active_state(manager, 99, exists=False, is_active=False)

        await manager._reap_or_warn_unhealthy()

        assert 99 not in manager.workers

    async def test_unhealthy_worker_for_active_stream_still_warns(
        self, manager, caplog
    ):
        worker = _stalled_worker()
        manager.workers[3] = worker
        _set_stream_active_state(manager, 3, exists=True, is_active=True)

        with caplog.at_level("WARNING", logger="services.stream_manager"):
            await manager._reap_or_warn_unhealthy()

        # Real bug: a worker for an active stream went unhealthy.
        # Registry entry stays (so the operator can investigate),
        # warning fires.
        assert 3 in manager.workers
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("Worker 3 unhealthy" in r.message for r in warnings), (
            f"Expected unhealthy warning for active stream; got: "
            f"{[r.message for r in warnings]}"
        )

    async def test_healthy_workers_are_left_alone(self, manager, caplog):
        manager.workers[1] = _healthy_worker()
        manager.workers[2] = _healthy_worker()

        with caplog.at_level("WARNING", logger="services.stream_manager"):
            await manager._reap_or_warn_unhealthy()

        assert 1 in manager.workers
        assert 2 in manager.workers
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warnings
