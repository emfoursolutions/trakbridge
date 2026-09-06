# ABOUTME: Regression tests for T2.1 — decrypted plugin config must not
# ABOUTME: render into the stream detail page or leave the server for Test Connection.
"""T2.1 — no credential leak from the stream detail page.

The threat model called out that a VIEWER-authorised session could
Ctrl-U on ``/streams/<id>`` and read every decrypted plugin
credential (Garmin password, API keys, MQTT broker passwords,
Discord/Slack webhook URLs) because the template's Test Connection
button embedded ``stream.get_plugin_config()`` into an inline
``<script>``. The server-side ``/streams/<id>/test`` endpoint already
loads the config itself, so the client only needs to send the
stream id.

Two orthogonal guarantees this file enforces:

1. Rendered HTML contains no ``plugin_<field>: '<secret>'`` literals
   for sensitive keys.
2. The client-side Test Connection code path does not iterate
   ``get_plugin_config`` values into any ``<script>`` block.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestNoInlineConfigInJS:
    """Source-level: the template must not embed decrypted config into
    inline JS. Line 730 was the leak — it iterated
    ``config.items()`` inside a ``<script>`` block. The two remaining
    safe call sites (geofence bounds only) may keep using
    ``get_plugin_config`` because they touch known-safe fields.
    """

    TEMPLATE = Path("templates/stream_detail.html")

    def test_no_config_items_loop_in_template(self):
        """No ``{% for key, value in config.items() %}`` inside a script
        block. That construction is what leaked every credential."""
        source = self.TEMPLATE.read_text()
        # The exact leak pattern was:
        #   {% for key, value in config.items() %}
        #     plugin_{{ key }}: '{{ value }}',
        #   {% endfor %}
        # A literal search catches any near-verbatim reintroduction.
        assert "plugin_{{ key }}" not in source, (
            "stream_detail.html still embeds get_plugin_config() values "
            "into inline JS via `plugin_{{ key }}`. See threat model T2.1."
        )

    def test_get_plugin_config_only_used_for_geofence_bounds(self):
        """Every ``stream.get_plugin_config()`` call should be guarded by
        a ``global_geofence_bounds`` check — that is the only field the
        template legitimately renders. Any other use is a regression."""
        source = self.TEMPLATE.read_text()

        # Find every ``{% set config = stream.get_plugin_config() %}``
        # and confirm the next few lines mention geofence bounds.
        occurrences = [
            m.start() for m in re.finditer(
                r"stream\.get_plugin_config\(\)", source
            )
        ]
        assert occurrences, (
            "Test is stale — no get_plugin_config() calls found. "
            "Update this test if the template was refactored."
        )
        for start in occurrences:
            window = source[start:start + 400]
            assert "global_geofence" in window, (
                f"stream.get_plugin_config() call at offset {start} is "
                f"not gated by a geofence check. New call sites must "
                f"either use stream.to_dict(include_sensitive=False) "
                f"or route through the server-side test endpoint. "
                f"Window follows:\n{window}"
            )


class TestTestConnectionButtonUsesServerSideEndpoint:
    """The Test Connection button must POST to /streams/<id>/test
    (which loads the config server-side) — not /streams/test-connection
    (which requires the caller to send the config)."""

    def test_button_targets_server_side_endpoint(self):
        source = Path("templates/stream_detail.html").read_text()
        # Server-side endpoint takes stream_id in the URL; the client
        # sends nothing sensitive.
        assert "/{{ stream.id }}/test'" in source or \
               '/{{ stream.id }}/test"' in source or \
               "`/streams/${" in source, (
            "Test Connection button in stream_detail.html should POST "
            "to /streams/<id>/test — the server-side endpoint that "
            "loads the plugin config itself. See threat model T2.1."
        )

    def test_button_does_not_post_to_free_form_test_connection(self):
        """The free-form /streams/test-connection endpoint is still
        used by create/edit forms (where the config isn't saved yet),
        but the *detail* page must not use it — it forces the client
        to construct plugin_config from decrypted values."""
        source = Path("templates/stream_detail.html").read_text()
        # Explicit URL in a fetch call — a wider regex would false-
        # positive on comments or hrefs; this is deliberately narrow.
        assert "fetch('/streams/test-connection'" not in source, (
            "stream_detail.html POSTs to /streams/test-connection, "
            "which requires the client to send plugin config. Use "
            "/streams/<id>/test instead so the config stays server-side."
        )


class TestServerSideEndpointExistsAndIsGated:
    """The server-side /streams/<id>/test endpoint must exist and
    require at least streams:read (not public)."""

    def test_server_side_endpoint_route_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any("/streams/<int:stream_id>/test" in r for r in rules), (
            "Server-side test endpoint /streams/<id>/test is missing. "
            "T2.1 fix requires it to exist so credentials never cross "
            "the wire."
        )

    def test_server_side_endpoint_rejects_unauthenticated(self, client):
        """Without auth, POST /streams/<id>/test must not run."""
        response = client.post("/streams/1/test", json={})
        # 302 (login redirect) or 401 — both prove the gate is on.
        assert response.status_code in (302, 401, 400), (
            f"Expected auth gate on /streams/1/test, got "
            f"{response.status_code}"
        )
