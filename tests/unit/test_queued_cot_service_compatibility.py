"""Unit tests for QueuedCOTService backward compatibility."""

from unittest.mock import Mock, patch

import pytest

from services.cot_service import get_cot_service, reset_cot_service


class TestQueuedCOTServiceCompatibility:
    """Test backward compatibility properties of QueuedCOTService."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset the singleton before and after each test."""
        reset_cot_service()
        yield
        reset_cot_service()

    @pytest.fixture
    def mock_queue_manager(self):
        """Create a mock queue manager."""
        queue_manager = Mock()
        queue_manager.queues = {1: Mock(), 2: Mock()}
        return queue_manager

    @pytest.fixture
    def mock_monitoring_service(self):
        """Create a mock monitoring service."""
        return Mock()

    def test_queues_property_delegates_to_queue_manager(
        self, mock_queue_manager, mock_monitoring_service
    ):
        """Test that the queues property correctly delegates to queue_manager.queues."""
        with (
            patch(
                "services.cot_service_integration.get_queue_manager",
                return_value=mock_queue_manager,
            ),
            patch(
                "services.cot_service_integration.get_queue_monitoring_service",
                return_value=mock_monitoring_service,
            ),
        ):

            # Create service using singleton
            service = get_cot_service()

            # Test that queues property returns queue_manager.queues
            assert service.queues is mock_queue_manager.queues
            assert service.queues == {
                1: mock_queue_manager.queues[1],
                2: mock_queue_manager.queues[2],
            }

    def test_queues_property_reflects_queue_manager_changes(
        self, mock_queue_manager, mock_monitoring_service
    ):
        """Test that the queues property reflects changes in queue_manager.queues."""
        with (
            patch(
                "services.cot_service_integration.get_queue_manager",
                return_value=mock_queue_manager,
            ),
            patch(
                "services.cot_service_integration.get_queue_monitoring_service",
                return_value=mock_monitoring_service,
            ),
        ):

            # Create service using singleton
            service = get_cot_service()

            # Initially has 2 queues
            assert len(service.queues) == 2

            # Add a queue to the queue manager
            mock_queue_manager.queues[3] = Mock()

            # Service should reflect the change
            assert len(service.queues) == 3
            assert 3 in service.queues

    def test_backward_compatibility_with_len_access(
        self, mock_queue_manager, mock_monitoring_service
    ):
        """Test that len(service.queues) works as expected for backward compatibility."""
        with (
            patch(
                "services.cot_service_integration.get_queue_manager",
                return_value=mock_queue_manager,
            ),
            patch(
                "services.cot_service_integration.get_queue_monitoring_service",
                return_value=mock_monitoring_service,
            ),
        ):

            # Create service using singleton
            service = get_cot_service()

            # Test len() access - this is what was failing in stream_worker.py
            assert len(service.queues) == 2

    def test_backward_compatibility_with_key_access(
        self, mock_queue_manager, mock_monitoring_service
    ):
        """Test that service.queues[key] works as expected for backward compatibility."""
        with (
            patch(
                "services.cot_service_integration.get_queue_manager",
                return_value=mock_queue_manager,
            ),
            patch(
                "services.cot_service_integration.get_queue_monitoring_service",
                return_value=mock_monitoring_service,
            ),
        ):

            # Create service using singleton
            service = get_cot_service()

            # Test key access
            assert service.queues[1] is mock_queue_manager.queues[1]
            assert service.queues[2] is mock_queue_manager.queues[2]

    def test_backward_compatibility_with_iteration(
        self, mock_queue_manager, mock_monitoring_service
    ):
        """Test that iterating over service.queues works as expected."""
        with (
            patch(
                "services.cot_service_integration.get_queue_manager",
                return_value=mock_queue_manager,
            ),
            patch(
                "services.cot_service_integration.get_queue_monitoring_service",
                return_value=mock_monitoring_service,
            ),
        ):

            # Create service using singleton
            service = get_cot_service()

            # Test iteration over keys
            queue_ids = list(service.queues.keys())
            assert queue_ids == [1, 2]

            # Test 'in' operator
            assert 1 in service.queues
            assert 2 in service.queues
            assert 3 not in service.queues
