"""
ABOUTME: Unit tests for DeviceStateManager integration with the inbound pipeline covering
ABOUTME: stale location rejection, new device acceptance, and timestamp ordering logic.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.device_state_manager import DeviceStateManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dsm():
    """Create a fresh DeviceStateManager instance."""
    return DeviceStateManager()


@pytest.fixture
def now():
    """Provide a consistent timezone-aware 'now' timestamp."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# New Device Acceptance
# ---------------------------------------------------------------------------


class TestNewDeviceAcceptance:
    """Test that previously unseen devices are always accepted."""

    def test_new_device_should_update(self, dsm, now):
        """A device UID not yet tracked should always be accepted."""
        assert dsm.should_update_device("new-device-1", now) is True

    def test_multiple_new_devices(self, dsm, now):
        """Multiple distinct new device UIDs are all accepted."""
        assert dsm.should_update_device("alpha", now) is True
        assert dsm.should_update_device("bravo", now) is True
        assert dsm.should_update_device("charlie", now) is True

    def test_new_device_state_stored(self, dsm, now):
        """After update, device state is stored and retrievable."""
        event_data = {"timestamp": now, "lat": 38.9, "lon": -77.0}
        dsm.update_device_state("dev-1", event_data)

        assert "dev-1" in dsm.device_states
        assert dsm.device_states["dev-1"]["lat"] == 38.9

    def test_update_does_not_mutate_input(self, dsm, now):
        """update_device_state makes a copy, not a reference."""
        event_data = {"timestamp": now, "lat": 38.9, "lon": -77.0}
        dsm.update_device_state("dev-1", event_data)

        # Mutate original — should not affect stored state
        event_data["lat"] = 0.0
        assert dsm.device_states["dev-1"]["lat"] == 38.9


# ---------------------------------------------------------------------------
# Stale Location Rejection
# ---------------------------------------------------------------------------


class TestStaleLocationRejection:
    """Test that locations older than the last-seen timestamp are rejected."""

    def test_older_timestamp_rejected(self, dsm, now):
        """A location with a timestamp older than the stored one is rejected."""
        dsm.update_device_state("dev-1", {"timestamp": now})

        older = now - timedelta(seconds=30)
        assert dsm.should_update_device("dev-1", older) is False

    def test_same_timestamp_rejected(self, dsm, now):
        """A location with the exact same timestamp is rejected (not strictly newer)."""
        dsm.update_device_state("dev-1", {"timestamp": now})
        assert dsm.should_update_device("dev-1", now) is False

    def test_much_older_timestamp_rejected(self, dsm, now):
        """A location from hours ago is rejected."""
        dsm.update_device_state("dev-1", {"timestamp": now})

        hours_old = now - timedelta(hours=2)
        assert dsm.should_update_device("dev-1", hours_old) is False

    def test_stale_does_not_affect_other_devices(self, dsm, now):
        """Rejecting stale data for one device doesn't affect another."""
        dsm.update_device_state("dev-1", {"timestamp": now})
        dsm.update_device_state("dev-2", {"timestamp": now - timedelta(minutes=5)})

        # dev-1: older → reject
        assert dsm.should_update_device("dev-1", now - timedelta(seconds=1)) is False
        # dev-2: newer than its last → accept
        assert dsm.should_update_device("dev-2", now) is True


# ---------------------------------------------------------------------------
# Timestamp Ordering
# ---------------------------------------------------------------------------


class TestTimestampOrdering:
    """Test correct ordering behavior for sequential updates."""

    def test_newer_timestamp_accepted(self, dsm, now):
        """A location newer than the last-seen timestamp is accepted."""
        dsm.update_device_state("dev-1", {"timestamp": now})

        newer = now + timedelta(seconds=10)
        assert dsm.should_update_device("dev-1", newer) is True

    def test_sequential_updates_accepted(self, dsm, now):
        """A series of monotonically increasing timestamps are all accepted."""
        for i in range(5):
            ts = now + timedelta(seconds=i)
            assert dsm.should_update_device("dev-1", ts) is True
            dsm.update_device_state("dev-1", {"timestamp": ts})

    def test_out_of_order_last_one_rejected(self, dsm, now):
        """After storing the latest, a slightly older one is rejected."""
        t1 = now
        t2 = now + timedelta(seconds=5)
        t3 = now + timedelta(seconds=3)  # Between t1 and t2

        dsm.update_device_state("dev-1", {"timestamp": t1})
        assert dsm.should_update_device("dev-1", t2) is True
        dsm.update_device_state("dev-1", {"timestamp": t2})

        # t3 is older than t2 — should be rejected
        assert dsm.should_update_device("dev-1", t3) is False

    def test_state_tracks_latest_only(self, dsm, now):
        """Device state reflects only the most recently stored event."""
        t1 = now
        t2 = now + timedelta(seconds=10)

        dsm.update_device_state("dev-1", {"timestamp": t1, "lat": 38.9})
        dsm.update_device_state("dev-1", {"timestamp": t2, "lat": 39.0})

        assert dsm.device_states["dev-1"]["lat"] == 39.0
        assert dsm.device_states["dev-1"]["timestamp"] == t2


