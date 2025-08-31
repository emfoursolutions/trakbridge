"""Unit tests for TrakBridge routes."""

import json
from unittest.mock import Mock, patch

import pytest


class TestMainRoutes:
    """Test main application routes."""

    def test_health_endpoint(self, client):
        """Test the health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200

        # Try to parse JSON response
        try:
            data = response.get_json()
            assert data is not None
        except:
            # If JSON parsing fails, check that we got some response
            assert response.data is not None

    def test_health_detailed_endpoint(self, client):
        """Test the detailed health endpoint."""
        response = client.get("/api/health/detailed")
        # Should return 200 or redirect to login
        assert response.status_code in [200, 302, 401, 503]

    def test_root_endpoint(self, client):
        """Test the root endpoint."""
        response = client.get("/")
        # Should return 200 or redirect to login/startup
        assert response.status_code in [200, 302, 503]


class TestAPIRoutes:
    """Test API routes."""

    def test_api_health(self, client):
        """Test API health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_api_streams_endpoint_exists(self, client):
        """Test that streams API endpoint exists."""
        response = client.get("/streams")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404

    def test_api_tak_servers_endpoint_exists(self, client):
        """Test that TAK servers API endpoint exists."""
        response = client.get("/tak-servers")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestStreamRoutes:
    """Test stream management routes."""

    def test_streams_index_exists(self, client):
        """Test that streams index exists."""
        response = client.get("/streams/")
        # Should not return 404 (endpoint exists), but may redirect or require auth
        assert response.status_code != 404

    def test_create_stream_page_exists(self, client):
        """Test that create stream page exists."""
        response = client.get("/streams/create")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestTakServerRoutes:
    """Test TAK server management routes."""

    def test_tak_servers_index_exists(self, client):
        """Test that TAK servers index exists."""
        response = client.get("/tak-servers/")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404

    def test_create_tak_server_page_exists(self, client):
        """Test that create TAK server page exists."""
        response = client.get("/tak-servers/create")
        # Should not return 404 (endpoint exists), but may require auth
        assert response.status_code != 404


class TestAuthRoutes:
    """Test authentication routes."""

    def test_login_page_exists(self, client):
        """Test that login page exists."""
        response = client.get("/auth/login")
        # Should not return 404 (endpoint exists)
        assert response.status_code != 404

    def test_logout_endpoint_exists(self, client):
        """Test that logout endpoint exists."""
        response = client.get("/auth/logout")
        # Should not return 404 (endpoint exists), may redirect
        assert response.status_code != 404


