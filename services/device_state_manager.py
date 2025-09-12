"""
ABOUTME: Device state management for generic queue event deduplication across all plugins
ABOUTME: Tracks latest position per device UID to enable smart event replacement
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class DeviceStateManager:
    """
    Generic device state manager for tracking latest positions across all GPS plugins.

    Enables event deduplication by maintaining latest known state for each device UID,
    allowing queue replacement logic to send only current positions instead of
    historical trails.
    """

    def __init__(self):
        """Initialize empty device state tracking"""
        self.device_states: Dict[str, Dict[str, Any]] = {}

    def should_update_device(self, uid: str, new_timestamp: datetime) -> bool:
        """
        Check if new event is newer than current state for device.

        Args:
            uid: Device unique identifier
            new_timestamp: Timestamp of new event

        Returns:
            True if device should be updated (new device or newer timestamp)
        """
        if uid not in self.device_states:
            # New device - always update
            return True

        current_state = self.device_states[uid]
        current_timestamp = current_state.get("timestamp")

        if current_timestamp is None:
            # No timestamp in current state - update
            return True

        # Update if new timestamp is newer
        return new_timestamp > current_timestamp

    def update_device_state(self, uid: str, event_data: Dict[str, Any]) -> None:
        """
        Update latest known state for device.

        Args:
            uid: Device unique identifier
            event_data: Dictionary containing latest device data (timestamp, lat, lon, etc.)
        """
        self.device_states[uid] = event_data.copy()

        logger.debug(
            f"Updated device state for {uid}: {event_data.get('timestamp', 'no timestamp')}"
        )

    def get_stale_devices(self, max_age: timedelta) -> List[str]:
        """
        Find devices that haven't updated recently.

        Args:
            max_age: Maximum age for device to be considered fresh

        Returns:
            List of device UIDs that are older than max_age
        """
        from datetime import timezone as tz

        cutoff_time = datetime.now(tz.utc) - max_age
        stale_devices = []

        for uid, state in self.device_states.items():
            timestamp = state.get("timestamp")
            if timestamp is None or timestamp < cutoff_time:
                stale_devices.append(uid)

        return stale_devices
