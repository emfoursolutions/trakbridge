# ABOUTME: Unit tests for the OutboundHTTP output plugin.
# ABOUTME: Covers metadata, config fields, pipeline, filtering, dedup, and error handling.

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Sample CoT XML used across tests
# ---------------------------------------------------------------------------

SAMPLE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-f-G-U-C" uid="ANDROID-device1"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="m-g">
  <point lat="38.897" lon="-77.036" hae="0" ce="10" le="10"/>
  <detail>
    <contact callsign="ALPHA-1" xmppUsername="alpha1@xmpp"/>
    <__group name="Cyan" role="Team Lead"/>
    <status battery="85"/>
    <takv device="Samsung" platform="Android" os="11" version="4.8.1"/>
    <track speed="5.2" course="180"/>
    <remarks>On patrol</remarks>
  </detail>
</event>"""

HOSTILE_COT_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" type="a-h-G" uid="hostile-1"
       time="2026-04-11T12:00:00Z" start="2026-04-11T12:00:00Z"
       stale="2026-04-11T12:05:00Z" how="h-e">
  <point lat="39.0" lon="-76.0" hae="100" ce="50" le="50"/>
  <detail>
    <contact callsign="HOSTILE-1"/>
  </detail>
</event>"""

# Minimal config that allows the friendly CoT event through
MINIMAL_CONFIG = {
    "endpoint_url": "https://example.com/hook",
    "message_rules": [
        {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": "{callsign}"},
    ],
}


def _make_plugin(config=None):
    from plugins.outbound_http import OutboundHTTP
    return OutboundHTTP(config or MINIMAL_CONFIG)


# ===========================================================================
# Metadata and registration
# ===========================================================================


class TestOutboundHTTPMetadata:
    """Verify plugin exposes correct metadata for auto-discovery."""

    def test_plugin_name(self):
        plugin = _make_plugin()
        assert plugin.plugin_name == "outbound_http"

    def test_plugin_category_is_output(self):
        plugin = _make_plugin()
        assert plugin.plugin_metadata["category"] == "output"

    def test_plugin_has_display_name(self):
        plugin = _make_plugin()
        meta = plugin.plugin_metadata
        assert "display_name" in meta
        assert meta["display_name"]

    def test_exactly_10_config_fields(self):
        plugin = _make_plugin()
        fields = plugin.plugin_metadata["config_fields"]
        assert len(fields) == 10, (
            f"Expected 10 config fields, got {len(fields)}: "
            f"{[f.name for f in fields]}"
        )

    def test_all_required_field_names_present(self):
        plugin = _make_plugin()
        field_names = {f.name for f in plugin.plugin_metadata["config_fields"]}
        expected = {
            "endpoint_url",
            "http_method",
            "output_format",
            "custom_template",
            "custom_headers",
            "timeout_seconds",
            "uid_filter",
            "include_raw_xml",
            "dedup_enabled",
            "dedup_ttl_seconds",
        }
        assert field_names == expected

    def test_endpoint_url_is_required(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["endpoint_url"].required is True

    def test_http_method_default_is_post(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["http_method"].default_value == "POST"

    def test_output_format_default_is_json(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["output_format"].default_value == "json"

    def test_timeout_default_is_10(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["timeout_seconds"].default_value == 10

    def test_timeout_min_1_max_60(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["timeout_seconds"].min_value == 1
        assert fields["timeout_seconds"].max_value == 60

    def test_dedup_enabled_default_true(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["dedup_enabled"].default_value == "true"

    def test_dedup_ttl_default_5(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["dedup_ttl_seconds"].default_value == 5

    def test_dedup_ttl_min_1_max_300(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        assert fields["dedup_ttl_seconds"].min_value == 1
        assert fields["dedup_ttl_seconds"].max_value == 300

    def test_custom_template_has_depends_on(self):
        plugin = _make_plugin()
        fields = {f.name: f for f in plugin.plugin_metadata["config_fields"]}
        field = fields["custom_template"]
        assert field.depends_on is not None
        # Condition must express "show when output_format == custom_template"
        assert field.depends_on.get("output_format") == "custom_template"

    def test_message_rules_is_custom_component(self):
        from plugins.base_plugin import PluginCustomComponent
        plugin = _make_plugin()
        components = plugin.plugin_metadata["custom_components"]
        component_types = {c.field_name: c for c in components}
        assert "message_rules" in component_types
        assert isinstance(component_types["message_rules"], PluginCustomComponent)

    def test_global_geofence_is_custom_component(self):
        from plugins.base_plugin import PluginCustomComponent
        plugin = _make_plugin()
        components = plugin.plugin_metadata["custom_components"]
        component_types = {c.field_name: c for c in components}
        assert "global_geofence" in component_types
        assert isinstance(component_types["global_geofence"], PluginCustomComponent)

    def test_inherits_base_output_plugin(self):
        from plugins.base_plugin import BaseOutputPlugin
        from plugins.outbound_http import OutboundHTTP
        assert issubclass(OutboundHTTP, BaseOutputPlugin)


# ===========================================================================
# handle_cot_message — happy paths
# ===========================================================================


class TestHandleCotMessageHappyPath:
    """Verify correct HTTP delivery under normal conditions."""

    def _make_mock_response(self, status=200):
        """Build a mock aiohttp response context manager."""
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    def _make_mock_session(self, status=200):
        """Build a mock aiohttp.ClientSession context manager."""
        mock_resp = self._make_mock_response(status)
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    @pytest.mark.asyncio
    async def test_post_json_calls_request_with_correct_method(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "http_method": "POST",
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        mock_session.request.assert_called_once()
        call_kwargs = mock_session.request.call_args
        assert call_kwargs[0][0].upper() == "POST"

    @pytest.mark.asyncio
    async def test_put_method_used_when_configured(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "http_method": "PUT",
            "output_format": "json",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        assert call_kwargs[0][0].upper() == "PUT"

    @pytest.mark.asyncio
    async def test_successful_post_increments_events_sent(self):
        plugin = _make_plugin()
        mock_session = self._make_mock_session(status=200)
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 1
        assert stats["events_dropped"] == 0

    @pytest.mark.asyncio
    async def test_xml_output_format_sends_bytes_with_correct_content_type(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "output_format": "xml",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        # headers should include application/xml
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("Content-Type") == "application/xml"
        # data kwarg should be bytes (raw XML passthrough)
        assert isinstance(call_kwargs[1].get("data"), bytes)

    @pytest.mark.asyncio
    async def test_custom_template_output_renders_and_sends_text(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "output_format": "custom_template",
            "custom_template": "ALERT: {callsign} at {lat},{lon}",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        data = call_kwargs[1].get("data", "")
        assert "ALPHA-1" in data
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("Content-Type") == "text/plain"

    @pytest.mark.asyncio
    async def test_include_raw_xml_true_adds_base64_field(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "output_format": "json",
            "include_raw_xml": "true",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        json_body = call_kwargs[1].get("json")
        assert json_body is not None
        assert "raw_xml" in json_body
        # Verify it decodes back to the original XML
        decoded = base64.b64decode(json_body["raw_xml"])
        assert decoded == SAMPLE_COT_XML

    @pytest.mark.asyncio
    async def test_json_payload_does_not_contain_tak_server_id(self):
        """tak_server_id must not leak into the outbound payload."""
        plugin = _make_plugin()
        mock_session = self._make_mock_session()
        captured = {}
        original_request = mock_session.request

        def capture_request(*args, **kwargs):
            captured["json"] = kwargs.get("json")
            return original_request(*args, **kwargs)

        mock_session.request = MagicMock(side_effect=capture_request,
                                         return_value=self._make_mock_response())
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=42)

        body = captured.get("json", {})
        body_str = json.dumps(body)
        assert "tak_server_id" not in body_str
        assert "tak_server_id" not in body

    @pytest.mark.asyncio
    async def test_custom_headers_are_sent_on_wire(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "custom_headers": "X-Api-Key: secret123\nAuthorization: Bearer mytoken",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        headers = call_kwargs[1].get("headers", {})
        assert headers.get("X-Api-Key") == "secret123"
        assert headers.get("Authorization") == "Bearer mytoken"

    @pytest.mark.asyncio
    async def test_endpoint_url_passed_correctly(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        call_kwargs = mock_session.request.call_args
        url_arg = call_kwargs[0][1]
        assert url_arg == "https://example.com/hook"


# ===========================================================================
# handle_cot_message — filtering
# ===========================================================================


class TestHandleCotMessageFiltering:
    """Verify that filter paths drop events and do not call the session."""

    def _make_mock_session(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    @pytest.mark.asyncio
    async def test_uid_filter_no_match_drops_event(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "uid_filter": "^DRONE-.*",  # won't match ANDROID-device1
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        mock_session.request.assert_not_called()
        assert plugin.get_health_stats()["events_dropped"] == 1

    @pytest.mark.asyncio
    async def test_geofence_outside_drops_event(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "global_geofence": {
                "enabled": True,
                "bounds": {"north": 10.0, "south": 0.0, "east": 10.0, "west": 0.0},
            },
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            # SAMPLE_COT_XML is at lat=38.897 — outside the 0–10 box
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        mock_session.request.assert_not_called()
        assert plugin.get_health_stats()["events_dropped"] == 1

    @pytest.mark.asyncio
    async def test_message_rules_no_match_drops_event(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "message_rules": [
                {"cot_type_pattern": "b-t-f", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        mock_session.request.assert_not_called()
        assert plugin.get_health_stats()["events_dropped"] == 1

    @pytest.mark.asyncio
    async def test_empty_message_rules_drops_event(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "message_rules": [],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
        mock_session.request.assert_not_called()
        assert plugin.get_health_stats()["events_dropped"] == 1


# ===========================================================================
# handle_cot_message — deduplication
# ===========================================================================


class TestHandleCotMessageDedup:
    """Verify deduplication suppresses duplicate events within the TTL window."""

    def _make_mock_session(self):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    @pytest.mark.asyncio
    async def test_duplicate_within_ttl_is_dropped(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "dedup_enabled": "true",
            "dedup_ttl_seconds": 60,
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        # Request should be called exactly once; second is a duplicate
        assert mock_session.request.call_count == 1
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 1
        assert stats["events_dropped"] == 1

    @pytest.mark.asyncio
    async def test_dedup_disabled_allows_duplicates(self):
        plugin = _make_plugin({
            "endpoint_url": "https://example.com/hook",
            "dedup_enabled": "false",
            "message_rules": [
                {"cot_type_pattern": "a-f-*", "enabled": True, "format_template": ""},
            ],
        })
        mock_session = self._make_mock_session()
        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        assert mock_session.request.call_count == 2
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 2
        assert stats["events_dropped"] == 0


# ===========================================================================
# handle_cot_message — error handling
# ===========================================================================


class TestHandleCotMessageErrors:
    """Verify that HTTP failures increment events_dropped without raising."""

    @pytest.mark.asyncio
    async def test_http_non_2xx_increments_dropped_sets_last_error(self):
        plugin = _make_plugin()
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            # Must not raise
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 1
        assert stats["last_error"] is not None

    @pytest.mark.asyncio
    async def test_http_exception_increments_dropped_no_raise(self):
        import aiohttp as _aiohttp
        plugin = _make_plugin()
        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=_aiohttp.ClientError("timeout"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 1
        assert stats["last_error"] is not None

    @pytest.mark.asyncio
    async def test_timeout_exception_is_caught(self):
        import asyncio
        plugin = _make_plugin()
        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await plugin.handle_cot_message(SAMPLE_COT_XML, tak_server_id=1)

        stats = plugin.get_health_stats()
        assert stats["events_dropped"] == 1


# ===========================================================================
# get_health_stats
# ===========================================================================


class TestGetHealthStats:
    """Verify health stats shape and initial values."""

    def test_initial_stats_are_zero(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert stats["events_sent"] == 0
        assert stats["events_dropped"] == 0
        assert stats["last_error"] is None

    def test_stats_shape_is_correct(self):
        plugin = _make_plugin()
        stats = plugin.get_health_stats()
        assert set(stats.keys()) == {"events_sent", "events_dropped", "last_error"}


# ===========================================================================
# start / cleanup lifecycle
# ===========================================================================


class TestLifecycle:
    """Verify start() and cleanup() are safe no-ops."""

    @pytest.mark.asyncio
    async def test_start_is_safe_noop(self):
        plugin = _make_plugin()
        # Must not raise
        await plugin.start()

    @pytest.mark.asyncio
    async def test_cleanup_is_safe_noop(self):
        plugin = _make_plugin()
        # Must not raise
        await plugin.cleanup()
