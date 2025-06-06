# =============================================================================
# plugins/base_plugin.py - Base Plugin Class
# =============================================================================

from abc import ABC, abstractmethod
from typing import List, Dict, Any
import asyncio
import aiohttp
import logging
from datetime import datetime


class BaseGPSPlugin(ABC):
    """Base class for GPS tracking plugins"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f'{self.__class__.__name__}')

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """Return the name of this plugin"""
        pass

    @property
    @abstractmethod
    def required_config_fields(self) -> List[str]:
        """Return list of required configuration fields"""
        pass

    @abstractmethod
    async def fetch_locations(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        """
        Fetch location data from the GPS service

        Returns:
            List of location dictionaries with keys:
            - name: Device/tracker name
            - lat: Latitude (float)
            - lon: Longitude (float)
            - timestamp: UTC timestamp (datetime)
            - description: Optional description
            - additional_data: Dict of any additional data
        """
        pass

    def validate_config(self) -> bool:
        """Validate that all required configuration fields are present"""
        for field in self.required_config_fields:
            if field not in self.config or not self.config[field]:
                self.logger.error(f"Missing required configuration field: {field}")
                return False
        return True

    async def test_connection(self) -> bool:
        """Test connection to the GPS service"""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                locations = await self.fetch_locations(session)
                return locations is not None
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False