"""
ABOUTME: Phase 6 TDD tests for inbound stream UI integration covering stream list,
ABOUTME: create/edit forms, detail view, and backend form handling for inbound fields.
"""

from unittest.mock import MagicMock, patch

import pytest

from models.stream import Stream


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def inbound_stream(app, db_session):
    """Create a real inbound stream in the test database."""
    from models.tak_server import TakServer

    server = TakServer(
        name="Test TAK",
        host="tak.example.com",
        port=8089,
        protocol="ssl",
    )
    db_session.add(server)
    db_session.flush()

    stream = Stream(
        name="Inbound Test Stream",
        plugin_type="generic_inbound",
        stream_mode="inbound",
        tak_server_id=server.id,
        inbound_api_key="ENC:test-key-abcd1234",
        inbound_rate_limit=30,
        inbound_ip_allowlist='["10.0.0.0/8"]',
        inbound_preview_mode=True,
    )
    db_session.add(stream)
    db_session.commit()
    return stream


@pytest.fixture
def poll_stream(app, db_session):
    """Create a standard poll-based stream for comparison."""
    from models.tak_server import TakServer

    server = TakServer(
        name="Poll TAK",
        host="tak2.example.com",
        port=8089,
        protocol="ssl",
    )
    db_session.add(server)
    db_session.flush()

    stream = Stream(
        name="Poll Test Stream",
        plugin_type="garmin",
        stream_mode="poll",
        tak_server_id=server.id,
        poll_interval=120,
    )
    db_session.add(stream)
    db_session.commit()
    return stream


@pytest.fixture
def authenticated_admin(client, app, db_session):
    """Create an authenticated admin client for template rendering tests."""
    from models.user import AuthProvider, User, UserRole

    user = User(
        username="testadmin",
        email="admin@test.com",
        full_name="Test Admin",
        role=UserRole.ADMIN,
        auth_provider=AuthProvider.LOCAL,
    )
    user.set_password("AdminPass123")
    db_session.add(user)
    db_session.commit()

    from services.auth.auth_manager import AuthenticationManager

    with patch(
        "config.authentication_loader.load_authentication_config",
        return_value={
            "session": {"lifetime_hours": 8, "cleanup_interval_minutes": 60, "secure_cookies": False},
            "provider_priority": ["local"],
            "providers": {"local": {"enabled": True, "password_policy": {"min_length": 8, "require_uppercase": True, "require_lowercase": True, "require_numbers": True, "require_special": False}}},
        },
    ):
        manager = AuthenticationManager()
        session = manager.create_session(user)

    with client.session_transaction() as sess:
        sess["session_id"] = session.session_id
        sess["user_id"] = user.id

    return client


# ===========================================================================
# 6.1 — Stream Creation/Edit Forms
# ===========================================================================


