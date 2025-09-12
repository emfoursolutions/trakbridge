"""
File: services/plugin_category_service.py

Description:
    Service for managing plugin categories and providing category-based filtering
    functionality. Dynamically discovers categories from plugin metadata and provides
    a standardized interface for category management without requiring database storage.

Author: Emfour Solutions
Created: 2025-08-08
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CategoryInfo:
    """Information about a plugin category"""

    key: str
    display_name: str
    description: str
    icon: str
    plugin_count: int = 0


@dataclass
class PluginInfo:
    """Simplified plugin information for category listings"""

    key: str
    display_name: str
    description: str
    icon: str
    category: str


class PluginCategoryService:
    """Service for managing plugin categories and category-based operations"""

    def __init__(self, plugin_manager):
        """
        Initialize the category service

        Args:
            plugin_manager: The plugin manager instance
        """
        self.plugin_manager = plugin_manager

        # Category mapping from plugin categories to display categories
        self._category_mapping = {
            "osint": "OSINT",
            "satellite": "Tracker",
            "platform": "Tracker",
            "tracker": "Tracker",
            "ems": "EMS",
        }

        # Category display information
        self._category_info = {
            "OSINT": CategoryInfo(
                key="OSINT",
                display_name="OSINT",
                description="Open Source Intelligence platforms and tools",
                icon="fas fa-search",
            ),
            "Tracker": CategoryInfo(
                key="Tracker",
                display_name="Tracker",
                description="GPS and satellite tracking devices and platforms",
                icon="fas fa-satellite-dish",
            ),
            "EMS": CategoryInfo(
                key="EMS",
                display_name="EMS",
                description="Emergency Management Systems and services",
                icon="fas fa-ambulance",
            ),
        }

    def get_available_categories(self) -> Dict[str, CategoryInfo]:
        """
        Get all available categories with plugin counts

        Returns:
            Dictionary mapping category keys to CategoryInfo objects
        """
        try:
            # Start with base category info
            categories = {}

            # Get all plugin metadata
            all_metadata = self.plugin_manager.get_all_plugin_metadata()

            # Count plugins per category
            category_counts = {}
            discovered_categories = set()

            for plugin_key, metadata in all_metadata.items():
                plugin_category = metadata.get("category", "uncategorized")
                display_category = self._get_display_category(plugin_category)

                # Track discovered categories
                discovered_categories.add(display_category)

                # Count plugins per category
                category_counts[display_category] = (
                    category_counts.get(display_category, 0) + 1
                )

            # Build categories with counts
            for category_key in discovered_categories:
                if category_key in self._category_info:
                    category_info = self._category_info[category_key]
                    categories[category_key] = CategoryInfo(
                        key=category_info.key,
                        display_name=category_info.display_name,
                        description=category_info.description,
                        icon=category_info.icon,
                        plugin_count=category_counts.get(category_key, 0),
                    )
                else:
                    # Handle unknown categories dynamically
                    categories[category_key] = CategoryInfo(
                        key=category_key,
                        display_name=category_key,
                        description=f"Plugins in the {category_key} category",
                        icon="fas fa-puzzle-piece",
                        plugin_count=category_counts.get(category_key, 0),
                    )

            logger.debug(f"Discovered {len(categories)} plugin categories")
            return categories

        except Exception as e:
            logger.error(f"Error getting available categories: {e}")
            return {}

    def get_plugins_by_category(self, category: str) -> List[PluginInfo]:
        """
        Get all plugins in a specific category

        Args:
            category: The category to filter by

        Returns:
            List of PluginInfo objects for plugins in the category
        """
        try:
            plugins = []
            all_metadata = self.plugin_manager.get_all_plugin_metadata()

            for plugin_key, metadata in all_metadata.items():
                plugin_category = metadata.get("category", "uncategorized")
                display_category = self._get_display_category(plugin_category)

                if display_category == category:
                    plugins.append(
                        PluginInfo(
                            key=plugin_key,
                            display_name=metadata.get("display_name", plugin_key),
                            description=metadata.get(
                                "description", "No description available"
                            ),
                            icon=metadata.get("icon", "fas fa-puzzle-piece"),
                            category=display_category,
                        )
                    )

            # Sort plugins by display name
            plugins.sort(key=lambda p: p.display_name)

            logger.debug(f"Found {len(plugins)} plugins in category '{category}'")
            return plugins

        except Exception as e:
            logger.error(f"Error getting plugins for category '{category}': {e}")
            return []

    def get_category_display_mapping(self) -> Dict[str, str]:
        """
        Get the mapping from plugin categories to display categories

        Returns:
            Dictionary mapping plugin categories to display categories
        """
        return self._category_mapping.copy()

    def get_plugin_category(self, plugin_key: str) -> Optional[str]:
        """
        Get the display category for a specific plugin

        Args:
            plugin_key: The plugin key/name

        Returns:
            The display category name, or None if plugin not found
        """
        try:
            metadata = self.plugin_manager.get_plugin_metadata(plugin_key)
            if metadata:
                plugin_category = metadata.get("category", "uncategorized")
                return self._get_display_category(plugin_category)
            return None

        except Exception as e:
            logger.error(f"Error getting category for plugin '{plugin_key}': {e}")
            return None

    def get_categorized_plugins(self) -> Dict[str, List[PluginInfo]]:
        """
        Get all plugins grouped by category

        Returns:
            Dictionary mapping category names to lists of PluginInfo objects
        """
        try:
            categorized = {}
            categories = self.get_available_categories()

            for category_key in categories.keys():
                categorized[category_key] = self.get_plugins_by_category(category_key)

            return categorized

        except Exception as e:
            logger.error(f"Error getting categorized plugins: {e}")
            return {}

    def _get_display_category(self, plugin_category: str) -> str:
        """
        Convert a plugin category to a display category

        Args:
            plugin_category: The category defined in the plugin

        Returns:
            The display category name
        """
        return self._category_mapping.get(plugin_category.lower(), "Other")

    def add_category_mapping(self, plugin_category: str, display_category: str):
        """
        Add a new category mapping (useful for external plugins)

        Args:
            plugin_category: The category key from plugin metadata
            display_category: The display category to map it to
        """
        self._category_mapping[plugin_category.lower()] = display_category
        logger.info(f"Added category mapping: {plugin_category} -> {display_category}")

    def get_category_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about plugin categories

        Returns:
            Dictionary with category statistics
        """
        try:
            categories = self.get_available_categories()
            total_plugins = sum(cat.plugin_count for cat in categories.values())

            stats = {
                "total_categories": len(categories),
                "total_plugins": total_plugins,
                "categories": {
                    key: {
                        "plugin_count": cat.plugin_count,
                        "display_name": cat.display_name,
                        "description": cat.description,
                    }
                    for key, cat in categories.items()
                },
                "category_distribution": {
                    key: (
                        round((cat.plugin_count / total_plugins) * 100, 1)
                        if total_plugins > 0
                        else 0
                    )
                    for key, cat in categories.items()
                },
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting category statistics: {e}")
            return {}


# Global instance - will be initialized by the application
_category_service: Optional[PluginCategoryService] = None


def get_category_service(plugin_manager=None) -> PluginCategoryService:
    """
    Get the global category service instance

    Args:
        plugin_manager: Plugin manager instance (required for first call)

    Returns:
        The category service instance
    """
    global _category_service

    if _category_service is None:
        if plugin_manager is None:
            raise ValueError("Plugin manager is required for first initialization")
        _category_service = PluginCategoryService(plugin_manager)

    return _category_service


def initialize_category_service(plugin_manager) -> PluginCategoryService:
    """
    Initialize the global category service

    Args:
        plugin_manager: The plugin manager instance

    Returns:
        The initialized category service
    """
    global _category_service
    _category_service = PluginCategoryService(plugin_manager)
    return _category_service
