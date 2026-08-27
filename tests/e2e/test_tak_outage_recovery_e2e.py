"""
ABOUTME: End-to-end TAK outage/recovery lifecycle over real sockets, including
ABOUTME: the monitoring status surface operators watch during an outage.
"""

import asyncio
from unittest.mock import patch

import pytest

from services.circuit_breaker import CircuitBreakerState
from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService
from services.queue_manager import reset_queue_manager
from tests.integration.test_tak_outage_recovery import (
    EVENT,
    FakeTakServer,
    _make_breaker,
    _make_tak_server,
    _scaled_sleep,
    _wait_until,
)

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_cot_service()
    reset_queue_manager()
    yield
    reset_cot_service()
    reset_queue_manager()


class TestTakOutageRecoveryE2E:

    async def test_full_outage_lifecycle_with_status_surface(self):
        """Deliver -> outage -> auto-recover -> deliver, verifying the
        breaker status dict that /api/health/circuit_breaker serializes."""
        fake = FakeTakServer()
        await fake.start()
        service = QueuedCOTService(_bypass_singleton_check=True)
        service._running = True
        tak_server = _make_tak_server(fake.port)
        breaker = _make_breaker(fake)

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch("services.cot_service_integration.asyncio.sleep", _scaled_sleep),
        ):
            try:
                assert await service.start_worker(tak_server)
                await service.enqueue_event(EVENT, tak_server.id)
                assert await _wait_until(lambda: EVENT in fake.received)

                await fake.stop()

                async def _feed():
                    while breaker.state != CircuitBreakerState.OPEN:
                        await service.enqueue_event(EVENT, tak_server.id)
                        await asyncio.sleep(0.05)

                feed = asyncio.create_task(_feed())
                assert await _wait_until(
                    lambda: breaker.state == CircuitBreakerState.OPEN
                )
                feed.cancel()
                try:
                    await feed
                except asyncio.CancelledError:
                    pass

                # The status dict the monitoring endpoints serialize must
                # reflect the outage in the shape routes/api.py expects.
                status = breaker.get_status()
                assert status["state"] == "open"
                assert status["failure_count"] >= 1
                assert status["last_failure_time"] is not None

                fake.received.clear()
                await fake.start(port=tak_server.port)
                assert await _wait_until(
                    lambda: breaker.state == CircuitBreakerState.CLOSED
                )
                assert breaker.get_status()["state"] == "closed"

                await service.enqueue_event(EVENT, tak_server.id)
                assert await _wait_until(lambda: EVENT in fake.received)
            finally:
                await service.stop_worker(tak_server.id)
                await breaker.cleanup()
                await fake.stop()
