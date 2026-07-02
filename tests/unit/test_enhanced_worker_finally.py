"""
ABOUTME: Unit tests for _enhanced_transmission_worker's finally-block cleanup.
ABOUTME: The finally must close only the connection this iteration owned, not
ABOUTME: whatever's currently in self.connections — otherwise a config-edit
ABOUTME: restart's late cancellation can close the freshly-started worker's
ABOUTME: socket, tripping the circuit breaker on a healthy connection.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.cot_service_integration import QueuedCOTService
from services.cot_service import reset_cot_service


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


class TestFinallyClosesOwnConnection:
    """
    Regression: when a stream is saved and restarted, stop_all_workers_for_server
    cancels the old worker task. The task's `finally` block used to read the
    connection to close from self.connections[tak_server_id] at the moment
    finally ran. If the new worker had already replaced that entry with its
    own connection, the old task's finally closed the new socket — tripping
    the circuit breaker on a fresh healthy connection. Fix captures the
    per-iteration connection as a local and closes only that.
    """

    @pytest.mark.asyncio
    async def test_finally_does_not_close_replaced_connection(self, service):
        """
        Old worker's cleanup must not close a connection installed by a
        subsequently-started worker.

        We arrange for the TX loop to hang until we explicitly release it.
        That lets us swap the dict entry with a 'new' connection before the
        finally runs, mimicking a restart_worker sequence.
        """
        tak_server = _make_tak_server()
        tak_server_id = tak_server.id

        old_connection = (Mock(), Mock(name="old_writer"))
        new_connection = (Mock(), Mock(name="new_writer"))

        cleanups: list = []

        async def record_cleanup(conn):
            cleanups.append(conn)

        tx_can_exit = asyncio.Event()

        async def hanging_tx(sid, writer, ts):
            # Hang until the test decides to let it exit — this keeps the
            # worker inside its main try block, past the point where it
            # stored `old_connection` in self.connections.
            await tx_can_exit.wait()

        with (
            patch.object(
                service,
                "_create_pytak_connection",
                return_value=old_connection,
            ),
            patch.object(service, "_tx_loop", side_effect=hanging_tx),
            patch.object(service, "_cleanup_connection", side_effect=record_cleanup),
            patch.object(service, "_get_tak_circuit_breaker", return_value=None),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )

            # Wait for old worker to install its connection.
            for _ in range(50):
                await asyncio.sleep(0.005)
                if service.connections.get(tak_server_id) is old_connection:
                    break
            assert service.connections.get(tak_server_id) is old_connection

            # Simulate a fresh worker (from restart_worker) installing its
            # own connection under the same key.
            service.connections[tak_server_id] = new_connection

            # Now release the old worker: its main try block finishes and
            # the finally runs.
            tx_can_exit.set()

            # Cancel to exit the outer reconnect loop cleanly.
            await asyncio.sleep(0.05)
            task.cancel()
            await task

        assert (
            new_connection not in cleanups
        ), f"finally closed the new worker's connection: {cleanups}"
        assert (
            old_connection in cleanups
        ), f"finally never closed its own connection: {cleanups}"

    @pytest.mark.asyncio
    async def test_finally_leaves_dict_entry_when_replaced(self, service):
        """
        If the dict entry now points at a different (new) connection, the
        old worker's finally must NOT `del` it — that would leave the new
        worker orphaned from the connection registry.
        """
        tak_server = _make_tak_server()
        tak_server_id = tak_server.id

        old_connection = (Mock(), Mock(name="old_writer"))
        new_connection = (Mock(), Mock(name="new_writer"))

        tx_can_exit = asyncio.Event()

        async def hanging_tx(sid, writer, ts):
            await tx_can_exit.wait()

        with (
            patch.object(
                service,
                "_create_pytak_connection",
                return_value=old_connection,
            ),
            patch.object(service, "_tx_loop", side_effect=hanging_tx),
            patch.object(service, "_cleanup_connection", new_callable=AsyncMock),
            patch.object(service, "_get_tak_circuit_breaker", return_value=None),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )

            for _ in range(50):
                await asyncio.sleep(0.005)
                if service.connections.get(tak_server_id) is old_connection:
                    break

            service.connections[tak_server_id] = new_connection
            tx_can_exit.set()

            await asyncio.sleep(0.05)
            task.cancel()
            await task

        assert (
            service.connections.get(tak_server_id) is new_connection
        ), "finally cleared the dict entry belonging to a newer worker"

    @pytest.mark.asyncio
    async def test_finally_clears_dict_when_still_own_connection(self, service):
        """
        Baseline: when no replacement happened, finally must still clean up
        its own dict entry so a fresh restart doesn't see stale state.
        """
        tak_server = _make_tak_server()
        tak_server_id = tak_server.id

        connection = (Mock(), Mock())

        tx_can_exit = asyncio.Event()

        async def hanging_tx(sid, writer, ts):
            await tx_can_exit.wait()

        with (
            patch.object(service, "_create_pytak_connection", return_value=connection),
            patch.object(service, "_tx_loop", side_effect=hanging_tx),
            patch.object(service, "_cleanup_connection", new_callable=AsyncMock),
            patch.object(service, "_get_tak_circuit_breaker", return_value=None),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )

            for _ in range(50):
                await asyncio.sleep(0.005)
                if service.connections.get(tak_server_id) is connection:
                    break

            tx_can_exit.set()
            await asyncio.sleep(0.05)
            task.cancel()
            await task

        assert (
            tak_server_id not in service.connections
        ), "finally did not clear its own dict entry"


class TestOuterCancelStopsInnerTasks:
    """
    Regression: cancelling the outer _enhanced_transmission_worker task must
    also cancel its inner TX/RX child tasks. Previously the outer's
    `except asyncio.CancelledError: break` propagated up without touching the
    child tasks it had spawned into `tasks = [...]`. The orphaned _tx_loop
    kept calling queue_manager.get_batch() every 100ms (logging ERROR
    because the queue was gone), and its writes on the *old* writer racked
    up circuit-breaker failures charged against the shared tak_server_id
    even after the new worker was already running on a fresh connection.
    """

    @pytest.mark.asyncio
    async def test_outer_cancel_cancels_inner_tx_task(self, service):
        tak_server = _make_tak_server(enable_rx=False)
        tak_server_id = tak_server.id
        connection = (Mock(), Mock())

        tx_started = asyncio.Event()
        tx_cancelled = asyncio.Event()

        async def real_tx_loop(sid, writer, ts):
            tx_started.set()
            try:
                # Simulate a TX loop hanging on get_batch/sleep — the shape
                # of the real inner loop when the queue's been removed.
                while True:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                tx_cancelled.set()
                raise

        with (
            patch.object(service, "_create_pytak_connection", return_value=connection),
            patch.object(service, "_tx_loop", side_effect=real_tx_loop),
            patch.object(service, "_cleanup_connection", new_callable=AsyncMock),
            patch.object(service, "_get_tak_circuit_breaker", return_value=None),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )

            # Wait for the inner TX loop to be up.
            await asyncio.wait_for(tx_started.wait(), timeout=1.0)

            # Cancel the OUTER worker (equivalent of stop_worker's cancel).
            task.cancel()
            await task

            # The inner TX task must have been cancelled too, promptly.
            await asyncio.wait_for(tx_cancelled.wait(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_outer_cancel_cancels_inner_rx_task_when_enabled(self, service):
        tak_server = _make_tak_server(enable_rx=True)
        tak_server_id = tak_server.id
        connection = (Mock(), Mock())

        rx_started = asyncio.Event()
        rx_cancelled = asyncio.Event()

        async def real_tx_loop(sid, writer, ts):
            while True:
                await asyncio.sleep(0.05)

        async def real_rx_worker(sid, reader):
            rx_started.set()
            try:
                while True:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                rx_cancelled.set()
                raise

        with (
            patch.object(service, "_create_pytak_connection", return_value=connection),
            patch.object(service, "_tx_loop", side_effect=real_tx_loop),
            patch.object(service, "_rx_worker", side_effect=real_rx_worker),
            patch.object(service, "_cleanup_connection", new_callable=AsyncMock),
            patch.object(service, "_get_tak_circuit_breaker", return_value=None),
        ):
            task = asyncio.create_task(
                service._enhanced_transmission_worker(tak_server_id, tak_server)
            )
            await asyncio.wait_for(rx_started.wait(), timeout=1.0)

            task.cancel()
            await task

            await asyncio.wait_for(rx_cancelled.wait(), timeout=1.0)