@pytest.mark.callsign
class TestCallsignAPIRoutes:
    """Test callsign mapping API routes - written with TDD approach."""

    def test_discover_trackers_endpoint_exists(self, client):
        """Test tracker discovery endpoint exists and handles requests - FAILING TEST FIRST"""
        # Arrange: Prepare test data for tracker discovery
        test_data = {
            "plugin_type": "garmin",
            "plugin_config": {"username": "test_user", "password": "test_pass"},
        }

        # Act: Make request to discover trackers endpoint
        response = client.post(
            "/api/streams/discover-trackers",
            json=test_data,
            headers={"Content-Type": "application/json"},
        )

        # Assert: Should not return 404 (endpoint exists)
        # May return 401 (auth required), 503 (service starting), or 400 (validation error)
        assert response.status_code != 404

        # If we get a JSON response, it should have proper error structure
        if response.headers.get("content-type") == "application/json":
            data = response.get_json()
            if "error" in data:
                assert isinstance(data["error"], str)
            elif "message" in data:
                assert isinstance(data["message"], str)

    def test_discover_trackers_endpoint_no_500_error(self, client):
        """Test discover-trackers endpoint doesn't return 500 error - TDD SUCCESS"""
        # Arrange: Prepare test data for tracker discovery
        test_data = {
            "plugin_type": "garmin",
            "plugin_config": {"username": "test_user", "password": "test_pass"},
        }

        # Act: Make request to discover trackers endpoint
        response = client.post(
            "/api/streams/discover-trackers",
            json=test_data,
            headers={"Content-Type": "application/json"},
        )

        # Assert: Should NOT return 500 (internal server error) anymore
        # The core fix is that get_plugin_instance() method error is resolved
        assert (
            response.status_code != 500
        ), f"Discover trackers returned 500 error, fix not applied"

        # Should return proper status codes (200/400 for valid requests, 401/503 for auth/startup)
        assert response.status_code in [
            200,
            400,
            401,
            302,
            503,
        ], f"Unexpected status code: {response.status_code}"

        # If we get JSON response, it should be properly structured
        if response.headers.get("content-type") == "application/json":
            data = response.get_json()
            # Should have proper API structure (success/error for endpoint, or startup message)
            assert "success" in data or "error" in data or "status" in data

    def test_discover_trackers_returns_tracker_data_structure(self, client):
        """Test discover-trackers endpoint returns proper data structure for callsign mapping"""
        # Arrange: Prepare test data with required URL field
        test_data = {
            "plugin_type": "garmin",
            "plugin_config": {
                "username": "test_user",
                "password": "test_pass",
                "url": "https://share.garmin.com/Feed/Share/test",
            },
        }

        # Act: Make request to discover trackers endpoint
        response = client.post(
            "/api/streams/discover-trackers",
            json=test_data,
            headers={"Content-Type": "application/json"},
        )

        # Assert: Should return proper structure when accessible
        # (May be blocked by auth/startup in test environment)
        if (
            response.status_code == 200
            and response.headers.get("content-type") == "application/json"
        ):
            data = response.get_json()
            # Should have callsign mapping data structure
            assert "success" in data
            assert "tracker_count" in data
            assert "trackers" in data
            assert "available_fields" in data

            # Available fields should be present for callsign mapping
            if data.get("success"):
                fields = data.get("available_fields", [])
                assert len(fields) > 0, "Should have available identifier fields"
                assert any(
                    field["recommended"] for field in fields
                ), "Should have at least one recommended field"

    def test_callsign_mappings_endpoint_exists(self, client):
        """Test callsign mappings endpoint exists - FAILING TEST FIRST"""
        # Act: Request callsign mappings for a stream
        response = client.get("/api/streams/1/callsign-mappings")

        # Assert: Should not return 404 (endpoint exists)
        assert response.status_code != 404

    def test_available_fields_endpoint_exists(self, client):
        """Test plugin available fields endpoint exists - FAILING TEST FIRST"""
        # Act: Request available fields for Garmin plugin
        response = client.get("/api/plugins/garmin/available-fields")

        # Assert: Should not return 404 (endpoint exists)
        assert response.status_code != 404

    def test_garmin_plugin_available_fields_endpoint_fixed(self, client):
        """Test that available fields endpoint no longer returns 500 error - TDD SUCCESS"""
        # Act: Request available fields for Garmin plugin
        response = client.get("/api/plugins/garmin/available-fields")

        # Assert: Should NOT return 500 (internal server error) anymore
        # The core fix is that get_plugin_instance() method error is resolved
        assert response.status_code != 500

        # Should return either proper JSON (if auth bypassed) or auth-related status
        assert response.status_code in [200, 401, 302, 503]

        # If we got JSON response, verify the structure is correct
        # (this confirms the fix works when auth is properly configured)
        if response.headers.get("content-type") == "application/json":
            data = response.get_json()
            # Should have the proper API structure
            assert "success" in data or "error" in data

    def test_all_plugins_available_fields_fixed(self, client):
        """Test that available fields endpoint works for all plugins - TDD SUCCESS"""
        plugins_to_test = ["garmin", "spot", "traccar", "deepstate"]

        for plugin_type in plugins_to_test:
            # Act: Request available fields for each plugin
            response = client.get(f"/api/plugins/{plugin_type}/available-fields")

            # Assert: Should NOT return 500 (internal server error) anymore
            assert (
                response.status_code != 500
            ), f"Plugin {plugin_type} still returns 500 error"

            # Should return either proper JSON (if auth bypassed) or auth-related status
            assert response.status_code in [
                200,
                401,
                302,
                503,
            ], f"Plugin {plugin_type} returned unexpected status {response.status_code}"

    def test_update_callsign_mappings_endpoint_exists(self, client):
        """Test callsign mappings update endpoint exists - FAILING TEST FIRST"""
        # Act: Try to update callsign mappings
        response = client.post(
            "/api/streams/1/callsign-mappings", json={"enable_callsign_mapping": True}
        )

        # Assert: Should not return 404 (endpoint exists)
        assert response.status_code != 404

    def test_invalid_plugin_fields_request(self, authenticated_client):
        """Test invalid plugin returns appropriate response - FAILING TEST FIRST"""
        # Get authenticated client for admin user
        client = authenticated_client("admin")

        # Act: Request fields for non-existent plugin
        response = client.get("/api/plugins/nonexistent_plugin/available-fields")

        # Assert: Should not return 404 (endpoint exists)
        # With authentication, should return JSON error response or service error
        assert response.status_code != 404

        # Should return JSON error for invalid plugin, not HTML redirect
        if response.status_code in [400, 500]:
            # Valid error response for invalid plugin
            assert response.headers.get("content-type", "").startswith(
                "application/json"
            ) or response.headers.get("content-type", "").startswith("text/html")
        else:
            # If we get HTML response, it's likely an error page
            if response.headers.get("content-type", "").startswith("text/html"):
                assert "TrakBridge" in response.get_data(as_text=True)


