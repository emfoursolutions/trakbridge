"""
ABOUTME: Integration test proving the TAK worker + circuit breaker recover
ABOUTME: from a server outage with zero manual intervention (real sockets).
"""

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
)
from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService
from services.queue_manager import reset_queue_manager

pytestmark = pytest.mark.integration

EVENT = b'<event uid="ANDROID-integration-test"/>'

# Captured before patching: the worker's backoff sleeps are fast-forwarded by
# patching asyncio.sleep on the shared module, so the test's own waits must
# use the real one.
_real_sleep = asyncio.sleep


async def _wait_until(cond, timeout=15.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await _real_sleep(interval)
    return False


async def _scaled_sleep(delay, *args, **kwargs):
    """Worker reconnect backoff (5-120s literals) scaled down for CI."""
    await _real_sleep(min(delay, 0.05))


class FakeTakServer:
    """A real asyncio TCP endpoint that accepts and drains connections.

    Outage mode aborts live connections (RST) and stops listening. A true
    kernel-buffer black-hole (writes succeed into the buffer forever) is not
    CI-reproducible; abort exercises the same recovery code path — TX loop
    break -> worker reconnect -> breaker-gated connection attempts.
    """

    def __init__(self):
        self.server = None
        self.port = None
        self.received = bytearray()
        self._writers = []

    async def start(self, port=0):
        self.server = await asyncio.start_server(
            self._handle, "127.0.0.1", port or self.port or 0
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        self._writers.append(writer)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                self.received.extend(data)
        except Exception:
            pass

    async def stop(self):
        for w in self._writers:
            try:
                w.transport.abort()
            except Exception:
                pass
        self._writers.clear()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_cot_service()
    reset_queue_manager()
    yield
    reset_cot_service()
    reset_queue_manager()


def _make_tak_server(port):
    server = Mock()
    server.id = 1
    server.name = "FakeTAK"
    server.host = "127.0.0.1"
    server.port = port
    server.protocol = "tcp"
    server.enable_rx = False
    server.identity_enabled = False
    return server


def _make_breaker(fake: FakeTakServer):
    config = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout=0.2,
        half_open_max_calls=3,
        success_threshold=2,
        timeout=5.0,
        health_check_interval=0.1,
        health_check_timeout=1.0,
        jitter_enabled=False,
    )
    breaker = CircuitBreaker("tak_server_1", config)

    async def probe():
        # Socket-level probe of the fake server. The production
        # _tak_health_check needs a Flask app context + DB row, which this
        # test intentionally avoids; the health-loop mechanics themselves
        # are unit-tested in test_circuit_breaker.py.
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", fake.port)
            writer.close()
            await writer.wait_closed()
            return True
        except OSError:
            return False

    breaker.set_health_check(probe)
    return breaker


class TestTakOutageRecovery:

    async def test_worker_reconnects_and_breaker_closes_after_outage(self):
        fake = FakeTakServer()
        await fake.start()
        service = QueuedCOTService(_bypass_singleton_check=True)
        service._running = True
        tak_server = _make_tak_server(fake.port)
        breaker = _make_breaker(fake)
        reset_spy = AsyncMock(wraps=breaker.manual_reset)
        breaker.manual_reset = reset_spy

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch("services.cot_service_integration.asyncio.sleep", _scaled_sleep),
        ):
            try:
                assert await service.start_worker(tak_server)

                # Healthy: an enqueued event reaches the server.
                await service.enqueue_event(EVENT, tak_server.id)
                assert await _wait_until(lambda: EVENT in fake.received), (
                    "event never arrived at the healthy fake TAK server"
                )

                # Outage: abort connections and stop listening.
                await fake.stop()

                # Push events until the dead socket is noticed and reconnect
                # attempts trip the breaker.
                async def _feed():
                    while breaker.state != CircuitBreakerState.OPEN:
                        await service.enqueue_event(EVENT, tak_server.id)
                        await _real_sleep(0.05)

                feed_task = asyncio.create_task(_feed())
                opened = await _wait_until(
                    lambda: breaker.state == CircuitBreakerState.OPEN
                )
                feed_task.cancel()
                try:
                    await feed_task
                except asyncio.CancelledError:
                    pass
                assert opened, "breaker never opened during the outage"

                # Recovery: server comes back. NO manual reset anywhere.
                fake.received.clear()
                await fake.start(port=tak_server.port)

                closed = await _wait_until(
                    lambda: breaker.state == CircuitBreakerState.CLOSED
                )
                assert closed, (
                    f"breaker never closed after the server returned "
                    f"(state={breaker.state.value})"
                )

                await service.enqueue_event(EVENT, tak_server.id)
                assert await _wait_until(lambda: EVENT in fake.received), (
                    "worker did not deliver events after recovery"
                )

                reset_spy.assert_not_awaited()
            finally:
                await service.stop_worker(tak_server.id)
                await breaker.cleanup()
                await fake.stop()

    async def test_breaker_gates_reconnect_attempts_while_open(self):
        service = QueuedCOTService(_bypass_singleton_check=True)
        service._running = True
        tak_server = _make_tak_server(59999)  # nothing listening
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=3600.0,  # stay OPEN for the whole test
            timeout=5.0,
            jitter_enabled=False,
        )
        breaker = CircuitBreaker("tak_server_1", config)
        factory = AsyncMock(side_effect=ConnectionRefusedError("down"))

        sleep_count = {"n": 0}

        async def counting_sleep(delay, *args, **kwargs):
            if delay >= 1:
                sleep_count["n"] += 1
            await _real_sleep(0.01)

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch("services.cot_service_integration.pytak.protocol_factory", factory),
            patch(
                "services.cot_service_integration.asyncio.sleep", counting_sleep
            ),
        ):
            try:
                assert await service.start_worker(tak_server)
                # Let the worker iterate well past the failure threshold.
                assert await _wait_until(lambda: sleep_count["n"] >= 8)

                assert breaker.state == CircuitBreakerState.OPEN
                assert factory.await_count == config.failure_threshold, (
                    f"breaker did not gate connection attempts: "
                    f"{factory.await_count} network hits, expected "
                    f"{config.failure_threshold}"
                )
            finally:
                await service.stop_worker(tak_server.id)
                await breaker.cleanup()