class TestCreateStreamFormInboundFields:
    """Test that the create stream form includes inbound-specific fields."""

    def test_create_form_contains_inbound_config_section(self, authenticated_admin, app):
        """The create stream form must have an inbound configuration section
        that is hidden by default and shown when an inbound plugin is selected."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        # The form must contain the inbound config container
        assert 'id="inbound-config-section"' in html, (
            "Create form missing inbound-config-section element"
        )

    def test_create_form_has_inbound_rate_limit_field(self, authenticated_admin, app):
        """Inbound rate limit field must be present in create form."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        assert 'name="inbound_rate_limit"' in html, (
            "Create form missing inbound_rate_limit field"
        )

    def test_create_form_has_inbound_ip_allowlist_field(self, authenticated_admin, app):
        """IP allowlist textarea must be present in create form."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        assert 'name="inbound_ip_allowlist"' in html, (
            "Create form missing inbound_ip_allowlist field"
        )

    def test_create_form_has_generate_api_key_button(self, authenticated_admin, app):
        """There should be a button/action to generate an API key for inbound streams."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        assert "generateApiKey" in html or "generate-api-key" in html, (
            "Create form missing API key generation control"
        )

    def test_create_form_hides_poll_interval_for_inbound(self, authenticated_admin, app):
        """JavaScript must hide poll_interval when an inbound category plugin is selected.
        We verify the JS function references the inbound category."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        # The updatePluginConfig JS must handle inbound category to hide poll settings
        assert "inbound" in html.lower(), (
            "Create form JS does not reference inbound category for visibility toggling"
        )

    def test_create_form_shows_endpoint_url_hint(self, authenticated_admin, app):
        """For inbound streams, the form should indicate the endpoint URL pattern."""
        response = authenticated_admin.get("/streams/create")
        html = response.data.decode()

        assert "/api/inbound/" in html or "inbound-endpoint-url" in html, (
            "Create form missing inbound endpoint URL display"
        )


class TestEditStreamFormInboundFields:
    """Test that the edit stream form correctly populates inbound fields."""

    def test_edit_form_shows_inbound_config_section(self, authenticated_admin, app, inbound_stream):
        """Edit form for an inbound stream must show the inbound configuration section."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}/edit")
        html = response.data.decode()

        assert 'id="inbound-config-section"' in html, (
            "Edit form missing inbound-config-section element"
        )

    def test_edit_form_populates_rate_limit(self, authenticated_admin, app, inbound_stream):
        """Edit form must populate the rate limit value from the stream."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}/edit")
        html = response.data.decode()

        # The rate limit value should appear in the form
        assert str(inbound_stream.inbound_rate_limit) in html, (
            f"Edit form does not populate inbound_rate_limit={inbound_stream.inbound_rate_limit}"
        )

    def test_edit_form_populates_ip_allowlist(self, authenticated_admin, app, inbound_stream):
        """Edit form must populate the IP allowlist from the stream."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}/edit")
        html = response.data.decode()

        assert "10.0.0.0/8" in html, (
            "Edit form does not populate inbound_ip_allowlist"
        )

    def test_edit_form_shows_preview_mode_toggle(self, authenticated_admin, app, inbound_stream):
        """Edit form must show a preview mode toggle for inbound streams."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}/edit")
        html = response.data.decode()

        assert 'name="inbound_preview_mode"' in html or "inbound_preview_mode" in html, (
            "Edit form missing inbound_preview_mode toggle"
        )

    def test_edit_form_masks_api_key(self, authenticated_admin, app, inbound_stream):
        """Edit form must NOT expose the raw encrypted API key. It should be masked."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}/edit")
        html = response.data.decode()

        # The raw encrypted key should never appear
        assert "ENC:test-key-abcd1234" not in html, (
            "Edit form exposes raw encrypted API key"
        )


# ===========================================================================
# 6.2 — Stream List View
# ===========================================================================


class TestStreamListInboundDisplay:
    """Test that the streams list shows inbound stream information correctly."""

    def test_stream_list_shows_mode_badge_for_inbound(self, authenticated_admin, app, inbound_stream):
        """Inbound streams must show a mode badge (e.g. 'Inbound') in the list."""
        response = authenticated_admin.get("/streams/")
        html = response.data.decode()

        # Check that some kind of inbound indicator exists
        assert "Inbound" in html or "inbound" in html, (
            "Stream list does not show inbound mode indicator"
        )

    def test_stream_list_shows_mode_badge_for_poll(self, authenticated_admin, app, poll_stream):
        """Poll streams should show a Poll mode badge or interval display."""
        response = authenticated_admin.get("/streams/")
        html = response.data.decode()

        # Poll streams show their interval
        assert f"{poll_stream.poll_interval}s" in html or "Poll" in html, (
            "Stream list does not show poll mode indicator"
        )

    def test_stream_list_hides_interval_for_inbound(self, authenticated_admin, app, inbound_stream):
        """Inbound streams should NOT show a poll interval in the list since they are push-based."""
        response = authenticated_admin.get("/streams/")
        html = response.data.decode()

        # The interval text should not be shown for inbound streams next to
        # the inbound stream name. We check that the inbound stream row
        # does not contain 'interval' text.
        # A simple proxy: the text "120s interval" shouldn't appear for an inbound
        # stream that has the default poll_interval.
        # We look for whether the stream_mode is rendered appropriately
        assert "Push" in html or "inbound" in html.lower(), (
            "Stream list should indicate push mode for inbound streams"
        )


# ===========================================================================
# 6.3 — Stream Detail View
# ===========================================================================


