"""
ABOUTME: Unit tests for the TX loop's identity-on-connect invariant.
ABOUTME: Identity heartbeat must be the first byte sent on every new socket.
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
    """Minimal queue manager stand-in: returns a primed batch then stays empty."""

    def __init__(self, primed_batch):
        self._batches = [primed_batch]

    async def get_batch(self, tak_server_id):
        if self._batches:
            return self._batches.pop(0)
        # Hold until cancelled so the TX loop doesn't busy-spin.
        await asyncio.sleep(3600)
        return []

    def get_queue_status(self, tak_server_id):
        return {"size": 0}


class TestIdentitySentBeforeQueueDrain:
    """The identity heartbeat MUST be the first write on a new socket."""

    async def test_first_write_on_new_socket_is_identity_heartbeat(self):
        service = _make_service()
        service.queue_manager = _PrimedQueueManager([BRIDGED_BYTES])

        # Stub transmit_batch so it just records the writer interaction.
        async def fake_transmit(batch, connection, tak_server):
            _, writer = connection
            for event in batch:
                writer.write(event)
                await writer.drain()
            return True

        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            patch.object(service, "_transmit_batch", side_effect=fake_transmit),
        ):
            task = asyncio.create_task(
                service._tx_loop(tak_server.id, writer, tak_server)
            )

            # Yield long enough for the loop to do its connect-time write +
            # one queue drain. The fixture's get_batch sleeps after the
            # primed batch so the loop will park.
            for _ in range(50):
                await asyncio.sleep(0.005)
                if writer.write.call_count >= 2:
                    break

            task.cancel()
            await task  # _tx_loop catches CancelledError and breaks

        # The invariant: write[0] is the identity heartbeat, NOT a bridged event.
        assert writer.write.call_count >= 1, "TX loop sent nothing"
        first_payload = writer.write.call_args_list[0].args[0]
        assert first_payload == IDENTITY_BYTES, (
            f"First write was {first_payload!r}, expected identity heartbeat. "
            "TX loop is draining the queue before sending identity, which "
            "causes TAK Server to stamp the subscription with the wrong UID."
        )

    async def test_identity_send_failure_breaks_loop_before_queue_drain(self):
        """If identity write fails, the queue must NOT be drained on this socket."""
        service = _make_service()
        service.queue_manager = _PrimedQueueManager([BRIDGED_BYTES])

        async def failing_drain():
            raise ConnectionResetError("Connection lost")

        writer = MagicMock()
        writer.drain = AsyncMock(side_effect=failing_drain)
        tak_server = _make_tak_server()

        transmit_called = False

        async def fake_transmit(batch, connection, tak_server):
            nonlocal transmit_called
            transmit_called = True
            return True

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            patch.object(service, "_transmit_batch", side_effect=fake_transmit),
        ):
            task = asyncio.create_task(
                service._tx_loop(tak_server.id, writer, tak_server)
            )
            # Loop should exit on its own once identity write raises.
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                pytest.fail("TX loop did not exit after identity write failure")

        # Identity was attempted, queue was NOT drained on this dead socket.
        assert writer.write.call_count == 1
        assert writer.write.call_args_list[0].args[0] == IDENTITY_BYTES
        assert transmit_called is False, (
            "Queue was drained on a socket whose identity write failed — "
            "the bridged event will hit the next reconnect's fresh socket first."
        )

    async def test_identity_disabled_still_drains_queue(self):
        """If identity is disabled (no callsign), queue draining still works."""
        service = _make_service()
        service.queue_manager = _PrimedQueueManager([BRIDGED_BYTES])

        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()
        tak_server.identity_enabled = False
        tak_server.identity_callsign = None

        async def fake_transmit(batch, connection, tak_server):
            _, w = connection
            for event in batch:
                w.write(event)
                await w.drain()
            return True

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=None,
            ),
            patch.object(service, "_transmit_batch", side_effect=fake_transmit),
        ):
            task = asyncio.create_task(
                service._tx_loop(tak_server.id, writer, tak_server)
            )
            for _ in range(50):
                await asyncio.sleep(0.005)
                if writer.write.call_count >= 1:
                    break
            task.cancel()
            await task  # _tx_loop catches CancelledError and breaks

        # No identity sent, bridged event went through.
        assert writer.write.call_count >= 1
        assert writer.write.call_args_list[0].args[0] == BRIDGED_BYTES


class TestIdentityLogLevels:
    """Connect-time identity is INFO; recurring heartbeat is DEBUG."""

    async def test_connect_time_identity_logs_at_info(self, caplog):
        service = _make_service()
        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            caplog.at_level("INFO", logger="services.cot_service_integration"),
        ):
            await service._send_identity_heartbeat(writer, tak_server, "identity")

        info_lines = [r for r in caplog.records if r.levelname == "INFO"]
        assert any("TX identity -> Taknet" in r.message for r in info_lines), (
            f"Expected INFO 'TX identity -> Taknet' line, got: "
            f"{[r.message for r in info_lines]}"
        )

    async def test_periodic_heartbeat_logs_at_debug_not_info(self, caplog):
        service = _make_service()
        writer = MagicMock()
        writer.drain = AsyncMock()
        tak_server = _make_tak_server()

        with (
            patch.object(
                QueuedCOTService,
                "_generate_trakbridge_identity_cot",
                return_value=IDENTITY_BYTES,
            ),
            caplog.at_level("DEBUG", logger="services.cot_service_integration"),
        ):
            await service._send_identity_heartbeat(writer, tak_server, "heartbeat")

        info_heartbeat = [
            r
            for r in caplog.records
            if r.levelname == "INFO" and "TX heartbeat ->" in r.message
        ]
        assert not info_heartbeat, (
            f"Recurring heartbeat must not log at INFO; got: "
            f"{[r.message for r in info_heartbeat]}"
        )
        debug_heartbeat = [
            r
            for r in caplog.records
            if r.levelname == "DEBUG" and "TX heartbeat ->" in r.message
        ]
        assert debug_heartbeat, "Expected at least one DEBUG 'TX heartbeat ->' line"
