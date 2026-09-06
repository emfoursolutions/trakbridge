# ABOUTME: Regression tests for T4.3 — the Garmin, Discord and Slack
# ABOUTME: plugins must not retry credential-bearing requests with SSL off.
"""T4.3 — no insecure SSL fallback.

The threat model called out that on ``ssl.SSLError`` the three
credential-bearing plugins were retrying the *same* request with
``ssl=False``, re-sending credentials or webhook payloads. Delete
the fallbacks; assert that the failure propagates and no second
network call is made.
"""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _async_cm(enter_side_effect=None, enter_return=None):
    """Build an object usable as `async with foo(...) as bar`."""
    cm = MagicMock()
    if enter_side_effect is not None:
        cm.__aenter__ = AsyncMock(side_effect=enter_side_effect)
    else:
        cm.__aenter__ = AsyncMock(return_value=enter_return)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Garmin — SSLError must propagate, no ssl=False retry
# ---------------------------------------------------------------------------


class TestGarminNoSSLFallback:
    """Garmin plugin must not retry with SSL off."""

    @pytest.mark.asyncio
    async def test_ssl_error_does_not_trigger_insecure_retry(self):
        """On SSLError, Garmin must not issue a second request with ssl=False."""
        from plugins.garmin_plugin import GarminPlugin

        plugin = GarminPlugin(config={
            "url": "https://share.garmin.com/feed/",
            "username": "user",
            "password": "pw",
        })

        session = MagicMock()
        session.get = MagicMock(
            return_value=_async_cm(enter_side_effect=ssl.SSLError("bad cert"))
        )

        with patch("plugins.garmin_plugin.asyncio.sleep", new=AsyncMock()):
            result = await plugin._fetch_kml_feed(
                session,
                {
                    "url": "https://share.garmin.com/feed/",
                    "username": "user",
                    "password": "pw",
                    "retry_delay": 0,
                },
            )

        # The retry loop tries up to 3 times, each strictly with the
        # secure ssl_context — no attempt uses ssl=False.
        for call in session.get.call_args_list:
            assert call.kwargs.get("ssl") is not False, (
                f"Garmin issued a request with ssl=False: {call}"
            )

        # After 3 SSL errors the feed returns None (failure), it
        # does not somehow succeed via the removed fallback path.
        assert result is None


# ---------------------------------------------------------------------------
# Discord — SSLError must propagate, no ssl=False retry
# ---------------------------------------------------------------------------


class TestDiscordNoSSLFallback:
    """Discord webhook must not retry with SSL off."""

    @pytest.mark.asyncio
    async def test_ssl_error_does_not_trigger_insecure_retry(self):
        """On SSLError, Discord webhook post must not retry with ssl=False."""
        from plugins.discord_handler import DiscordHandler

        handler = DiscordHandler(config={
            "webhook_url": "https://discord.com/api/webhooks/x/y",
        })

        # Patch the decrypting accessor so we don't need real crypto set up.
        with patch.object(
            handler,
            "get_decrypted_config",
            return_value={"webhook_url": "https://discord.com/api/webhooks/x/y"},
        ):
            inner_session = MagicMock()
            inner_session.post = MagicMock(
                return_value=_async_cm(
                    enter_side_effect=ssl.SSLError("bad cert")
                )
            )
            session_cm = _async_cm(enter_return=inner_session)

            with patch(
                "plugins.discord_handler.aiohttp.ClientSession",
                return_value=session_cm,
            ):
                # send_to_discord must not raise (SSLError is caught
                # and logged) but MUST NOT retry.
                await handler._send_to_discord(text="test")

        # Exactly one POST attempted (the secure one). The removed
        # fallback opened a second ClientSession and re-posted.
        assert inner_session.post.call_count == 1, (
            f"Discord retried after SSLError: "
            f"{inner_session.post.call_args_list}"
        )
        # Whatever it posted did not use ssl=False.
        call_kwargs = inner_session.post.call_args.kwargs
        assert call_kwargs.get("ssl") is not False


# ---------------------------------------------------------------------------
# Slack — SSLError must propagate, no ssl=False retry
# ---------------------------------------------------------------------------


class TestSlackNoSSLFallback:
    """Slack webhook must not retry with SSL off."""

    @pytest.mark.asyncio
    async def test_ssl_error_does_not_trigger_insecure_retry(self):
        """On SSLError, Slack webhook post must not retry with ssl=False."""
        from plugins.slack_handler import SlackHandler

        handler = SlackHandler(config={
            "webhook_url": "https://hooks.slack.com/services/x/y/z",
        })

        with patch.object(
            handler,
            "get_decrypted_config",
            return_value={
                "webhook_url": "https://hooks.slack.com/services/x/y/z"
            },
        ):
            inner_session = MagicMock()
            inner_session.post = MagicMock(
                return_value=_async_cm(
                    enter_side_effect=ssl.SSLError("bad cert")
                )
            )
            session_cm = _async_cm(enter_return=inner_session)

            with patch(
                "plugins.slack_handler.aiohttp.ClientSession",
                return_value=session_cm,
            ):
                await handler._send_to_slack(text="test")

        assert inner_session.post.call_count == 1, (
            f"Slack retried after SSLError: "
            f"{inner_session.post.call_args_list}"
        )
        call_kwargs = inner_session.post.call_args.kwargs
        assert call_kwargs.get("ssl") is not False


# ---------------------------------------------------------------------------
# Source-level assertion — the ssl=False literal must not appear at all
# ---------------------------------------------------------------------------


class TestNoInsecureSSLInSource:
    """Belt-and-braces: the string ``ssl=False`` must not appear in
    any of the three plugin files. If it does, someone reintroduced
    the fallback."""

    @pytest.mark.parametrize("module_path", [
        "plugins/garmin_plugin.py",
        "plugins/discord_handler.py",
        "plugins/slack_handler.py",
    ])
    def test_no_ssl_false_literal(self, module_path):
        from pathlib import Path
        source = Path(module_path).read_text()
        assert "ssl=False" not in source, (
            f"{module_path} still contains ssl=False — T4.3 fallback "
            f"has been reintroduced. See threat model T4.3."
        )