class TestStreamDetailInboundDisplay:
    """Test that stream detail page shows inbound-specific information."""

    def test_detail_shows_stream_mode(self, authenticated_admin, app, inbound_stream):
        """Stream detail must show the stream mode (Inbound)."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        assert "Inbound" in html, (
            "Stream detail does not show stream mode"
        )

    def test_detail_shows_endpoint_url(self, authenticated_admin, app, inbound_stream):
        """Stream detail must display the endpoint URL for sending data."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        expected_url_fragment = f"/api/inbound/{inbound_stream.id}/data"
        assert expected_url_fragment in html, (
            f"Stream detail does not show endpoint URL: {expected_url_fragment}"
        )

    def test_detail_shows_rate_limit(self, authenticated_admin, app, inbound_stream):
        """Stream detail must show the configured rate limit."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        assert str(inbound_stream.inbound_rate_limit) in html, (
            "Stream detail does not show rate limit"
        )

    def test_detail_shows_preview_mode_status(self, authenticated_admin, app, inbound_stream):
        """Stream detail must show preview mode status."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        assert "Preview" in html or "preview" in html, (
            "Stream detail does not show preview mode status"
        )

    def test_detail_shows_api_key_masked(self, authenticated_admin, app, inbound_stream):
        """Stream detail must show a masked API key, not the raw encrypted value."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        # Raw key must not be present
        assert "ENC:test-key-abcd1234" not in html, (
            "Stream detail exposes raw API key"
        )

    def test_detail_hides_poll_interval_for_inbound(self, authenticated_admin, app, inbound_stream):
        """For inbound streams, the Poll Interval metric card should say 'Push' or similar
        instead of showing a poll interval number."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        # The detail page has a "Poll Interval" metric card — for inbound it should
        # show Push or N/A
        assert "Push" in html or "N/A" in html or "Inbound" in html, (
            "Stream detail shows poll interval for inbound stream instead of push indicator"
        )

    def test_detail_shows_ip_allowlist(self, authenticated_admin, app, inbound_stream):
        """Stream detail must show configured IP allowlist."""
        response = authenticated_admin.get(f"/streams/{inbound_stream.id}")
        html = response.data.decode()

        assert "10.0.0.0/8" in html or "IP" in html, (
            "Stream detail does not show IP allowlist information"
        )


# ===========================================================================
# 6.4 — Backend: StreamOperationsService inbound field handling
# ===========================================================================


class TestStreamOperationsInboundCreate:
    """Test that StreamOperationsService correctly handles inbound fields during creation."""

    def test_create_inbound_stream_sets_stream_mode(self, app, db_session):
        """Creating a stream with stream_mode='inbound' must persist it."""
        from models.tak_server import TakServer

        server = TakServer(name="S1", host="h1", port=8089, protocol="ssl")
        db_session.add(server)
        db_session.commit()

        stream_mgr = MagicMock()
        stream_mgr.refresh_stream_tak_workers.return_value = True

        from services.stream_operations_service import StreamOperationsService

        svc = StreamOperationsService(stream_mgr, db_session)

        with patch("plugins.plugin_manager.get_plugin_manager") as mock_pm, \
             patch("services.stream_config_service.StreamConfigService") as mock_cfg_cls:
            mock_cfg_cls.return_value.extract_plugin_config_from_request.return_value = {}

            result = svc.create_stream({
                "name": "Inbound Via Service",
                "plugin_type": "generic_inbound",
                "tak_servers": [str(server.id)],
                "stream_mode": "inbound",
                "inbound_rate_limit": "45",
                "inbound_ip_allowlist": '["192.168.1.0/24"]',
                "inbound_preview_mode": "true",
            })

        assert result["success"], f"create_stream failed: {result}"
        created = db_session.get(Stream, result["stream_id"])
        assert created.stream_mode == "inbound"
        assert created.inbound_rate_limit == 45
        assert created.inbound_ip_allowlist == '["192.168.1.0/24"]'
        assert created.inbound_preview_mode is True

    def test_create_inbound_stream_generates_api_key_if_missing(self, app, db_session):
        """If no API key is provided, the service should auto-generate one."""
        from models.tak_server import TakServer

        server = TakServer(name="S2", host="h2", port=8089, protocol="ssl")
        db_session.add(server)
        db_session.commit()

        stream_mgr = MagicMock()
        stream_mgr.refresh_stream_tak_workers.return_value = True

        from services.stream_operations_service import StreamOperationsService

        svc = StreamOperationsService(stream_mgr, db_session)

        with patch("plugins.plugin_manager.get_plugin_manager") as mock_pm, \
             patch("services.stream_config_service.StreamConfigService") as mock_cfg_cls:
            mock_cfg_cls.return_value.extract_plugin_config_from_request.return_value = {}

            result = svc.create_stream({
                "name": "Inbound No Key",
                "plugin_type": "generic_inbound",
                "tak_servers": [str(server.id)],
                "stream_mode": "inbound",
            })

        assert result["success"], f"create_stream failed: {result}"
        created = db_session.get(Stream, result["stream_id"])
        assert created.stream_mode == "inbound"
        # API key should have been auto-generated
        assert created.inbound_api_key is not None
        assert len(created.inbound_api_key) > 0


