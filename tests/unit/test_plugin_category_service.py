"""
Unit tests for the PluginCategoryService

These tests verify the functionality of plugin categorization, dynamic category discovery,
and category-based filtering functionality. The tests mock the plugin manager to avoid
dependencies on actual plugins and focus on testing the category service logic.
"""

import pytest
from unittest.mock import Mock, MagicMock
from services.plugin_category_service import (
    PluginCategoryService,
    CategoryInfo,
    PluginInfo,
    get_category_service,
    initialize_category_service
)


class TestPluginCategoryService:
    """Test suite for PluginCategoryService functionality"""

    @pytest.fixture
    def mock_plugin_manager(self):
        """Create a mock plugin manager for testing"""
        mock_manager = Mock()
        
        # Mock plugin metadata
        mock_metadata = {
            'garmin': {
                'display_name': 'Garmin InReach',
                'description': 'Garmin satellite tracker',
                'icon': 'fas fa-satellite-dish',
                'category': 'tracker'
            },
            'spot': {
                'display_name': 'SPOT Satellite',
                'description': 'SPOT satellite tracker',
                'icon': 'fas fa-satellite',
                'category': 'tracker'
            },
            'deepstate': {
                'display_name': 'DeepstateMAP',
                'description': 'OSINT platform',
                'icon': 'fas fa-map-marked-alt',
                'category': 'osint'
            },
            'traccar': {
                'display_name': 'Traccar GPS Platform',
                'description': 'GPS tracking platform',
                'icon': 'fas fa-map-marked-alt',
                'category': 'tracker'
            }
        }
        
        mock_manager.get_all_plugin_metadata.return_value = mock_metadata
        mock_manager.get_plugin_metadata = lambda key: mock_metadata.get(key)
        
        return mock_manager

    @pytest.fixture
    def category_service(self, mock_plugin_manager):
        """Create a category service instance for testing"""
        return PluginCategoryService(mock_plugin_manager)

    def test_get_available_categories(self, category_service):
        """Test getting all available categories with plugin counts"""
        categories = category_service.get_available_categories()
        
        # Should have discovered 2 categories: OSINT and Tracker
        assert len(categories) == 2
        assert 'OSINT' in categories
        assert 'Tracker' in categories
        
        # Check OSINT category
        osint_category = categories['OSINT']
        assert isinstance(osint_category, CategoryInfo)
        assert osint_category.key == 'OSINT'
        assert osint_category.display_name == 'OSINT'
        assert osint_category.plugin_count == 1  # deepstate
        assert osint_category.icon == 'fas fa-search'
        
        # Check Tracker category  
        tracker_category = categories['Tracker']
        assert isinstance(tracker_category, CategoryInfo)
        assert tracker_category.key == 'Tracker'
        assert tracker_category.display_name == 'Tracker'
        assert tracker_category.plugin_count == 3  # garmin, spot, traccar
        assert tracker_category.icon == 'fas fa-satellite-dish'

    def test_get_plugins_by_category(self, category_service):
        """Test getting plugins filtered by category"""
        # Test Tracker category
        tracker_plugins = category_service.get_plugins_by_category('Tracker')
        assert len(tracker_plugins) == 3
        
        plugin_keys = {plugin.key for plugin in tracker_plugins}
        assert plugin_keys == {'garmin', 'spot', 'traccar'}
        
        # Check plugin info structure
        garmin_plugin = next(p for p in tracker_plugins if p.key == 'garmin')
        assert isinstance(garmin_plugin, PluginInfo)
        assert garmin_plugin.display_name == 'Garmin InReach'
        assert garmin_plugin.category == 'Tracker'
        assert garmin_plugin.icon == 'fas fa-satellite-dish'
        
        # Test OSINT category
        osint_plugins = category_service.get_plugins_by_category('OSINT')
        assert len(osint_plugins) == 1
        assert osint_plugins[0].key == 'deepstate'
        
        # Test non-existent category
        empty_plugins = category_service.get_plugins_by_category('NonExistent')
        assert len(empty_plugins) == 0

    def test_get_category_display_mapping(self, category_service):
        """Test getting the category mapping dictionary"""
        mapping = category_service.get_category_display_mapping()
        
        expected_mapping = {
            'osint': 'OSINT',
            'satellite': 'Tracker',
            'platform': 'Tracker', 
            'tracker': 'Tracker',
            'ems': 'EMS'
        }
        
        assert mapping == expected_mapping

    def test_get_plugin_category(self, category_service):
        """Test getting category for specific plugins"""
        # Test existing plugins
        assert category_service.get_plugin_category('garmin') == 'Tracker'
        assert category_service.get_plugin_category('deepstate') == 'OSINT'
        assert category_service.get_plugin_category('spot') == 'Tracker'
        
        # Test non-existent plugin
        assert category_service.get_plugin_category('nonexistent') is None

    def test_get_categorized_plugins(self, category_service):
        """Test getting all plugins grouped by category"""
        categorized = category_service.get_categorized_plugins()
        
        assert len(categorized) == 2  # OSINT and Tracker
        assert 'OSINT' in categorized
        assert 'Tracker' in categorized
        
        assert len(categorized['OSINT']) == 1
        assert len(categorized['Tracker']) == 3
        
        # Verify plugins are sorted by display name
        tracker_plugins = categorized['Tracker']
        display_names = [p.display_name for p in tracker_plugins]
        assert display_names == sorted(display_names)

    def test_add_category_mapping(self, category_service):
        """Test adding new category mappings"""
        # Add a new mapping
        category_service.add_category_mapping('medical', 'EMS')
        
        mapping = category_service.get_category_display_mapping()
        assert mapping['medical'] == 'EMS'

    def test_get_category_statistics(self, category_service):
        """Test getting category statistics"""
        stats = category_service.get_category_statistics()
        
        assert 'total_categories' in stats
        assert 'total_plugins' in stats
        assert 'categories' in stats
        assert 'category_distribution' in stats
        
        assert stats['total_categories'] == 2
        assert stats['total_plugins'] == 4
        
        # Check category breakdown
        assert 'OSINT' in stats['categories']
        assert 'Tracker' in stats['categories']
        
        assert stats['categories']['OSINT']['plugin_count'] == 1
        assert stats['categories']['Tracker']['plugin_count'] == 3
        
        # Check distribution percentages
        assert stats['category_distribution']['OSINT'] == 25.0  # 1/4 * 100
        assert stats['category_distribution']['Tracker'] == 75.0  # 3/4 * 100

    def test_category_mapping_case_insensitive(self, category_service):
        """Test that category mapping is case insensitive"""
        assert category_service._get_display_category('OSINT') == 'OSINT'
        assert category_service._get_display_category('osint') == 'OSINT'
        assert category_service._get_display_category('Osint') == 'OSINT'
        assert category_service._get_display_category('TRACKER') == 'Tracker'

    def test_unknown_category_handling(self, category_service):
        """Test handling of unknown categories"""
        # Test with unknown category
        result = category_service._get_display_category('unknown')
        assert result == 'Other'

    def test_empty_plugin_metadata(self):
        """Test behavior with no plugins"""
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.return_value = {}
        
        service = PluginCategoryService(mock_manager)
        categories = service.get_available_categories()
        
        assert len(categories) == 0

    def test_plugin_without_category(self, mock_plugin_manager):
        """Test handling of plugins without category metadata"""
        # Add a plugin without category
        metadata = mock_plugin_manager.get_all_plugin_metadata.return_value
        metadata['nocategory'] = {
            'display_name': 'No Category Plugin',
            'description': 'Plugin without category',
            'icon': 'fas fa-question'
            # No 'category' field
        }
        
        service = PluginCategoryService(mock_plugin_manager)
        
        # Should still work, plugin should go to 'Other' category
        categories = service.get_available_categories()
        
        # Should now have 3 categories including 'Other'
        assert 'Other' in categories
        
        other_plugins = service.get_plugins_by_category('Other')
        assert len(other_plugins) == 1
        assert other_plugins[0].key == 'nocategory'