# ---------------------------------------------------------------------------
# Missing / None Timestamps
# ---------------------------------------------------------------------------


class TestMissingTimestamps:
    """Test behavior when timestamp is missing from device state."""

    def test_no_timestamp_in_state_allows_update(self, dsm, now):
        """Device with no timestamp in state allows any update."""
        dsm.update_device_state("dev-1", {"lat": 38.9, "lon": -77.0})
        assert dsm.should_update_device("dev-1", now) is True

    def test_none_timestamp_in_state_allows_update(self, dsm, now):
        """Device with explicit None timestamp allows any update."""
        dsm.update_device_state("dev-1", {"timestamp": None, "lat": 38.9})
        assert dsm.should_update_device("dev-1", now) is True


# ---------------------------------------------------------------------------
# Stale Device Detection
# ---------------------------------------------------------------------------


class TestStaleDeviceDetection:
    """Test get_stale_devices for cleanup/monitoring purposes."""

    def test_fresh_devices_not_stale(self, dsm, now):
        """Devices updated recently are not considered stale."""
        dsm.update_device_state("dev-1", {"timestamp": now})
        dsm.update_device_state("dev-2", {"timestamp": now - timedelta(seconds=30)})

        stale = dsm.get_stale_devices(max_age=timedelta(minutes=5))
        assert "dev-1" not in stale
        assert "dev-2" not in stale

    def test_old_devices_are_stale(self, dsm, now):
        """Devices not updated within max_age are stale."""
        dsm.update_device_state(
            "dev-old", {"timestamp": now - timedelta(hours=1)}
        )
        dsm.update_device_state("dev-fresh", {"timestamp": now})

        stale = dsm.get_stale_devices(max_age=timedelta(minutes=30))
        assert "dev-old" in stale
        assert "dev-fresh" not in stale

    def test_device_without_timestamp_is_stale(self, dsm):
        """Device with no timestamp is considered stale."""
        dsm.update_device_state("dev-no-ts", {"lat": 38.9})

        stale = dsm.get_stale_devices(max_age=timedelta(minutes=5))
        assert "dev-no-ts" in stale

    def test_empty_manager_returns_no_stale(self, dsm):
        """Empty manager returns no stale devices."""
        stale = dsm.get_stale_devices(max_age=timedelta(minutes=5))
        assert stale == []


# ---------------------------------------------------------------------------
# Multi-Device Isolation
# ---------------------------------------------------------------------------


class TestMultiDeviceIsolation:
    """Test that device state is correctly isolated per UID."""

    def test_independent_device_tracking(self, dsm, now):
        """Each device UID is tracked independently."""
        dsm.update_device_state("alpha", {"timestamp": now, "lat": 10.0})
        dsm.update_device_state("bravo", {"timestamp": now, "lat": 20.0})

        assert dsm.device_states["alpha"]["lat"] == 10.0
        assert dsm.device_states["bravo"]["lat"] == 20.0

    def test_update_one_device_does_not_affect_another(self, dsm, now):
        """Updating one device's state doesn't change another's."""
        dsm.update_device_state("alpha", {"timestamp": now, "lat": 10.0})
        dsm.update_device_state("bravo", {"timestamp": now, "lat": 20.0})

        # Update alpha
        dsm.update_device_state(
            "alpha", {"timestamp": now + timedelta(seconds=5), "lat": 15.0}
        )

        # Bravo unchanged
        assert dsm.device_states["bravo"]["lat"] == 20.0
        assert dsm.device_states["alpha"]["lat"] == 15.0

    def test_stale_check_per_device(self, dsm, now):
        """should_update_device uses per-device timestamps, not global."""
        t_old = now - timedelta(minutes=10)
        t_new = now

        dsm.update_device_state("slow", {"timestamp": t_old})
        dsm.update_device_state("fast", {"timestamp": t_new})

        # A timestamp between t_old and t_new should:
        t_mid = now - timedelta(minutes=5)
        assert dsm.should_update_device("slow", t_mid) is True  # Newer than slow's last
        assert dsm.should_update_device("fast", t_mid) is False  # Older than fast's last
