# ABOUTME: Regression tests for T7.4 — /health/recovery must surface real
# ABOUTME: circuit-breaker state, not the orphaned recovery singleton.
"""T7.4 — recovery subsystem was orphaned; expose CB state instead.

``services/recovery_service.py`` and
``services/recovery_implementations.py`` were introduced alongside
the circuit breaker in commit 45ddcfc. The circuit breaker took
over the recovery role in practice (see commits f76542e, 83fbee6,
366c9b1, 6308239). The recovery service was never wired up:
``initialize_recovery_system()`` has no callers, no recovery
methods are registered, so the ``/health/recovery`` endpoint was
publishing "healthy" derived from a singleton that never ran.

Delete the recovery subsystem. Rework ``/health/recovery`` to
report per-service circuit-breaker state. Overall status maps:

- any OPEN  → ``unhealthy`` (HTTP 503)
- any HALF_OPEN → ``degraded`` (HTTP 200)
- all CLOSED → ``healthy``  (HTTP 200)
- no breakers registered → ``healthy`` (HTTP 200)
"""

from unittest.mock import patch


class TestHealthRecoveryReportsCircuitBreakerState:
    """/health/recovery must derive its payload from the CB manager."""

    def test_all_closed_reports_healthy(
        self, authenticated_client, app
    ):
        """When every breaker is CLOSED, endpoint returns healthy/200."""
        client = authenticated_client("admin")
        cb_status = {
            "tak-server-1": {
                "state": "closed",
                "failure_count": 0,
                "last_failure_time": None,
            },
            "tak-server-2": {
                "state": "closed",
                "failure_count": 0,
                "last_failure_time": None,
            },
        }

        with patch(
            "routes.api.get_circuit_breaker_manager"
        ) as mock_mgr:
            mock_mgr.return_value.get_all_status.return_value = cb_status
            response = client.get("/api/health/recovery")

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "healthy"
        assert "circuit_breakers" in body
        assert set(body["circuit_breakers"].keys()) == {
            "tak-server-1",
            "tak-server-2",
        }

    def test_any_open_reports_unhealthy_503(
        self, authenticated_client, app
    ):
        """A single OPEN breaker flips the whole endpoint to unhealthy/503."""
        client = authenticated_client("admin")
        cb_status = {
            "tak-server-1": {
                "state": "closed",
                "failure_count": 0,
                "last_failure_time": None,
            },
            "tak-server-2": {
                "state": "open",
                "failure_count": 5,
                "last_failure_time": "2026-09-04T10:00:00+00:00",
            },
        }

        with patch(
            "routes.api.get_circuit_breaker_manager"
        ) as mock_mgr:
            mock_mgr.return_value.get_all_status.return_value = cb_status
            response = client.get("/api/health/recovery")

        assert response.status_code == 503
        body = response.get_json()
        assert body["status"] == "unhealthy"
        assert body["circuit_breakers"]["tak-server-2"]["state"] == "open"

    def test_half_open_reports_degraded_200(
        self, authenticated_client, app
    ):
        """HALF_OPEN is a recovery-in-progress signal, not a failure."""
        client = authenticated_client("admin")
        cb_status = {
            "tak-server-1": {
                "state": "half_open",
                "failure_count": 3,
                "last_failure_time": "2026-09-04T10:00:00+00:00",
            },
        }

        with patch(
            "routes.api.get_circuit_breaker_manager"
        ) as mock_mgr:
            mock_mgr.return_value.get_all_status.return_value = cb_status
            response = client.get("/api/health/recovery")

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "degraded"

    def test_no_breakers_reports_healthy(
        self, authenticated_client, app
    ):
        """Empty CB registry is healthy (nothing to worry about yet)."""
        client = authenticated_client("admin")

        with patch(
            "routes.api.get_circuit_breaker_manager"
        ) as mock_mgr:
            mock_mgr.return_value.get_all_status.return_value = {}
            response = client.get("/api/health/recovery")

        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "healthy"
        assert body["circuit_breakers"] == {}


class TestRecoveryServiceModulesDeleted:
    """The orphaned modules must not be present in the tree."""

    def test_recovery_service_module_removed(self):
        from pathlib import Path
        assert not Path("services/recovery_service.py").exists(), (
            "services/recovery_service.py still present — T7.4 requires "
            "deletion. The circuit breaker superseded this subsystem."
        )

    def test_recovery_implementations_module_removed(self):
        from pathlib import Path
        assert not Path("services/recovery_implementations.py").exists(), (
            "services/recovery_implementations.py still present — T7.4 "
            "requires deletion. The circuit breaker superseded this "
            "subsystem."
        )
