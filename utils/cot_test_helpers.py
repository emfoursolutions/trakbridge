"""
ABOUTME: Test helper utilities for COT service testing
ABOUTME: Provides clean helper functions for test cases without polluting
ABOUTME: production code

File: utils/cot_test_helpers.py

Description:
    Test utilities for COT service testing that provide clean helper functions
    for creating test events, accessing queues, and managing test configuration
    without polluting production service code.

Key features:
    - Test event creation with configurable properties
    - Queue access helpers for verification
    - Configuration helpers for test setup
    - Clean separation from production code

Author: TrakBridge Development Team
Created: 2025-09-24
"""

import asyncio
import time
from typing import Any, Dict, Optional
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


def create_test_cot_event(
    uid: str, event_type: str = "a-f-G-U-C", **kwargs
) -> Dict[str, Any]:
    """
    Create a test COT event dictionary with default values.

    Args:
        uid: Unique identifier for the event
        event_type: COT type identifier (default: "a-f-G-U-C")
        **kwargs: Additional event properties to override defaults

    Returns:
        Dictionary containing test event data
    """
    default_event = {
        "uid": uid,
        "time": time.time(),
        "type": event_type,
        "lat": 40.7128,
        "lon": -74.0060,
        "hae": 10.0,
        "callsign": f"Test-{uid}",
        "name": f"Test-{uid}",
        "description": f"Test event {uid}",
    }

    # Override defaults with any provided kwargs
    default_event.update(kwargs)
    return default_event


def get_queue_for_server(cot_service, tak_server_id: int) -> Optional[asyncio.Queue]:
    """
    Get the queue for a specific TAK server for test verification.

    Args:
        cot_service: COT service instance
        tak_server_id: TAK server identifier

    Returns:
        asyncio.Queue instance or None if not found
    """
    if hasattr(cot_service, "queue_manager") and cot_service.queue_manager:
        return cot_service.queue_manager.queues.get(tak_server_id)
    elif hasattr(cot_service, "queues"):
        return cot_service.queues.get(tak_server_id)
    else:
        logger.warning(
            f"Could not find queue interface on COT service for server "
            f"{tak_server_id}"
        )
        return None


async def enqueue_test_event(
    cot_service, tak_server_id: int, event_data: Dict[str, Any]
) -> bool:
    """
    Enqueue a test event using the production API.

    Args:
        cot_service: COT service instance
        tak_server_id: TAK server identifier
        event_data: Event data dictionary

    Returns:
        True if successfully enqueued
    """
    try:
        # Create a simple COT XML from the dict for testing
        event_xml = (
            f"<event uid='{event_data.get('uid', 'test')}' "
            f"type='{event_data.get('type', 'a-f-G-U-C')}'/>".encode()
        )

        # Use the production enqueue_event method
        return await cot_service.enqueue_event(event_xml, tak_server_id)
    except Exception as e:
        logger.error(f"Failed to enqueue test event for server {tak_server_id}: {e}")
        return False


def create_queue_config(
    max_size: int = 500,
    batch_size: int = 20,
    overflow_strategy: str = "drop_oldest",
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a queue configuration dictionary for testing.

    Args:
        max_size: Maximum queue size (default: 500)
        batch_size: Batch size for transmission (default: 20)
        overflow_strategy: Overflow handling strategy
                          (default: "drop_oldest")
        **kwargs: Additional configuration options

    Returns:
        Configuration dictionary
    """
    config = {
        "max_size": max_size,
        "batch_size": batch_size,
        "overflow_strategy": overflow_strategy,
        "flush_on_config_change": True,
        "batch_timeout_ms": 100,
        "queue_check_interval_ms": 100,
        "log_queue_stats": True,
        "queue_warning_threshold": max_size - 100,
    }

    # Override defaults with any provided kwargs
    config.update(kwargs)
    return config


def create_parallel_config(
    enabled: bool = True,
    batch_size_threshold: int = 10,
    max_concurrent_tasks: int = 50,
    **kwargs,
) -> Dict[str, Any]:
    """
    Create a parallel processing configuration dictionary for testing.

    Args:
        enabled: Whether parallel processing is enabled (default: True)
        batch_size_threshold: Threshold for using parallel processing (default: 10)
        max_concurrent_tasks: Maximum concurrent tasks (default: 50)
        **kwargs: Additional configuration options

    Returns:
        Parallel configuration dictionary
    """
    config = {
        "enabled": enabled,
        "batch_size_threshold": batch_size_threshold,
        "max_concurrent_tasks": max_concurrent_tasks,
        "fallback_on_error": True,
        "processing_timeout": 30.0,
        "enable_performance_logging": True,
        "circuit_breaker": {
            "enabled": True,
            "failure_threshold": 3,
            "recovery_timeout": 60.0,
        },
    }

    # Override defaults with any provided kwargs
    config.update(kwargs)
    return config


async def wait_for_queue_size(
    queue: asyncio.Queue, expected_size: int, timeout: float = 5.0
) -> bool:
    """
    Wait for a queue to reach a specific size within a timeout.

    Args:
        queue: asyncio.Queue to monitor
        expected_size: Expected queue size
        timeout: Maximum time to wait in seconds

    Returns:
        True if queue reached expected size within timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if queue.qsize() == expected_size:
            return True
        await asyncio.sleep(0.01)  # Small delay to prevent busy waiting

    logger.warning(
        f"Queue did not reach expected size {expected_size} within "
        f"{timeout}s timeout. Current size: {queue.qsize()}"
    )
    return False


def verify_queue_metrics(metrics: Dict[str, Any], expected_keys: list = None) -> bool:
    """
    Verify that queue metrics contain expected keys and valid values.

    Args:
        metrics: Metrics dictionary to verify
        expected_keys: List of expected keys (default: standard metrics)

    Returns:
        True if metrics are valid
    """
    if expected_keys is None:
        expected_keys = ["queue_size", "queue_full", "queue_empty", "events_queued"]

    for key in expected_keys:
        if key not in metrics:
            logger.error(f"Missing expected metric key: {key}")
            return False

    # Verify basic type expectations
    if not isinstance(metrics.get("queue_size", 0), int):
        logger.error("queue_size should be an integer")
        return False

    if not isinstance(metrics.get("queue_full", False), bool):
        logger.error("queue_full should be a boolean")
        return False

    if not isinstance(metrics.get("queue_empty", True), bool):
        logger.error("queue_empty should be a boolean")
        return False

    return True
