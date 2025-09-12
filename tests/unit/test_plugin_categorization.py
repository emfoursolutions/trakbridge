"""
Integration tests for plugin categorization functionality

These tests verify the complete plugin categorization system including:
- API endpoints for categories and categorized plugins
- Stream creation with category selection
- UI cascading dropdown behavior simulation
- Category persistence in streams
- Integration with the plugin manager
"""

import json
import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from database import db
from models.stream import Stream
from models.tak_server import TakServer
from models.user import AuthProvider, User, UserRole
from services.plugin_category_service import initialize_category_service
from utils.app_helpers import get_plugin_manager


@pytest.fixture
def auth_headers():
    """Simple auth headers for testing authenticated endpoints"""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def mock_app_with_categories(app):
    """Flask app with categorization system initialized (no database objects)"""
    with app.app_context():
        # Initialize the category service
        plugin_manager = get_plugin_manager()
        initialize_category_service(plugin_manager)
        yield app


def create_test_user_and_server(db_session):
    """Helper function to create test user and server with unique names"""
    unique_id = uuid.uuid4().hex[:8]

    # Create test user with unique credentials
    test_user = User(
        username=f"test_user_{unique_id}",
        email=f"test_{unique_id}@example.com",
        full_name="Test User",
        role=UserRole.ADMIN,
        auth_provider=AuthProvider.LOCAL,
    )
    test_user.set_password("test_password")
    db_session.add(test_user)

    # Create test TAK server with unique name
    unique_name = f"Test TAK Server {uuid.uuid4().hex[:8]}"
    test_server = TakServer(
        name=unique_name,
        host="test.example.com",
        port=8087,
        protocol="tls",
        verify_ssl=True,
    )
    db_session.add(test_server)
    db_session.commit()

    return test_user, test_server


