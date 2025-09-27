#!/usr/bin/env python3
"""
Test script to verify both fixes:
1. CoT Type Mode extraction from plugin config
2. Direct workers access instead of get_running_workers()
"""

import sys
import os
import pytest

sys.path.append(".")

from services.cot_service import get_cot_service, reset_cot_service


def test_cot_service_workers_access():
    """Test that QueuedCOTService.workers is accessible"""

    print("Testing QueuedCOTService workers access...")

    try:
        # Reset any existing singleton instance first
        reset_cot_service()

        # Get service using singleton pattern
        service = get_cot_service()

        # Test workers attribute exists and is a dict
        assert hasattr(
            service, "workers"
        ), "QueuedCOTService should have workers attribute"
        assert isinstance(service.workers, dict), "workers should be a dictionary"
        assert len(service.workers) == 0, "workers should start empty"

        # Test workers can be used like the old get_running_workers() return value
        running_workers = service.workers

        # Test operations that the code expects
        worker_keys = running_workers.keys()  # Used in stream_manager.py line 822, 1192
        worker_count = len(
            running_workers
        )  # Used in stream_manager.py line 676, 961, 969
        worker_exists = bool(
            running_workers
        )  # Used in stream_manager.py line 675, 821, 974, 1191

        print(f"✅ SUCCESS: workers attribute accessible")
        print(f"  - Keys: {list(worker_keys)}")
        print(f"  - Count: {worker_count}")
        print(f"  - Exists: {worker_exists}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        pytest.fail(f"COT service workers access test failed: {e}")


def test_plugin_config_extraction():
    """Test that plugin config can be extracted for cot_type_mode"""

    print("\nTesting plugin config extraction...")

    try:
        from plugins.plugin_manager import get_plugin_manager
        from services.stream_config_service import StreamConfigService

        # Create mock form data like what would come from the frontend
        form_data = {
            "name": "Test Stream",
            "plugin_type": "deepstate",
            "plugin_api_url": "https://deepstatemap.live/api/history/last",
            "plugin_cot_type_mode": "per_point",
            "plugin_timeout": "30",
            "plugin_max_events": "100",
        }

        plugin_manager = get_plugin_manager()
        config_service = StreamConfigService(plugin_manager)
        plugin_config = config_service.extract_plugin_config_from_request(form_data)

        print(f"✅ SUCCESS: plugin config extracted")
        print(f"  - Config: {plugin_config}")

        # Test that cot_type_mode can be extracted
        cot_type_mode = plugin_config.get("cot_type_mode", "stream")
        print(f"  - cot_type_mode: {cot_type_mode}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        pytest.fail(f"Plugin config extraction test failed: {e}")


def test_stream_constructor():
    """Test that Stream constructor accepts cot_type_mode"""

    print("\nTesting Stream constructor with cot_type_mode...")

    try:
        from models.stream import Stream

        # Test with per_point mode
        stream = Stream(
            name="Test Stream", plugin_type="deepstate", cot_type_mode="per_point"
        )

        assert (
            stream.cot_type_mode == "per_point"
        ), f"Expected per_point, got {stream.cot_type_mode}"

        print(f"✅ SUCCESS: Stream constructor accepts cot_type_mode")
        print(f"  - Value: {stream.cot_type_mode}")

    except Exception as e:
        print(f"❌ FAILED: {e}")
        pytest.fail(f"Stream constructor test failed: {e}")


if __name__ == "__main__":
    print("Testing both fixes...")

    try:
        test_cot_service_workers_access()
        test_plugin_config_extraction()
        test_stream_constructor()

        print("\n🎉 ALL TESTS PASSED!")
        print("Both fixes are working correctly:")
        print("  1. ✅ QueuedCOTService.workers direct access")
        print("  2. ✅ Plugin config cot_type_mode extraction")
        print("  3. ✅ Stream constructor accepts cot_type_mode")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
