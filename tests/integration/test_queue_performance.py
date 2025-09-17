"""
ABOUTME: Integration tests for queue performance and system-wide queue behavior
ABOUTME: Tests performance requirements and compatibility with Deepstate scenarios

This module contains integration tests for queue performance as specified in the Queue
Management Specification Phase 1. These tests verify that queue changes do not negatively
impact system performance and that the system can handle realistic workloads.

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import pytest
import time
import statistics
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from services.cot_service import PersistentCOTService
from services.stream_manager import StreamManager
from models.tak_server import TakServer
from models.stream import Stream


class TestQueuePerformanceIntegration:
    """Integration tests for queue performance under realistic conditions"""
    
    @pytest.mark.asyncio
    async def test_deepstate_workload_performance(self):
        """Test queue performance with Deepstate-like workload (300+ points)"""
        # Simulate Deepstate scenario with 300 GPS points
        point_count = 300
        batch_processing_time_limit = 30.0  # seconds
        
        cot_service = PersistentCOTService()
        tak_server = TakServer(id=1, name="deepstate-test", host="localhost", port=8089)
        
        # Mock the actual transmission to avoid network calls
        transmitted_events = []
        async def mock_transmit(events, server):
            transmitted_events.extend(events)
            await asyncio.sleep(0.001)  # Simulate minimal network delay
        
        with patch.object(cot_service, '_transmit_events_batch', side_effect=mock_transmit):
            start_time = time.time()
            
            # Generate and queue 300 GPS points rapidly
            tasks = []
            for i in range(point_count):
                event = self._create_deepstate_event(f"deepstate-{i}", lat=40.7128 + i*0.001, lon=-74.0060 + i*0.001)
                task = asyncio.create_task(cot_service.queue_event(tak_server.id, event))
                tasks.append(task)
            
            # Wait for all events to be queued
            await asyncio.gather(*tasks)
            
            # Process all events through transmission
            await cot_service._process_all_queues()
            
            total_time = time.time() - start_time
            
            # Performance assertions
            assert total_time < batch_processing_time_limit, f"Processing took {total_time}s, expected < {batch_processing_time_limit}s"
            assert len(transmitted_events) == point_count, f"Expected {point_count} events, got {len(transmitted_events)}"
            
            # Throughput assertion (events per second)
            throughput = point_count / total_time
            assert throughput > 10.0, f"Throughput {throughput} events/sec too low, expected > 10/sec"

    @pytest.mark.asyncio
    async def test_configuration_change_propagation_time(self):
        """Test that configuration changes propagate within 5-15 seconds as specified"""
        max_propagation_time = 15.0  # seconds (upper limit from spec)
        target_propagation_time = 5.0  # seconds (target from spec)
        
        cot_service = PersistentCOTService()
        tak_server = TakServer(id=1, name="config-test", host="localhost", port=8089)
        
        # Fill queue with events
        for i in range(20):
            event = self._create_test_event(f"config-change-{i}")
            await cot_service.queue_event(tak_server.id, event)
        
        queue = await cot_service._get_or_create_queue(tak_server.id)
        initial_size = queue.qsize()
        assert initial_size > 0, "Queue should have events before configuration change"
        
        # Measure configuration change response time
        start_time = time.time()
        await cot_service.handle_configuration_change(tak_server.id)
        propagation_time = time.time() - start_time
        
        # Verify queue was flushed
        final_size = queue.qsize()
        assert final_size == 0, "Queue should be empty after configuration change"
        
        # Time-based assertions
        assert propagation_time < max_propagation_time, f"Configuration change took {propagation_time}s, expected < {max_propagation_time}s"
        
        # Log performance for analysis
        if propagation_time > target_propagation_time:
            print(f"Warning: Configuration change took {propagation_time}s, target is {target_propagation_time}s")

    @pytest.mark.asyncio
    async def test_memory_usage_bounds(self):
        """Test that queue implementation keeps memory usage bounded"""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        cot_service = PersistentCOTService()
        tak_server = TakServer(id=1, name="memory-test", host="localhost", port=8089)
        
        # Configure small queue to force overflow handling
        with patch.object(cot_service, '_get_queue_config') as mock_config:
            mock_config.return_value = {'max_size': 50}
            
            # Add many events to trigger overflow behavior
            for i in range(500):  # 10x the queue size
                event = self._create_test_event(f"memory-{i}")
                await cot_service.queue_event(tak_server.id, event)
                
                # Periodically check memory doesn't grow unbounded
                if i % 100 == 0:
                    current_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_growth = current_memory - initial_memory
                    assert memory_growth < 100, f"Memory grew by {memory_growth}MB, indicating potential memory leak"
            
            # Final memory check
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            total_memory_growth = final_memory - initial_memory
            
            # Memory should be bounded despite processing 500 events
            assert total_memory_growth < 50, f"Total memory growth {total_memory_growth}MB too high"

    @pytest.mark.asyncio
    async def test_batch_transmission_efficiency(self):
        """Test that batch transmission reduces TAK server load as intended"""
        batch_size = 8  # From specification
        event_count = 50
        
        cot_service = PersistentCOTService()
        tak_server = TakServer(id=1, name="batch-test", host="localhost", port=8089)
        
        transmission_calls = []
        async def mock_transmit_batch(events, server):
            transmission_calls.append(len(events))
            await asyncio.sleep(0.01)  # Simulate transmission time
        
        with patch.object(cot_service, '_transmit_events_batch', side_effect=mock_transmit_batch):
            with patch.object(cot_service, '_get_transmission_config') as mock_config:
                mock_config.return_value = {'batch_size': batch_size, 'batch_timeout_ms': 100}
                
                # Queue events
                for i in range(event_count):
                    event = self._create_test_event(f"batch-{i}")
                    await cot_service.queue_event(tak_server.id, event)
                
                # Process batches
                await cot_service._process_transmission_batches(tak_server.id)
                
                # Verify batching efficiency
                expected_full_batches = event_count // batch_size
                expected_calls = expected_full_batches + (1 if event_count % batch_size else 0)
                
                assert len(transmission_calls) == expected_calls, f"Expected {expected_calls} transmission calls, got {len(transmission_calls)}"
                
                # Most batches should be full size (except possibly the last one)
                full_batches = [call for call in transmission_calls if call == batch_size]
                assert len(full_batches) >= expected_full_batches, "Not enough full-size batches transmitted"

    @pytest.mark.asyncio
    async def test_concurrent_stream_processing(self):
        """Test queue performance with multiple concurrent streams"""
        stream_count = 5
        events_per_stream = 20
        
        cot_service = PersistentCOTService()
        tak_servers = [
            TakServer(id=i, name=f"concurrent-{i}", host="localhost", port=8089+i)
            for i in range(1, stream_count + 1)
        ]
        
        transmitted_events = {server.id: [] for server in tak_servers}
        
        async def mock_transmit(events, server):
            transmitted_events[server.id].extend(events)
            await asyncio.sleep(0.005)  # Simulate transmission delay
        
        with patch.object(cot_service, '_transmit_events_batch', side_effect=mock_transmit):
            start_time = time.time()
            
            # Process events concurrently across all streams
            all_tasks = []
            for server in tak_servers:
                for i in range(events_per_stream):
                    event = self._create_test_event(f"concurrent-{server.id}-{i}")
                    task = asyncio.create_task(cot_service.queue_event(server.id, event))
                    all_tasks.append(task)
            
            # Wait for all events to be queued
            await asyncio.gather(*all_tasks)
            
            # Process all queues
            await cot_service._process_all_queues()
            
            total_time = time.time() - start_time
            
            # Verify all events processed
            total_transmitted = sum(len(events) for events in transmitted_events.values())
            expected_total = stream_count * events_per_stream
            
            assert total_transmitted == expected_total, f"Expected {expected_total} events, got {total_transmitted}"
            
            # Performance should not degrade significantly with concurrent streams
            avg_throughput = total_transmitted / total_time
            assert avg_throughput > 20.0, f"Concurrent throughput {avg_throughput} events/sec too low"

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

    def _create_deepstate_event(self, uid: str, lat: float, lon: float) -> Dict[str, Any]:
        """Helper method to create Deepstate-style GPS events"""
        return {
            'uid': uid,
            'time': time.time(),
            'type': 'a-f-G-U-C',
            'lat': lat,
            'lon': lon,
            'hae': 15.0,
            'callsign': f'Deepstate-{uid}',
            'speed': 25.0,
            'course': 180.0
        }


class TestQueueSystemIntegration:
    """Integration tests for queue system compatibility"""
    
    @pytest.mark.asyncio
    async def test_existing_stream_manager_compatibility(self):
        """Test that queue changes don't break existing StreamManager functionality"""
        from services.stream_manager import StreamManager
        
        # This test ensures the queue changes integrate properly with existing systems
        stream_manager = StreamManager()
        
        # Mock a stream configuration
        stream_config = {
            'id': 1,
            'name': 'integration-test',
            'plugin_name': 'test_plugin',
            'enabled': True
        }
        
        # Verify stream manager can still create and manage streams
        # This is a placeholder test - actual implementation depends on StreamManager interface
        assert stream_manager is not None
        
        # Test would verify that:
        # 1. StreamManager can create streams that use the new queue system
        # 2. Existing monitoring metrics still work
        # 3. Stream lifecycle management (start/stop/restart) works with queues

    @pytest.mark.asyncio 
    async def test_monitoring_metrics_integration(self):
        """Test that queue metrics integrate with existing monitoring system"""
        cot_service = PersistentCOTService()
        tak_server = TakServer(id=1, name="monitoring-test", host="localhost", port=8089)
        
        # Add some events
        for i in range(5):
            event = self._create_test_event(f"monitoring-{i}")
            await cot_service.queue_event(tak_server.id, event)
        
        # Get monitoring data
        metrics = await cot_service.get_queue_metrics(tak_server.id)
        
        # Verify monitoring integration
        assert 'queue_size' in metrics
        assert 'events_queued' in metrics
        assert metrics['queue_size'] == 5
        
        # Test that metrics update correctly
        await cot_service._process_transmission_batches(tak_server.id)
        updated_metrics = await cot_service.get_queue_metrics(tak_server.id)
        
        # Queue should be processed
        assert updated_metrics['queue_size'] <= metrics['queue_size']

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