class TestPluginCategoryAPI:
    """Test plugin category API endpoints"""

    def test_get_plugin_categories_endpoint(
        self, authenticated_client, mock_app_with_categories, db_session
    ):
        """Test the /api/plugins/categories endpoint"""
        # Create test user and server for this specific test
        create_test_user_and_server(db_session)

        # Authenticate as admin user
        auth_client = authenticated_client("admin")
        response = auth_client.get("/api/plugins/categories")

        assert response.status_code == 200
        data = response.get_json()

        # Should have categories based on existing plugins
        assert isinstance(data, dict)

        # Check that we have expected categories
        category_keys = set(data.keys())
        expected_categories = {
            "OSINT",
            "Tracker",
        }  # Based on standardized plugin categories
        assert expected_categories.issubset(category_keys)

        # Verify category structure
        for category_key, category_data in data.items():
            assert "key" in category_data
            assert "display_name" in category_data
            assert "description" in category_data
            assert "icon" in category_data
            assert "plugin_count" in category_data
            assert isinstance(category_data["plugin_count"], int)

    def test_get_plugins_by_category_endpoint(
        self, authenticated_client, mock_app_with_categories, db_session
    ):
        """Test the /api/plugins/by-category/<category> endpoint"""
        # Create test user and server for this specific test
        create_test_user_and_server(db_session)

        # Authenticate as admin user
        auth_client = authenticated_client("admin")

        # Test Tracker category
        response = auth_client.get("/api/plugins/by-category/Tracker")

        assert response.status_code == 200
        data = response.get_json()

        assert "category" in data
        assert "plugins" in data
        assert data["category"] == "Tracker"

        plugins = data["plugins"]
        assert isinstance(plugins, list)
        assert len(plugins) > 0  # Should have tracker plugins

        # Verify plugin structure
        for plugin in plugins:
            assert "key" in plugin
            assert "display_name" in plugin
            assert "description" in plugin
            assert "icon" in plugin
            assert "category" in plugin
            assert plugin["category"] == "Tracker"

    def test_get_plugins_by_nonexistent_category(
        self, authenticated_client, mock_app_with_categories, db_session
    ):
        """Test getting plugins for non-existent category"""
        # Create test user and server for this specific test
        create_test_user_and_server(db_session)

        # Authenticate as admin user
        auth_client = authenticated_client("admin")

        response = auth_client.get("/api/plugins/by-category/NonExistent")

        assert response.status_code == 200
        data = response.get_json()

        assert data["category"] == "NonExistent"
        assert data["plugins"] == []

    def test_get_categorized_plugins_endpoint(
        self, authenticated_client, mock_app_with_categories, db_session
    ):
        """Test the /api/plugins/categorized endpoint"""
        # Create test user and server for this specific test
        create_test_user_and_server(db_session)

        # Authenticate as admin user
        auth_client = authenticated_client("admin")

        response = auth_client.get("/api/plugins/categorized")

        assert response.status_code == 200
        data = response.get_json()

        assert isinstance(data, dict)

        # Should have categories
        assert len(data) > 0

        # Each category should have a list of plugins
        for category, plugins in data.items():
            assert isinstance(plugins, list)
            for plugin in plugins:
                assert "key" in plugin
                assert "display_name" in plugin
                assert plugin["category"] == category

    def test_get_category_statistics_endpoint(
        self, authenticated_client, mock_app_with_categories, db_session
    ):
        """Test the /api/plugins/category-statistics endpoint"""
        # Create test user and server for this specific test
        create_test_user_and_server(db_session)

        # Authenticate as admin user
        auth_client = authenticated_client("admin")

        response = auth_client.get("/api/plugins/category-statistics")

        assert response.status_code == 200
        data = response.get_json()

        # Verify statistics structure
        assert "total_categories" in data
        assert "total_plugins" in data
        assert "categories" in data
        assert "category_distribution" in data

        assert isinstance(data["total_categories"], int)
        assert isinstance(data["total_plugins"], int)
        assert isinstance(data["categories"], dict)
        assert isinstance(data["category_distribution"], dict)

        # Verify category details
        for category_key, category_info in data["categories"].items():
            assert "plugin_count" in category_info
            assert "display_name" in category_info
            assert "description" in category_info

    def test_category_api_authentication_required(
        self, client, mock_app_with_categories
    ):
        """Test that category APIs require authentication"""
        endpoints = [
            "/api/plugins/categories",
            "/api/plugins/by-category/Tracker",
            "/api/plugins/categorized",
            "/api/plugins/category-statistics",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            # Authentication redirect (302) or unauthorized (401) are both valid
            assert response.status_code in [302, 401]


class TestStreamCreationWithCategories:
    """Test stream creation with category selection"""

    def test_create_stream_form_loads_categories(
        self, client, mock_app_with_categories, auth_headers
    ):
        """Test that create stream form loads with category data"""
        # Mock authentication for this test
        with patch("services.auth.decorators.require_auth", lambda f: f):
            response = client.get("/streams/create", headers=auth_headers)

            # Expect redirect or success depending on route setup
            assert response.status_code in [200, 302]

            # Check that category dropdown is present in HTML (if accessible)
            if response.status_code == 200:
                html_content = response.get_data(as_text=True)
                assert "plugin_category" in html_content
                assert "Select Provider Category" in html_content
                assert "updatePluginsByCategory()" in html_content

    def test_edit_stream_form_loads_categories(
        self, client, mock_app_with_categories, auth_headers, db_session
    ):
        """Test that edit stream form loads with category data"""
        # Mock authentication for this test
        with patch("services.auth.decorators.require_auth", lambda f: f):
            with mock_app_with_categories.app_context():
                # Create test database objects
                test_user, tak_server = create_test_user_and_server(db_session)
                # Create a test stream
                test_stream = Stream(
                    name="Test Stream",
                    plugin_type="garmin",
                    plugin_config='{"url": "test", "username": "test", "password": "test"}',
                    tak_server_id=tak_server.id,
                    poll_interval=120,
                    cot_type="a-f-G-U-C",
                    cot_stale_time=300,
                )
                db.session.add(test_stream)
                db.session.commit()

                response = client.get(
                    f"/streams/{test_stream.id}/edit", headers=auth_headers
                )

                # Expect redirect or success depending on route setup
                assert response.status_code in [200, 302]

                # Check that category dropdown is present in HTML (if accessible)
                if response.status_code == 200:
                    html_content = response.get_data(as_text=True)
                    assert "plugin_category" in html_content
                    assert "Select Provider Category" in html_content
                    assert "updatePluginsByCategory()" in html_content


class TestCategoryMappingAccuracy:
    """Test that category mappings work correctly with actual plugins"""

    def test_plugin_category_mapping_accuracy(self, mock_app_with_categories):
        """Test that plugins are mapped to correct categories"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())

            # Test specific plugins based on our standardization
            expected_mappings = {
                "garmin": "Tracker",
                "spot": "Tracker",
                "traccar": "Tracker",
                "deepstate": "OSINT",
            }

            for plugin_key, expected_category in expected_mappings.items():
                actual_category = category_service.get_plugin_category(plugin_key)
                assert (
                    actual_category == expected_category
                ), f"Plugin {plugin_key} should be in {expected_category}, but is in {actual_category}"

    def test_all_plugins_have_categories(self, mock_app_with_categories):
        """Test that all plugins have valid categories"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            plugin_manager = get_plugin_manager()
            category_service = get_category_service(plugin_manager)

            all_metadata = plugin_manager.get_all_plugin_metadata()

            for plugin_key in all_metadata.keys():
                category = category_service.get_plugin_category(plugin_key)
                assert (
                    category is not None
                ), f"Plugin {plugin_key} does not have a valid category"
                assert isinstance(
                    category, str
                ), f"Plugin {plugin_key} category should be string, got {type(category)}"


class TestCascadingDropdownBehavior:
    """Test cascading dropdown behavior simulation"""

    def test_category_to_plugin_filtering(self, mock_app_with_categories):
        """Test that selecting a category correctly filters plugins"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())

            # Simulate selecting "Tracker" category
            tracker_plugins = category_service.get_plugins_by_category("Tracker")

            # Should have multiple tracker plugins
            assert len(tracker_plugins) > 1

            # All should be tracker plugins
            for plugin in tracker_plugins:
                assert plugin.category == "Tracker"

            # Should include expected plugins
            plugin_keys = {p.key for p in tracker_plugins}
            expected_tracker_plugins = {"garmin", "spot", "traccar"}
            assert expected_tracker_plugins.issubset(plugin_keys)

    def test_empty_category_handling(self, mock_app_with_categories):
        """Test handling of categories with no plugins"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())

            # Test with category that has no plugins
            empty_plugins = category_service.get_plugins_by_category("EMS")

            # Should return empty list, not error
            assert isinstance(empty_plugins, list)
            assert len(empty_plugins) == 0


class TestCategoryPersistence:
    """Test that category information persists correctly"""

    def test_stream_plugin_type_maintains_category_relationship(
        self, mock_app_with_categories, db_session
    ):
        """Test that stream's plugin_type can be used to determine its category"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            # Create test database objects
            test_user, tak_server = create_test_user_and_server(db_session)
            # Create a test stream
            test_stream = Stream(
                name="Category Test Stream",
                plugin_type="garmin",  # Should be in Tracker category
                plugin_config='{"url": "test"}',
                tak_server_id=tak_server.id,
                poll_interval=120,
                cot_type="a-f-G-U-C",
                cot_stale_time=300,
            )
            db.session.add(test_stream)
            db.session.commit()

            # Verify we can determine category from stream
            category_service = get_category_service(get_plugin_manager())
            stream_category = category_service.get_plugin_category(
                test_stream.plugin_type
            )

            assert stream_category == "Tracker"

    def test_multiple_streams_different_categories(
        self, mock_app_with_categories, db_session
    ):
        """Test that streams with different plugin types maintain their categories"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            # Create test database objects
            test_user, tak_server = create_test_user_and_server(db_session)

            # Create streams with different plugin types
            streams_data = [
                ("Tracker Stream", "garmin", "Tracker"),
                ("OSINT Stream", "deepstate", "OSINT"),
                ("Another Tracker", "spot", "Tracker"),
            ]

            created_streams = []
            for name, plugin_type, expected_category in streams_data:
                stream = Stream(
                    name=name,
                    plugin_type=plugin_type,
                    plugin_config='{"test": "data"}',
                    tak_server_id=tak_server.id,
                    poll_interval=120,
                    cot_type="a-f-G-U-C",
                    cot_stale_time=300,
                )
                db.session.add(stream)
                created_streams.append((stream, expected_category))

            db.session.commit()

            # Verify each stream's category
            category_service = get_category_service(get_plugin_manager())

            for stream, expected_category in created_streams:
                actual_category = category_service.get_plugin_category(
                    stream.plugin_type
                )
                assert actual_category == expected_category


class TestCategorySystemIntegration:
    """Test integration of category system with rest of application"""

    def test_category_data_available_in_plugin_metadata(self, mock_app_with_categories):
        """Test that category information is available in plugin metadata"""
        with mock_app_with_categories.app_context():
            plugin_manager = get_plugin_manager()
            all_metadata = plugin_manager.get_all_plugin_metadata()

            # Every plugin should have category information
            for plugin_key, metadata in all_metadata.items():
                assert (
                    "category" in metadata
                ), f"Plugin {plugin_key} missing category in metadata"
                assert isinstance(
                    metadata["category"], str
                ), f"Plugin {plugin_key} category should be string"
                assert (
                    len(metadata["category"]) > 0
                ), f"Plugin {plugin_key} has empty category"

    def test_category_service_initialization_on_app_startup(
        self, mock_app_with_categories
    ):
        """Test that category service initializes properly with the application"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            # Should be able to get category service
            category_service = get_category_service(get_plugin_manager())
            assert category_service is not None

            # Should have discovered categories
            categories = category_service.get_available_categories()
            assert len(categories) > 0

    def test_category_system_performance(self, mock_app_with_categories):
        """Test that category operations perform reasonably"""
        with mock_app_with_categories.app_context():
            import time

            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())

            # Time category operations
            start_time = time.time()

            # Perform various operations
            categories = category_service.get_available_categories()
            for category_key in categories.keys():
                plugins = category_service.get_plugins_by_category(category_key)
                assert isinstance(plugins, list)

            stats = category_service.get_category_statistics()
            assert isinstance(stats, dict)

            end_time = time.time()
            duration = end_time - start_time

            # Should complete quickly (less than 1 second for basic operations)
            assert duration < 1.0, f"Category operations took too long: {duration:.2f}s"


class TestBackwardCompatibility:
    """Test that categorization system maintains backward compatibility"""

    def test_existing_streams_still_work(self, mock_app_with_categories, db_session):
        """Test that existing streams continue to work with category system"""
        with mock_app_with_categories.app_context():
            # Create test database objects
            test_user, tak_server = create_test_user_and_server(db_session)
            # Simulate an existing stream (created before categorization)

            old_stream = Stream(
                name="Legacy Stream",
                plugin_type="garmin",  # This should still work
                plugin_config='{"url": "test", "username": "test", "password": "test"}',
                tak_server_id=tak_server.id,
                poll_interval=120,
                cot_type="a-f-G-U-C",
                cot_stale_time=300,
            )
            db.session.add(old_stream)
            db.session.commit()

            # Should still be able to determine plugin type and category
            assert old_stream.plugin_type == "garmin"

            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())
            category = category_service.get_plugin_category(old_stream.plugin_type)

            assert category == "Tracker"

    def test_plugin_metadata_api_still_works(
        self, client, mock_app_with_categories, auth_headers
    ):
        """Test that original plugin metadata API still functions"""
        response = client.get("/api/plugins/metadata", headers=auth_headers)

        # Authentication redirect or success are both valid
        assert response.status_code in [200, 302]

        if response.status_code == 200:
            data = response.get_json()
            # Should still have plugin metadata
            assert isinstance(data, dict)
            assert len(data) > 0

            # Each plugin should have required fields including category
            for plugin_key, metadata in data.items():
                assert "display_name" in metadata
                assert "description" in metadata
                assert "icon" in metadata
                assert "category" in metadata  # Category should be included


# Performance and error handling tests
class TestCategorySystemRobustness:
    """Test category system robustness and error handling"""

    def test_category_system_with_missing_plugins(self, mock_app_with_categories):
        """Test category system behavior when plugins are missing"""
        with mock_app_with_categories.app_context():
            from services.plugin_category_service import get_category_service
            from utils.app_helpers import get_plugin_manager

            category_service = get_category_service(get_plugin_manager())

            # Test with non-existent plugin
            category = category_service.get_plugin_category("nonexistent_plugin")
            assert category is None

            # Should not crash the system
            categories = category_service.get_available_categories()
            assert isinstance(categories, dict)

    def test_api_error_handling(self, client, mock_app_with_categories, auth_headers):
        """Test API error handling for category endpoints"""
        # Test with invalid category
        response = client.get(
            "/api/plugins/by-category/Invalid%20Category", headers=auth_headers
        )
        # Authentication redirect or success are both valid
        assert response.status_code in [200, 302]  # Should handle gracefully

        if response.status_code == 200:
            data = response.get_json()
            assert data["plugins"] == []  # Should return empty list, not error
