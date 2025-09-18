"""
File: services/cot_service.py

Compatibility layer for COT service functionality.
All implementation has been moved to QueuedCOTService in services/cot_service_integration.py

This file maintains backward compatibility for existing imports while delegating
all functionality to the modern queue-based COT service implementation.
"""

from services.cot_service_integration import QueuedCOTService


def get_cot_service() -> QueuedCOTService:
    """Get the singleton COT service instance with advanced queue management"""
    from services.cot_service_integration import get_queued_cot_service
    return get_queued_cot_service()


def reset_cot_service():
    """Reset the global COT service instance (mainly for testing)"""
    from services.cot_service_integration import reset_queued_cot_service
    reset_queued_cot_service()