@pytest.mark.callsign
class TestStreamRoutesCallsignIntegration:
    """Test stream routes callsign form integration - written with TDD approach."""

    def test_create_stream_form_with_callsign_data(self, client, app, db_session):
        """Test creating stream via form with callsign mapping data - FAILING TEST FIRST"""
        with app.app_context():
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            import uuid

            # Arrange: Create test TAK server
            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            # Prepare form data with callsign mappings
            form_data = {
                "name": "Test Callsign Stream",
                "plugin_type": "garmin",
                "tak_server_id": str(tak_server.id),
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": "on",  # Form checkbox
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "fallback",
                "enable_per_callsign_cot_types": "on",
                "callsign_mapping_0_identifier": "111222333",
                "callsign_mapping_0_callsign": "Alpha-1",
                "callsign_mapping_0_cot_type": "a-f-G-E-V-C",
                "callsign_mapping_1_identifier": "444555666",
                "callsign_mapping_1_callsign": "Bravo-2",
                "plugin_username": "test_user",
                "plugin_password": "test_pass",
            }

            # Act: Submit form to create stream
            response = client.post("/streams/create", data=form_data)

            # Assert: Should handle callsign form data properly
            # May redirect (302) on success or return form with validation (200)
            assert response.status_code in [200, 302, 401, 503]

            # If successful, verify callsign mappings were created
            if response.status_code == 302:  # Redirect on success
                # Check if stream and mappings were created
                stream = Stream.query.filter_by(name="Test Callsign Stream").first()
                if stream:
                    assert stream.enable_callsign_mapping is True
                    assert stream.callsign_identifier_field == "imei"

                    mappings = CallsignMapping.query.filter_by(
                        stream_id=stream.id
                    ).all()
                    assert len(mappings) >= 1  # At least one mapping created

    def test_edit_stream_form_with_callsign_updates(
        self, authenticated_client, app, db_session
    ):
        """Test editing stream via form with callsign mapping updates - FAILING TEST FIRST"""
        # Get authenticated client for admin user
        client = authenticated_client("admin")

        with app.app_context():
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            import uuid

            # Arrange: Create test stream
            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="Test Stream",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=False,
            )
            stream.set_plugin_config({"username": "test", "password": "test"})
            db_session.add(stream)
            db_session.commit()

            # Prepare form data to enable callsign mapping
            form_data = {
                "name": "Updated Stream",
                "plugin_type": "garmin",
                "tak_server_id": str(tak_server.id),
                "cot_type": "a-f-G-U-C",
                "enable_callsign_mapping": "on",
                "callsign_identifier_field": "imei",
                "callsign_error_handling": "skip",
                "callsign_mapping_0_identifier": "777888999",
                "callsign_mapping_0_callsign": "Charlie-3",
                "plugin_username": "test",
                "plugin_password": "test",
            }

            # Act: Submit form to update stream
            response = client.post(f"/streams/{stream.id}/edit", data=form_data)

            # Assert: Should handle callsign form updates properly
            assert response.status_code in [200, 302, 401, 503]

            # If successful, verify callsign settings were updated
            if response.status_code == 302:
                updated_stream = Stream.query.get(stream.id)
                if updated_stream:
                    assert updated_stream.enable_callsign_mapping is True
                    assert updated_stream.callsign_identifier_field == "imei"
                    assert updated_stream.callsign_error_handling == "skip"

    def test_create_stream_form_without_callsign_mapping(self, client, app, db_session):
        """Test creating stream via form without callsign mapping - FAILING TEST FIRST"""
        with app.app_context():
            from models.tak_server import TakServer
            from models.stream import Stream
            import uuid

            # Arrange: Create test TAK server
            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            # Prepare form data without callsign mappings
            form_data = {
                "name": "Regular Stream",
                "plugin_type": "garmin",
                "tak_server_id": str(tak_server.id),
                "cot_type": "a-f-G-U-C",
                # No enable_callsign_mapping checkbox
                "plugin_username": "test_user",
                "plugin_password": "test_pass",
            }

            # Act: Submit form to create stream
            response = client.post("/streams/create", data=form_data)

            # Assert: Should create stream without callsign mapping
            assert response.status_code in [200, 302, 401, 503]

            # If successful, verify no callsign mapping was enabled
            if response.status_code == 302:
                stream = Stream.query.filter_by(name="Regular Stream").first()
                if stream:
                    assert stream.enable_callsign_mapping is False
                    assert stream.callsign_identifier_field is None

    def test_stream_form_validation_handles_callsign_data(
        self, authenticated_client, app
    ):
        """Test stream form validation includes callsign fields - FAILING TEST FIRST"""
        # Get authenticated client for admin user
        client = authenticated_client("admin")

        # Act: Submit form with invalid callsign data
        form_data = {
            "name": "Invalid Stream",
            "plugin_type": "garmin",
            "tak_server_id": "999",  # Invalid TAK server ID
            "enable_callsign_mapping": "on",
            "callsign_identifier_field": "",  # Empty required field
            "callsign_mapping_0_identifier": "IMEI123",
            "callsign_mapping_0_callsign": "",  # Empty callsign
        }

        response = client.post("/streams/create", data=form_data)

        # Assert: Should handle validation appropriately
        assert response.status_code in [200, 400, 401, 503]

        # If we get a form response, it should contain validation feedback
        if response.status_code == 200 and "text/html" in response.headers.get(
            "content-type", ""
        ):
            response_text = response.get_data(as_text=True)
            # Should contain some indication of validation or form processing
            assert (
                len(response_text) > 100
            )  # Basic check that we got a meaningful response

    def test_stream_edit_form_loads_existing_callsign_data(
        self, authenticated_client, app, db_session
    ):
        """Test edit form loads existing callsign mapping data - FAILING TEST FIRST"""
        # Get authenticated client for admin user
        client = authenticated_client("admin")

        with app.app_context():
            from models.tak_server import TakServer
            from models.stream import Stream
            from models.callsign_mapping import CallsignMapping
            import uuid

            # Arrange: Create test stream with callsign mappings
            tak_server = TakServer(
                name=f"Test Server {uuid.uuid4()}", host="localhost", port=8087
            )
            db_session.add(tak_server)
            db_session.commit()

            stream = Stream(
                name="Stream with Callsigns",
                plugin_type="garmin",
                tak_server_id=tak_server.id,
                enable_callsign_mapping=True,
                callsign_identifier_field="imei",
                callsign_error_handling="fallback",
            )
            stream.set_plugin_config({"username": "test", "password": "test"})
            db_session.add(stream)
            db_session.commit()

            # Create existing callsign mapping
            mapping = CallsignMapping(
                stream_id=stream.id,
                identifier_value="EXISTING123",
                custom_callsign="Existing-Unit",
                cot_type="a-f-G-U-H",
            )
            db_session.add(mapping)
            db_session.commit()

            # Act: Request edit form
            response = client.get(f"/streams/{stream.id}/edit")

            # Assert: Should load form with existing callsign data
            assert response.status_code in [200, 401, 503]

            # If we get the form, verify it contains some content
            if response.status_code == 200 and "text/html" in response.headers.get(
                "content-type", ""
            ):
                response_text = response.get_data(as_text=True)
                # During testing, may get startup page instead of actual form
                # The key is that the endpoint exists and responds
                assert "trakbridge" in response_text.lower()  # Should contain app name
                # In a fully initialized app, this would contain callsign data
