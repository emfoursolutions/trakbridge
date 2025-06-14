import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class CotType:
    """Data class representing a single CoT type."""
    value: str
    label: str
    description: str
    category: str


class CotTypesService:
    """Service for managing Cursor-on-Target (CoT) types."""

    def __init__(self, yaml_file_path: str = "config/settings/cot_types.yaml"):
        self.yaml_file_path = yaml_file_path
        self._cot_types: Optional[List[CotType]] = None
        self._default_cot_type: Optional[str] = None
        self._loaded = False

    def _load_from_yaml(self) -> Dict[str, Any]:
        """Load CoT types from YAML file."""
        try:
            yaml_path = Path(self.yaml_file_path)
            if not yaml_path.exists():
                logger.warning(f"CoT types file not found: {self.yaml_file_path}")
                return self._get_default_data()

            with open(yaml_path, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)
                logger.info(f"Loaded CoT types from {self.yaml_file_path}")
                return data

        except yaml.YAMLError as e:
            logger.error(f"Error parsing {self.yaml_file_path}: {e}")
            return self._get_default_data()
        except Exception as e:
            logger.error(f"Unexpected error loading CoT types: {e}")
            return self._get_default_data()

    def _get_default_data(self) -> Dict[str, Any]:
        """Get default CoT types as fallback."""
        return {
            'cot_types': [
                {
                    'value': 'a-f-G-U-C',
                    'label': 'Friendly Ground Unit - Civil',
                    'description': 'Civilian ground unit or personnel',
                    'category': 'friendly'
                },
                {
                    'value': 'a-f-G-U-C-I',
                    'label': 'Friendly Ground Unit - Individual',
                    'description': 'Individual friendly person or operator',
                    'category': 'friendly'
                },
                {
                    'value': 'a-f-G-E-V-C',
                    'label': 'Friendly Ground Equipment - Vehicle - Civil',
                    'description': 'Civilian vehicle or mobile equipment',
                    'category': 'friendly'
                },
                {
                    'value': 'a-n-G',
                    'label': 'Neutral Ground',
                    'description': 'Neutral ground entity',
                    'category': 'neutral'
                }
            ],
            'default_cot_type': 'a-f-G-U-C'
        }

    def _ensure_loaded(self):
        """Ensure CoT types are loaded from source."""
        if self._loaded:
            return

        data = self._load_from_yaml()

        # Convert raw data to CotType objects
        self._cot_types = [
            CotType(
                value=item['value'],
                label=item['label'],
                description=item['description'],
                category=item['category']
            )
            for item in data.get('cot_types', [])
        ]

        self._default_cot_type = data.get('default_cot_type', 'a-f-G-U-C')
        self._loaded = True

    def get_all_cot_types(self) -> List[CotType]:
        """Get all available CoT types."""
        self._ensure_loaded()
        return self._cot_types.copy()

    def get_default_cot_type(self) -> str:
        """Get the default CoT type value."""
        self._ensure_loaded()
        return self._default_cot_type

    def get_cot_type_by_value(self, value: str) -> Optional[CotType]:
        """Get a specific CoT type by its value."""
        self._ensure_loaded()
        return next((cot for cot in self._cot_types if cot.value == value), None)

    def get_cot_types_by_category(self, category: str) -> List[CotType]:
        """Get CoT types filtered by category."""
        self._ensure_loaded()
        return [cot for cot in self._cot_types if cot.category == category]

    def is_valid_cot_type(self, value: str) -> bool:
        """Check if a CoT type value is valid."""
        return self.get_cot_type_by_value(value) is not None

    def reload(self):
        """Force reload of CoT types from source."""
        self._loaded = False
        self._cot_types = None
        self._default_cot_type = None
        self._ensure_loaded()

    def get_template_data(self) -> Dict[str, Any]:
        """Get data formatted for template rendering."""
        self._ensure_loaded()
        return {
            'cot_types': [
                {
                    'value': cot.value,
                    'label': cot.label,
                    'description': cot.description,
                    'category': cot.category
                }
                for cot in self._cot_types
            ],
            'default_cot_type': self._default_cot_type
        }


# Global service instance
cot_type_service = CotTypesService()


# Convenience functions for backward compatibility
def load_cot_types(yaml_file_path: str = "config/settings/cot_types.yaml") -> Dict[str, Any]:
    """Legacy function - use CotTypesService instead."""
    service = CotTypesService(yaml_file_path)
    return service.get_template_data()