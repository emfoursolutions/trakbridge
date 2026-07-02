"""
ABOUTME: Unit tests for QueuedCOTService.stop_worker writer-close behaviour.
ABOUTME: Editing a TAK server triggers restart_worker → stop_worker; the old
ABOUTME: StreamWriter must be explicitly closed or TAK Server holds the old
ABOUTME: subscription open, leading to duplicate identity heartbeats.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_cot_service()
    yield
    reset_cot_service()


def _make_service():
    with (
        patch("services.cot_service_integration.get_queue_manager") as qm,
        patch("services.cot_service_integration.get_queue_monitoring_service"),
    ):
        qm.return_value = MagicMock()
        qm.return_value.remove_queue = AsyncMock()
        svc = QueuedCOTService(_bypass_singleton_check=True)
        return svc


def _make_writer():
    """A writer whose close()/wait_closed() can be inspected by the test."""
    writer = MagicMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


class TestStopWorkerClosesWriter:
    """
    stop_worker must explicitly close the StreamWriter for the TAK server
    being stopped. Dropping the dict entry without closing the socket leaks
    the connection until TAK Server's stale-timeout (~60s) reaps it.
    """

    async def test_stop_worker_closes_writer_in_connections(self):
        svc = _make_service()
        writer = _make_writer()
        reader = MagicMock()
        svc.connections[1] = (reader, writer)

        await svc.stop_worker(1)

        # Writer.close() must be called and wait_closed() awaited so the
        # TCP FIN actually reaches TAK Server before stop_worker returns.
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        # Connection entry removed
        assert 1 not in svc.connections

    async def test_stop_worker_with_no_connection_is_noop(self):
        svc = _make_service()
        # No connection registered for server id 99
        await svc.stop_worker(99)
        # Just verifies it doesn't raise; no writer to inspect.

    async def test_stop_worker_tolerates_writer_close_failure(self):
        """A broken writer must not block teardown of the rest of the worker."""
        svc = _make_service()
        writer = _make_writer()
        writer.close.side_effect = OSError("already closed")
        svc.connections[1] = (None, writer)

        # Must complete cleanly even when close() raises
        await svc.stop_worker(1)

        assert 1 not in svc.connections

    async def test_stop_worker_cancels_task_before_closing_writer(self):
        """
        Order matters: the TX loop task must be cancelled before we yank
        the writer out from under it, otherwise the loop's in-flight
        writer.drain() will raise on the now-closed transport. We verify
        the invariant by checking the task is already done at the moment
        writer.close() runs.
        """
        svc = _make_service()
        writer = _make_writer()
        svc.connections[1] = (None, writer)

        async def slow_task():
            await asyncio.sleep(60)

        task = asyncio.create_task(slow_task())
        svc.workers[1] = task

        task_state_at_close = {}

        def record_close():
            task_state_at_close["done_at_close"] = task.done()
            task_state_at_close["cancelled_at_close"] = task.cancelled()

        writer.close.side_effect = record_close

        await svc.stop_worker(1)

        # When writer.close() ran, the worker task must already have been
        # cancelled and fully done.
        assert task_state_at_close.get("done_at_close") is True
        assert task_state_at_close.get("cancelled_at_close") is True


class TestRestartWorkerNoLeak:
    """
    Restart workflow integration: after restart_worker, no stale writer
    must remain unclosed in the previous connection slot.
    """

    async def test_restart_closes_old_writer_before_new_connection(self):
        """
        Regression for the 'two subscriptions on TAK Server after edit'
        bug: when restart_worker runs stop_worker, the *specific* writer
        we had before must be closed.
        """
        svc = _make_service()
        old_writer = _make_writer()
        svc.connections[1] = (None, old_writer)

        await svc.stop_worker(1)

        # The pre-restart writer is closed. We don't exercise the
        # subsequent "create new connection" half of restart_worker here
        # because it pulls in TakServer / db.session machinery; the
        # invariant we care about is the close.
        old_writer.close.assert_called_once()
        old_writer.wait_closed.assert_awaited_once()