class TestCategoryServiceGlobalFunctions:
    """Test global service management functions"""

    def test_initialize_category_service(self):
        """Test initializing the global category service"""
        mock_manager = Mock()
        
        service = initialize_category_service(mock_manager)
        
        assert isinstance(service, PluginCategoryService)
        assert service.plugin_manager is mock_manager

    def test_get_category_service_after_init(self):
        """Test getting the global service after initialization"""
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.return_value = {}
        
        # Initialize first
        initialize_category_service(mock_manager)
        
        # Should be able to get it without manager
        service = get_category_service()
        assert isinstance(service, PluginCategoryService)

    def test_get_category_service_without_init(self):
        """Test that getting service without init requires manager"""
        # Reset global state
        import services.plugin_category_service
        services.plugin_category_service._category_service = None
        
        with pytest.raises(ValueError, match="Plugin manager is required"):
            get_category_service()

    def test_get_category_service_with_manager_first_time(self):
        """Test getting service with manager on first call"""
        # Reset global state
        import services.plugin_category_service
        services.plugin_category_service._category_service = None
        
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.return_value = {}
        
        service = get_category_service(mock_manager)
        assert isinstance(service, PluginCategoryService)
        assert service.plugin_manager is mock_manager


class TestCategoryServiceErrorHandling:
    """Test error handling in category service"""

    def test_exception_in_get_available_categories(self):
        """Test handling exceptions in get_available_categories"""
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.side_effect = Exception("Test error")
        
        service = PluginCategoryService(mock_manager)
        categories = service.get_available_categories()
        
        # Should return empty dict on error
        assert categories == {}

    def test_exception_in_get_plugins_by_category(self):
        """Test handling exceptions in get_plugins_by_category"""
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.side_effect = Exception("Test error")
        
        service = PluginCategoryService(mock_manager)
        plugins = service.get_plugins_by_category('Tracker')
        
        # Should return empty list on error
        assert plugins == []

    def test_exception_in_get_plugin_category(self):
        """Test handling exceptions in get_plugin_category"""
        mock_manager = Mock()
        mock_manager.get_plugin_metadata.side_effect = Exception("Test error")
        
        service = PluginCategoryService(mock_manager)
        category = service.get_plugin_category('test')
        
        # Should return None on error
        assert category is None

    def test_exception_in_get_category_statistics(self):
        """Test handling exceptions in get_category_statistics"""
        mock_manager = Mock()
        mock_manager.get_all_plugin_metadata.side_effect = Exception("Test error")
        
        service = PluginCategoryService(mock_manager)
        stats = service.get_category_statistics()
        
        # Should return empty dict on error
        assert stats == {}


