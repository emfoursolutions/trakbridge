"""
ABOUTME: Unit tests for the TX loop's reaction to _transmit_batch outcomes.
ABOUTME: Socket errors must break the loop (reconnect); logical False must not.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService

IDENTITY_BYTES = b'<event uid="trakbridge-Taknet-580260" how="h-e"/>'
BRIDGED_BYTES = b'<event uid="ANDROID-64293d86bd018739"/>'


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_cot_service()
    yield
    reset_cot_service()


def _make_service():
    with (
        patch("services.cot_service_integration.get_queue_manager"),
        patch("services.cot_service_integration.get_queue_monitoring_service"),
    ):
        return QueuedCOTService(_bypass_singleton_check=True)


def _make_tak_server(server_id=1, name="Taknet"):
    server = MagicMock()
    server.id = server_id
    server.name = name
    server.identity_enabled = True
    server.identity_callsign = "Emfour-HQ"
    return server


class _PrimedQueueManager:
    """Returns primed batches then parks; records any enqueue attempts."""

    def __init__(self, primed_batches):
        self._batches = list(primed_batches)
        self.enqueue_event = AsyncMock()
        self.enqueue_with_replacement = AsyncMock()

    async def get_batch(self, tak_server_id):
        if self._batches:
            return self._batches.pop(0)
        await asyncio.sleep(3600)
        return []

    def get_queue_status(self, tak_server_id):
        return {"size": 0}


class TestTxLoopSocketErrors:
    """Socket death during transmit must exit the loop so the worker reconnects."""

    async def test_tx_loop_exits_on_transmit_socket_error(self):
        service = _make_service()
        service.queue_manager = _PrimedQueueManager([[BRIDGED_BYTES]])
        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            patch.object(
                service,
                "_transmit_batch",
                side_effect=ConnectionResetError("peer reset"),
            ),
        ):
            # Must complete on its own (break), not park forever.
            await asyncio.wait_for(
                service._tx_loop(tak_server.id, writer, tak_server), timeout=2.0
            )

    async def test_tx_loop_continues_on_logical_false(self):
        service = _make_service()
        service.queue_manager = _PrimedQueueManager([[BRIDGED_BYTES]])
        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()
        transmit = AsyncMock(return_value=False)

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            patch.object(service, "_transmit_batch", transmit),
        ):
            task = asyncio.create_task(
                service._tx_loop(tak_server.id, writer, tak_server)
            )
            for _ in range(50):
                await asyncio.sleep(0.005)
                if transmit.await_count >= 1:
                    break
            # Loop must still be running (parked on the empty queue), not exited.
            assert not task.done(), (
                "TX loop exited on a logical False from _transmit_batch; "
                "only socket errors should break the loop"
            )
            task.cancel()
            await task

    async def test_tx_loop_event_loss_on_break_is_accepted(self):
        """Pins the approved decision: no re-queue of the in-flight batch."""
        service = _make_service()
        queue_manager = _PrimedQueueManager([[BRIDGED_BYTES]])
        service.queue_manager = queue_manager
        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            patch.object(
                service,
                "_transmit_batch",
                side_effect=ConnectionResetError("peer reset"),
            ),
        ):
            await asyncio.wait_for(
                service._tx_loop(tak_server.id, writer, tak_server), timeout=2.0
            )

        queue_manager.enqueue_event.assert_not_awaited()
        queue_manager.enqueue_with_replacement.assert_not_awaited()
