"""
ABOUTME: Integration test proving a stream survives an extended plugin/TAK
ABOUTME: outage in the database: is_active stays True and the stream resumes.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from models.stream import Stream
from plugins.base_plugin import BaseGPSPlugin
from services.database_manager import DatabaseManager
from services.stream_worker import StreamWorker

pytestmark = pytest.mark.integration

_real_wait_for = asyncio.wait_for


class TestStreamRetryResilience:

    def test_stream_survives_extended_failure_and_resumes(self, app, db_session):
        with app.app_context():
            stream_row = Stream(
                name="Resilience Test Stream",
                plugin_type="garmin",
                poll_interval=1,
                is_active=True,
            )
            db_session.add(stream_row)
            db_session.commit()
            stream_id = stream_row.id

        db_manager = DatabaseManager(app_context_factory=app.app_context)

        stream = Mock()
        stream.id = stream_id
        stream.name = "Resilience Test Stream"
        stream.plugin_type = "garmin"
        stream.poll_interval = 0.001
        stream.enable_callsign_mapping = False

        worker = StreamWorker(stream, Mock(), db_manager)
        worker.plugin = Mock(spec=BaseGPSPlugin)
        worker.running = True
        worker._stop_event = asyncio.Event()
        worker._tak_worker_ensured = False
        worker._apply_callsign_mapping = AsyncMock()

        fetch_calls = {"n": 0}

        async def fetch(session):
            fetch_calls["n"] += 1
            if fetch_calls["n"] <= 7:
                raise RuntimeError("plugin outage")
            worker.running = False
            return [{"lat": 1.0, "lon": 2.0, "name": "t1", "uid": "t-1"}]

        worker.plugin.fetch_locations_with_protection = fetch

        async def _drive():
            # Fast-forward the retry backoff sleeps; everything else real.
            async def fake_wait_for(awaitable, timeout=None):
                if asyncio.iscoroutine(awaitable):
                    awaitable.close()
                raise asyncio.TimeoutError

            original = asyncio.wait_for
            asyncio.wait_for = fake_wait_for
            try:
                await _real_wait_for(worker._run_loop(), 30.0)
            finally:
                asyncio.wait_for = original

        asyncio.run(_drive())

        assert fetch_calls["n"] >= 8, "stream stopped polling during the outage"

        with app.app_context():
            row = db_session.get(Stream, stream_id)
            db_session.refresh(row)
            assert row.is_active is True, (
                "extended outage deactivated the stream in the database"
            )
