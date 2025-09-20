"""
ABOUTME: Unit tests for queue management functionality according to TDD Phase 1 specification
ABOUTME: Tests core queue behavior including size limits, overflow handling, and batch transmission

This module contains the core queue behavior tests as specified in the Queue Management
Specification Phase 1 (Red Phase). These tests are designed to fail initially and drive
the implementation of bounded queues with configurable overflow strategies.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from services.cot_service_integration import QueuedCOTService
from models.tak_server import TakServer
from models.stream import Stream


class TestQueueSizeManagement:
    """Test queue size limits and bounds enforcement"""
    
    @pytest.mark.asyncio
    async def test_queue_respects_max_size_limit(self):
        """Queue should not exceed configured maximum size"""
        max_queue_size = 5
        
        # Mock configuration with small queue size for testing
        with patch('services.cot_service.QueuedCOTService._get_queue_config') as mock_config:
            mock_config.return_value = {'max_size': max_queue_size}
            
            cot_service = QueuedCOTService()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)
            
            # Create a queue for this TAK server
            queue = await cot_service._get_or_create_queue(tak_server.id)
            
            # Add events up to the limit
            for i in range(max_queue_size):
                test_event = self._create_test_event(f"test-{i}")
                await cot_service.queue_event(tak_server.id, test_event)
            
            # Verify queue is at maximum capacity
            assert queue.qsize() == max_queue_size
            
            # Attempt to add one more event - should not exceed limit
            overflow_event = self._create_test_event("overflow")
            await cot_service.queue_event(tak_server.id, overflow_event)
            
            # Queue should still be at max size (oldest event dropped)
            assert queue.qsize() == max_queue_size

    @pytest.mark.asyncio
    async def test_overflow_drops_oldest_events(self):
        """When queue is full, oldest events should be dropped (FIFO)"""
        max_queue_size = 3
        
        with patch('services.cot_service.QueuedCOTService._get_queue_config') as mock_config:
            mock_config.return_value = {
                'max_size': max_queue_size,
                'overflow_strategy': 'drop_oldest'
            }
            
            cot_service = QueuedCOTService()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)
            
            queue = await cot_service._get_or_create_queue(tak_server.id)
            
            # Add initial events
            events = []
            for i in range(max_queue_size):
                event = self._create_test_event(f"event-{i}")
                events.append(event)
                await cot_service.queue_event(tak_server.id, event)
            
            # Add overflow event - should drop the oldest (event-0)
            overflow_event = self._create_test_event("overflow")
            await cot_service.queue_event(tak_server.id, overflow_event)
            
            # Verify queue size is still at maximum
            assert queue.qsize() == max_queue_size
            
            # Extract all events and verify oldest was dropped
            remaining_events = []
            while not queue.empty():
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                remaining_events.append(event)
            
            # Should contain event-1, event-2, and overflow (event-0 dropped)
            event_uids = [event.get('uid', '') for event in remaining_events]
            assert 'event-0' not in str(event_uids)
            assert 'overflow' in str(event_uids)

    @pytest.mark.asyncio 
    async def test_queue_batch_transmission(self):
        """Events should be transmitted in configurable small batches"""
        batch_size = 3
        
        with patch('services.cot_service.QueuedCOTService._get_transmission_config') as mock_config:
            mock_config.return_value = {
                'batch_size': batch_size,
                'batch_timeout_ms': 100
            }
            
            cot_service = QueuedCOTService()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)
            
            # Mock the transmission method
            transmitted_batches = []
            async def mock_transmit_batch(events, server):
                transmitted_batches.append(len(events))
            
            with patch.object(cot_service, '_transmit_events_batch', side_effect=mock_transmit_batch):
                # Queue multiple events
                for i in range(7):  # More than one batch
                    event = self._create_test_event(f"batch-event-{i}")
                    await cot_service.queue_event(tak_server.id, event)
                
                # Trigger batch transmission
                await cot_service._process_transmission_batches(tak_server.id)
                
                # Should have transmitted in batches of specified size
                assert len(transmitted_batches) >= 2  # At least 2 batches
                assert all(batch_size <= size <= batch_size for size in transmitted_batches[:-1])  # All but last should be full batches
                assert sum(transmitted_batches) == 7  # All events transmitted

    @pytest.mark.asyncio
    async def test_configuration_change_flushes_queue(self):
        """Configuration changes should trigger immediate queue flush"""
        with patch('services.cot_service.QueuedCOTService._get_queue_config') as mock_config:
            mock_config.return_value = {
                'max_size': 10,
                'flush_on_config_change': True
            }
            
            cot_service = QueuedCOTService()
            tak_server = TakServer(id=1, name="test", host="localhost", port=8089)
            
            # Add events to queue
            for i in range(5):
                event = self._create_test_event(f"pre-config-{i}")
                await cot_service.queue_event(tak_server.id, event)
            
            queue = await cot_service._get_or_create_queue(tak_server.id)
            assert queue.qsize() == 5
            
            # Simulate configuration change
            await cot_service.handle_configuration_change(tak_server.id)
            
            # Queue should be flushed (empty)
            assert queue.qsize() == 0

    def _create_test_event(self, uid: str) -> Dict[str, Any]:
        """Helper method to create test COT events"""
        return {
            'uid': uid,
            'time': time.time(),
            'type': 'a-f-G-U-C',
            'lat': 40.7128,
            'lon': -74.0060,
            'hae': 10.0,
            'callsign': f'Test-{uid}'
        }


class TestQueuePerformanceCompatibility:
    """Test performance requirements and compatibility with existing systems"""
    
    @pytest.mark.asyncio
    async def test_parallel_processing_performance_maintained(self):
        """Queue changes should not impact parallel input processing"""
        # This test verifies that queue modifications don't slow down parallel processing
        start_time = time.time()
        
        cot_service = QueuedCOTService()
        tak_servers = [
            TakServer(id=i, name=f"server-{i}", host="localhost", port=8089+i)
            for i in range(1, 4)
        ]
        
        # Process events in parallel across multiple servers
        tasks = []
        for server in tak_servers:
            for i in range(10):
                event = self._create_test_event(f"parallel-{server.id}-{i}")
                task = asyncio.create_task(cot_service.queue_event(server.id, event))
                tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        processing_time = time.time() - start_time
        
        # Performance requirement: should complete within reasonable time
        # This is a baseline - actual threshold needs benchmarking
        assert processing_time < 5.0, f"Parallel processing took {processing_time}s, expected < 5.0s"

    @pytest.mark.asyncio
    async def test_existing_monitoring_metrics_preserved(self):
        """All existing monitoring and metrics should remain functional"""
        cot_service = QueuedCOTService()
        tak_server = TakServer(id=1, name="test", host="localhost", port=8089)
        
        # Add some events
        for i in range(3):
            event = self._create_test_event(f"metric-{i}")
            await cot_service.queue_event(tak_server.id, event)
        
        # Get monitoring metrics
        metrics = await cot_service.get_queue_metrics(tak_server.id)
        
        # Verify expected metrics are present
        required_metrics = ['queue_size', 'queue_full', 'queue_empty', 'events_queued']
        for metric in required_metrics:
            assert metric in metrics, f"Required metric '{metric}' missing from monitoring"
        
        # Verify metric values are reasonable
        assert isinstance(metrics['queue_size'], int)
        assert isinstance(metrics['queue_full'], bool)
        assert isinstance(metrics['queue_empty'], bool)

    @pytest.mark.asyncio
    async def test_configurable_settings_applied(self):
        """All queue settings should be configurable via config files"""
        test_config = {
            'queue': {
                'max_size': 250,
                'batch_size': 12,
                'overflow_strategy': 'drop_newest',
                'flush_on_config_change': False
            },
            'transmission': {
                'batch_timeout_ms': 200,
                'queue_check_interval_ms': 75
            }
        }
        
        with patch('services.cot_service.QueuedCOTService._load_queue_configuration') as mock_load:
            mock_load.return_value = test_config
            
            cot_service = QueuedCOTService()
            config = await cot_service._get_queue_config()
            
            # Verify all configuration values are applied
            assert config['max_size'] == 250
            assert config['batch_size'] == 12
            assert config['overflow_strategy'] == 'drop_newest'
            assert config['flush_on_config_change'] == False

    def _create_test_event(self, uid: str) -> Dict[str, Any]:
        """Helper method to create test COT events"""
        return {
            'uid': uid,
            'time': time.time(),
            'type': 'a-f-G-U-C',
            'lat': 40.7128,
            'lon': -74.0060,
            'hae': 10.0,
            'callsign': f'Test-{uid}'
        }


class TestQueueConfiguration:
    """Test queue configuration loading and validation"""
    
    @pytest.mark.asyncio
    async def test_default_configuration_values(self):
        """Test that default configuration values are properly set"""
        cot_service = QueuedCOTService()
        config = await cot_service._get_queue_config()
        
        # Verify default values match specification
        assert config.get('max_size', 0) >= 500  # Default from spec
        assert config.get('batch_size', 0) >= 8   # Default from spec
        assert config.get('overflow_strategy') in ['drop_oldest', 'drop_newest', 'block']

    @pytest.mark.asyncio
    async def test_environment_variable_override(self):
        """Test that environment variables override config file values"""
        with patch.dict('os.environ', {
            'QUEUE_MAX_SIZE': '750',
            'QUEUE_BATCH_SIZE': '15',
            'QUEUE_OVERFLOW_STRATEGY': 'drop_newest'
        }):
            cot_service = QueuedCOTService()
            config = await cot_service._get_queue_config()
            
            assert config['max_size'] == 750
            assert config['batch_size'] == 15
            assert config['overflow_strategy'] == 'drop_newest'

    @pytest.mark.asyncio
    async def test_invalid_configuration_handled(self):
        """Test that invalid configuration values are handled gracefully"""
        invalid_config = {
            'queue': {
                'max_size': -10,  # Invalid: negative
                'batch_size': 0,   # Invalid: zero
                'overflow_strategy': 'invalid_strategy'  # Invalid: unknown strategy
            }
        }
        
        with patch('services.cot_service.QueuedCOTService._load_queue_configuration') as mock_load:
            mock_load.return_value = invalid_config
            
            cot_service = QueuedCOTService()
            
            # Should fallback to safe defaults
            config = await cot_service._get_queue_config()
            assert config['max_size'] > 0
            assert config['batch_size'] > 0
            assert config['overflow_strategy'] in ['drop_oldest', 'drop_newest', 'block']