# Integration-style tests with more realistic data
class TestCategoryServiceIntegration:
    """Integration-style tests with realistic plugin configurations"""

    @pytest.fixture
    def realistic_plugin_manager(self):
        """Plugin manager with realistic plugin metadata"""
        mock_manager = Mock()
        
        # Realistic plugin metadata based on actual plugins
        mock_metadata = {
            'garmin': {
                'display_name': 'Garmin InReach',
                'description': 'Connect to Garmin InReach satellite communicators via KML MapShare feeds',
                'icon': 'fas fa-satellite-dish',
                'category': 'tracker',
                'config_fields': [
                    {'name': 'url', 'required': True},
                    {'name': 'username', 'required': True},
                    {'name': 'password', 'required': True, 'sensitive': True}
                ]
            },
            'spot': {
                'display_name': 'SPOT Satellite',
                'description': 'Connect to SPOT satellite trackers via their web API',
                'icon': 'fas fa-satellite',
                'category': 'tracker',
                'config_fields': [
                    {'name': 'feed_id', 'required': True},
                    {'name': 'password', 'required': True, 'sensitive': True}
                ]
            },
            'deepstate': {
                'display_name': 'DeepstateMAP',
                'description': 'Connect to DeepstateMAP OSINT platform',
                'icon': 'fas fa-map-marked-alt',
                'category': 'osint',
                'config_fields': []
            },
            'traccar': {
                'display_name': 'Traccar GPS Platform',
                'description': 'Connect to Traccar GPS tracking platform via REST API',
                'icon': 'fas fa-map-marked-alt',
                'category': 'tracker',
                'config_fields': [
                    {'name': 'server_url', 'required': True},
                    {'name': 'username', 'required': True},
                    {'name': 'password', 'required': True, 'sensitive': True}
                ]
            }
        }
        
        mock_manager.get_all_plugin_metadata.return_value = mock_metadata
        mock_manager.get_plugin_metadata = lambda key: mock_metadata.get(key)
        
        return mock_manager

    def test_realistic_category_discovery(self, realistic_plugin_manager):
        """Test category discovery with realistic plugin data"""
        service = PluginCategoryService(realistic_plugin_manager)
        
        categories = service.get_available_categories()
        
        # Should discover OSINT and Tracker categories
        assert len(categories) == 2
        assert set(categories.keys()) == {'OSINT', 'Tracker'}
        
        # Verify realistic counts
        assert categories['OSINT'].plugin_count == 1
        assert categories['Tracker'].plugin_count == 3

    def test_realistic_plugin_filtering(self, realistic_plugin_manager):
        """Test plugin filtering with realistic data"""
        service = PluginCategoryService(realistic_plugin_manager)
        
        tracker_plugins = service.get_plugins_by_category('Tracker')
        
        # Should have 3 tracker plugins
        assert len(tracker_plugins) == 3
        
        plugin_names = {p.display_name for p in tracker_plugins}
        expected_names = {'Garmin InReach', 'SPOT Satellite', 'Traccar GPS Platform'}
        assert plugin_names == expected_names
        
        # Verify plugins are sorted by display name
        sorted_names = [p.display_name for p in tracker_plugins]
        assert sorted_names == sorted(sorted_names)

    def test_realistic_statistics(self, realistic_plugin_manager):
        """Test statistics with realistic plugin data"""
        service = PluginCategoryService(realistic_plugin_manager)
        
        stats = service.get_category_statistics()
        
        assert stats['total_plugins'] == 4
        assert stats['total_categories'] == 2
        
        # Check realistic distribution
        assert stats['category_distribution']['OSINT'] == 25.0
        assert stats['category_distribution']['Tracker'] == 75.0