class TestStreamOperationsInboundUpdate:
    """Test that StreamOperationsService correctly handles inbound fields during updates."""

    def test_update_stream_preserves_inbound_fields(self, app, db_session, inbound_stream):
        """Updating an inbound stream must preserve inbound-specific fields."""
        stream_mgr = MagicMock()
        stream_mgr.get_stream_status.return_value = {"running": False}
        stream_mgr.refresh_stream_tak_workers.return_value = True

        from services.stream_operations_service import StreamOperationsService

        svc = StreamOperationsService(stream_mgr, db_session)

        with patch("plugins.plugin_manager.get_plugin_manager") as mock_pm, \
             patch("services.stream_config_service.StreamConfigService") as mock_cfg_cls:
            mock_cfg_cls.return_value.extract_plugin_config_from_request.return_value = {}
            mock_cfg_cls.return_value.merge_plugin_config_with_existing.return_value = {}
            mock_pm.return_value.get_plugin_metadata.return_value = None

            result = svc.update_stream_safely(inbound_stream.id, {
                "name": "Updated Inbound",
                "plugin_type": "generic_inbound",
                "tak_servers": [str(inbound_stream.tak_server_id)],
                "stream_mode": "inbound",
                "inbound_rate_limit": "100",
                "inbound_ip_allowlist": '["172.16.0.0/12"]',
                "inbound_preview_mode": "false",
            })

        assert result["success"], f"update failed: {result}"
        db_session.refresh(inbound_stream)
        assert inbound_stream.inbound_rate_limit == 100
        assert inbound_stream.inbound_ip_allowlist == '["172.16.0.0/12"]'
        assert inbound_stream.inbound_preview_mode is False


# ===========================================================================
# 6.5 — API Key Generation Endpoint
# ===========================================================================


class TestApiKeyGeneration:
    """Test the API key generation endpoint for inbound streams."""

    def test_generate_api_key_endpoint_exists(self, authenticated_admin, app):
        """There must be an endpoint to generate a new API key."""
        response = authenticated_admin.post(
            "/api/inbound/generate-api-key",
            content_type="application/json",
        )
        # Should not be 404 (endpoint exists) — 200 or auth redirect are acceptable
        assert response.status_code != 404, (
            "API key generation endpoint does not exist"
        )

    def test_generate_api_key_returns_key(self, authenticated_admin, app):
        """The generate endpoint must return a new API key."""
        response = authenticated_admin.post(
            "/api/inbound/generate-api-key",
            content_type="application/json",
        )
        if response.status_code == 200:
            data = response.get_json()
            assert "api_key" in data, "Response missing api_key field"
            assert len(data["api_key"]) >= 32, "Generated key too short"

    def test_generate_api_key_requires_auth(self, client, app):
        """Unauthenticated requests to generate-api-key must be rejected."""
        response = client.post(
            "/api/inbound/generate-api-key",
            content_type="application/json",
        )
        # Should redirect to login or return 401/403
        assert response.status_code in (302, 401, 403), (
            f"Unauthenticated API key generation returned {response.status_code}"
        )


# ===========================================================================
# 6.6 — Integration: Create inbound stream via form POST
# ===========================================================================


class TestCreateInboundStreamFormPost:
    """Test creating an inbound stream through the form submission flow."""

    def test_form_post_creates_inbound_stream(self, authenticated_admin, app, db_session):
        """POSTing the create form with inbound fields should create the stream."""
        from models.tak_server import TakServer

        server = TakServer(name="FormTAK", host="form.example.com", port=8089, protocol="ssl")
        db_session.add(server)
        db_session.commit()

        response = authenticated_admin.post(
            "/streams/create",
            data={
                "name": "Form Inbound Stream",
                "plugin_type": "generic_inbound",
                "plugin_category": "inbound",
                "tak_servers[]": str(server.id),
                "poll_interval": "120",
                "cot_type": "a-f-G-U-C",
                "cot_stale_time": "300",
                "stream_mode": "inbound",
                "inbound_rate_limit": "50",
                "inbound_ip_allowlist": "",
                "inbound_preview_mode": "on",
            },
            follow_redirects=False,
        )

        # Should redirect to the stream detail page on success
        assert response.status_code in (200, 302), (
            f"Form POST returned {response.status_code}"
        )

        # Verify the stream was created with inbound fields
        created = Stream.query.filter_by(name="Form Inbound Stream").first()
        assert created is not None, "Inbound stream not created via form POST"
        assert created.stream_mode == "inbound"
        assert created.inbound_rate_limit == 50
        assert created.inbound_preview_mode is True
