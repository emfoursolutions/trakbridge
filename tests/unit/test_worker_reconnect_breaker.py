"""
ABOUTME: Unit tests for circuit breaker reset ownership in the TAK worker
ABOUTME: lifecycle: no per-iteration reset; stop/start resets preserved.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_cot_service()
    yield
    reset_cot_service()


@pytest.fixture
def service():
    with (
        patch("services.cot_service_integration.get_queue_manager"),
        patch("services.cot_service_integration.get_queue_monitoring_service"),
    ):
        svc = QueuedCOTService(_bypass_singleton_check=True)
        svc._running = True
        return svc


def _make_tak_server(server_id=1, name="Test", enable_rx=False):
    server = Mock()
    server.id = server_id
    server.name = name
    server.enable_rx = enable_rx
    return server


def _make_breaker_mock():
    breaker = MagicMock()
    breaker.manual_reset = AsyncMock()
    return breaker


class TestNoPerIterationReset:
    """
    The worker loop must NOT force the breaker CLOSED before every connection
    attempt — that neuters the breaker on the only path that can prove
    recovery (a fresh connection). Resets belong to operator actions
    (stop_worker / start_worker dead-worker cleanup) only.
    """

    async def test_worker_does_not_reset_breaker_per_iteration(self, service):
        tak_server = _make_tak_server()
        breaker = _make_breaker_mock()
        connection = (Mock(), Mock())

        tx_started = asyncio.Event()

        async def hanging_tx(sid, writer, ts):
            tx_started.set()
            await asyncio.sleep(3600)

        with (
            patch.object(service, "_create_pytak_connection", return_value=connection),
            patch.object(service, "_tx_loop", side_effect=hanging_tx),
            patch.object(service, "_cleanup_connection", new_callable=AsyncMock),
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server.id, tak_server)
            )
            await asyncio.wait_for(tx_started.wait(), timeout=1.0)
            task.cancel()
            await task

        breaker.manual_reset.assert_not_awaited()

    async def test_worker_backs_off_when_connection_none(self, service):
        """With the reset gone, the existing backoff still paces retries."""
        tak_server = _make_tak_server()
        breaker = _make_breaker_mock()

        real_sleep = asyncio.sleep
        delays = []
        two_backoffs = asyncio.Event()

        async def fake_sleep(delay, *args, **kwargs):
            if delay >= 1:
                delays.append(delay)
                if len(delays) >= 2:
                    two_backoffs.set()
            await real_sleep(0)

        with (
            patch.object(service, "_create_pytak_connection", return_value=None),
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch("services.cot_service_integration.asyncio.sleep", fake_sleep),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server.id, tak_server)
            )
            await asyncio.wait_for(two_backoffs.wait(), timeout=1.0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert delays[:2] == [
            5,
            10,
        ], f"Expected exponential backoff 5s then 10s, got {delays[:2]}"
        breaker.manual_reset.assert_not_awaited()


class TestOperatorResetsPreserved:
    """Stream-edit recovery (commit 9b4af2e) must keep working."""

    async def test_stop_worker_still_resets_breaker(self, service):
        breaker = _make_breaker_mock()
        service.queue_manager.remove_queue = AsyncMock()

        with patch.object(service, "_get_tak_circuit_breaker", return_value=breaker):
            await service.stop_worker(1)

        breaker.manual_reset.assert_awaited_once()

    async def test_start_worker_dead_worker_cleanup_still_resets(self, service):
        tak_server = _make_tak_server()
        breaker = _make_breaker_mock()
        service.queue_manager.create_queue = AsyncMock(return_value=True)

        # Seed a dead worker so start_worker takes the cleanup path.
        async def _noop():
            return None

        dead_task = asyncio.create_task(_noop())
        await dead_task
        service.workers[tak_server.id] = dead_task

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch.object(
                service,
                "_enhanced_transmission_worker",
                new=AsyncMock(),
            ),
        ):
            result = await service.start_worker(tak_server)
            # Let the spawned (mocked) worker task settle, then clean up.
            new_task = service.workers.get(tak_server.id)
            if new_task:
                await new_task

        assert result is True
        breaker.manual_reset.assert_awaited_once()
