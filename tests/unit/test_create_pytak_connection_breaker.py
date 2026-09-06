"""
ABOUTME: Unit tests for _create_pytak_connection's circuit breaker contract.
ABOUTME: CircuitOpenError must return None quietly; failures/successes hit the breaker.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from services.cot_service import reset_cot_service
from services.cot_service_integration import QueuedCOTService


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
    server.host = "127.0.0.1"
    server.port = 8089
    server.protocol = "tcp"
    return server


def _make_breaker(failure_threshold=2):
    config = CircuitBreakerConfig(
        failure_threshold=failure_threshold,
        recovery_timeout=3600.0,
        jitter_enabled=False,
    )
    return CircuitBreaker("tak_server_test", config)


class TestCreatePytakConnectionBreaker:

    async def test_circuit_open_returns_none_quietly(self, caplog):
        service = _make_service()
        tak_server = _make_tak_server()
        breaker = _make_breaker()
        await breaker.force_open()

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            caplog.at_level(logging.DEBUG),
        ):
            caplog.clear()  # discard force_open's own state-transition log
            result = await service._create_pytak_connection(tak_server)

        assert result is None
        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
        assert any(
            "circuit" in m.lower() for m in warning_msgs
        ), f"Expected a circuit-open WARNING, got warnings={warning_msgs}"
        assert (
            not error_msgs
        ), f"Circuit-open is expected fast-fail behaviour, not an error: {error_msgs}"

    async def test_connect_failure_counts_toward_breaker(self):
        service = _make_service()
        tak_server = _make_tak_server()
        breaker = _make_breaker(failure_threshold=2)

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch.object(
                service, "_create_pytak_config", new=AsyncMock(return_value={})
            ),
            patch(
                "services.cot_service_integration.pytak.protocol_factory",
                new=AsyncMock(side_effect=ConnectionRefusedError("down")),
            ),
        ):
            first = await service._create_pytak_connection(tak_server)
            second = await service._create_pytak_connection(tak_server)

        assert first is None
        assert second is None
        assert breaker.get_status()["state"] == "open"

    async def test_successful_connection_records_breaker_success(self):
        service = _make_service()
        tak_server = _make_tak_server()
        breaker = _make_breaker()
        reader, writer = MagicMock(), MagicMock()

        with (
            patch.object(service, "_get_tak_circuit_breaker", return_value=breaker),
            patch.object(
                service, "_create_pytak_config", new=AsyncMock(return_value={})
            ),
            patch(
                "services.cot_service_integration.pytak.protocol_factory",
                new=AsyncMock(return_value=(reader, writer)),
            ),
        ):
            result = await service._create_pytak_connection(tak_server)

        assert result == (reader, writer)
        assert breaker.metrics.successful_calls == 1
