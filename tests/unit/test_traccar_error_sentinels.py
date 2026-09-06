"""
ABOUTME: Unit tests for the Traccar plugin's connection-failure reporting:
ABOUTME: exception branches must return _error sentinels, not empty lists.
"""

import asyncio
import json
from unittest.mock import MagicMock

import aiohttp
import pytest

from plugins.traccar_plugin import TraccarPlugin

CONFIG = {
    "server_url": "https://traccar.example.com",
    "username": "u",
    "password": "p",
    "timeout": 5,
}


def _session_raising(error):
    session = MagicMock()
    session.get = MagicMock(side_effect=error)
    return session


class TestTraccarErrorSentinels:
    """An outage must be reported the same way as an HTTP error status:
    a sentinel the stream worker can recognise — an empty list is
    indistinguishable from a legitimately quiet feed."""

    @pytest.mark.parametrize(
        "error, expected_code",
        [
            (aiohttp.ClientConnectionError("unreachable"), "connection_failed"),
            (asyncio.TimeoutError(), "timeout"),
            (json.JSONDecodeError("bad", "doc", 0), "json_error"),
            (RuntimeError("surprise"), "unknown"),
        ],
    )
    async def test_exception_branches_return_sentinels(self, error, expected_code):
        session = _session_raising(error)

        result = await TraccarPlugin._fetch_positions_from_api(session, CONFIG)

        assert result, "outage must not be reported as an empty (quiet) feed"
        assert result[0].get("_error") == expected_code, (
            f"expected sentinel {expected_code!r}, got {result[0]!r}"
        )
        assert "_error_message" in result[0]
