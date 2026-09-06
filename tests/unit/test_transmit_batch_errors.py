"""
ABOUTME: Unit tests for _transmit_batch's error-propagation contract.
ABOUTME: Socket errors must raise (not return False) so the TX loop reconnects.
"""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService

EVENT_BYTES = b'<event uid="ANDROID-64293d86bd018739"/>'


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
    return server


def _make_writer(drain_error=None):
    writer = MagicMock()
    if drain_error is not None:
        writer.drain = AsyncMock(side_effect=drain_error)
    else:
        writer.drain = AsyncMock()
    return writer


class TestTransmitBatchSocketErrors:
    """Dead-socket errors must propagate so _tx_loop breaks and reconnects."""

    @pytest.mark.parametrize(
        "error",
        [
            ConnectionResetError("peer reset"),
            OSError("socket gone"),
            ssl.SSLError("tls torn down"),
        ],
    )
    async def test_transmit_batch_raises_socket_error(self, error):
        service = _make_service()
        tak_server = _make_tak_server()
        writer = _make_writer(drain_error=error)

        with pytest.raises(type(error)):
            await service._transmit_batch([EVENT_BYTES], (None, writer), tak_server)


class TestTransmitBatchLogicalOutcomes:
    """Non-socket outcomes keep the bool contract."""

    async def test_transmit_batch_returns_false_on_non_socket_failure(self):
        service = _make_service()
        tak_server = _make_tak_server()
        # Connection that is neither a (reader, writer) tuple nor has send():
        # the logical-failure path, not a socket death.
        connection = object()

        result = await service._transmit_batch([EVENT_BYTES], connection, tak_server)

        assert result is False

    async def test_transmit_batch_returns_true_on_success(self):
        service = _make_service()
        tak_server = _make_tak_server()
        writer = _make_writer()

        with patch.object(service, "_get_tak_circuit_breaker") as breaker_factory:
            result = await service._transmit_batch(
                [EVENT_BYTES], (None, writer), tak_server
            )

        assert result is True
        writer.write.assert_called_once_with(EVENT_BYTES)
        # The breaker must be off the write path entirely: transmission
        # failures are signalled by exceptions, connections are what the
        # breaker gates.
        breaker_factory.assert_not_called()

    async def test_transmit_batch_empty_batch_returns_true(self):
        service = _make_service()
        tak_server = _make_tak_server()

        result = await service._transmit_batch([], (None, None), tak_server)

        assert result is True
