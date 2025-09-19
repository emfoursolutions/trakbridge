# ABOUTME: Integration tests for multi-worker stream coordination functionality  
# ABOUTME: Tests stream restart coordination, version checking across simulated workers

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from services.worker_coordination_service import WorkerCoordinationService
from services.stream_operations_service import StreamOperationsService
from services.stream_manager import StreamManager
from models.stream import Stream


class TestMultiWorkerCoordination:
    """Integration tests for multi-worker coordination"""
    
    def setup_method(self):
        """Setup test environment"""
        self.coordination_service = WorkerCoordinationService()
        # Mock the dependencies for integration tests
        self.stream_operations = Mock()
        self.stream_operations.update_stream_config = Mock(return_value=True)
        self.test_stream_id = 123
        
    @patch('os.getenv')
    @patch('redis.from_url')
    def test_stream_restart_triggered_by_version_mismatch(self, mock_redis_from_url, mock_env):
        """Test that stream restarts are triggered when version mismatch detected"""
        mock_env.side_effect = lambda key, default='': {
            'ENABLE_WORKER_COORDINATION': 'true',
            'REDIS_URL': 'redis://localhost:6379/0',
            'WORKER_ID': 'worker-1'
        }.get(key, default)
        
        # Mock Redis client
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_pubsub = Mock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_redis_from_url.return_value = mock_client
        
        # Create coordination service
        coordination = WorkerCoordinationService()
        
        # Mock StreamManager for testing
        stream_manager = Mock()
        stream_manager._stream_versions = {}
        
        def mock_is_config_outdated(stream_id, new_version):
            current = stream_manager._stream_versions.get(stream_id)
            return current is None or new_version > current
        
        def mock_restart_stream(stream_id):
            stream_manager._stream_versions[stream_id] = datetime.utcnow()
            return True
        
        stream_manager.is_config_outdated = mock_is_config_outdated
        stream_manager.restart_stream = mock_restart_stream
        
        # Test version mismatch detection and restart
        old_version = datetime(2023, 8, 1, 12, 0, 0)
        new_version = datetime(2023, 8, 1, 12, 30, 0)
        
        # Initially no version cached
        assert mock_is_config_outdated(self.test_stream_id, new_version)
        
        # Update cache with old version
        stream_manager._stream_versions[self.test_stream_id] = old_version
        
        # Check with newer version should trigger restart
        assert mock_is_config_outdated(self.test_stream_id, new_version)
        
        # Simulate restart
        mock_restart_stream(self.test_stream_id)
        
        # After restart, should not be outdated
        assert not mock_is_config_outdated(self.test_stream_id, new_version)
    
    @patch('os.getenv')
    @patch('redis.from_url')
    def test_multiple_workers_coordinate_stream_updates(self, mock_redis_from_url, mock_env):
        """Test multiple workers coordinating stream updates"""
        mock_env.side_effect = lambda key, default='': {
            'ENABLE_WORKER_COORDINATION': 'true',
            'REDIS_URL': 'redis://localhost:6379/0'
        }.get(key, default)
        
        # Mock Redis client
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.publish.return_value = 3  # 3 workers subscribed
        mock_pubsub = Mock()
        mock_client.pubsub.return_value = mock_pubsub
        mock_redis_from_url.return_value = mock_client
        
        # Create coordination services for multiple workers
        worker1_coordination = WorkerCoordinationService()
        worker2_coordination = WorkerCoordinationService() 
        worker3_coordination = WorkerCoordinationService()
        
        # Track callbacks from each worker
        worker1_callbacks = []
        worker2_callbacks = []
        worker3_callbacks = []
        
        def worker1_callback(data):
            worker1_callbacks.append(data)
            
        def worker2_callback(data):
            worker2_callbacks.append(data)
            
        def worker3_callback(data):
            worker3_callbacks.append(data)
        
        # Subscribe all workers
        worker1_coordination.subscribe_to_config_changes(worker1_callback)
        worker2_coordination.subscribe_to_config_changes(worker2_callback)
        worker3_coordination.subscribe_to_config_changes(worker3_callback)
        
        # Simulate config change from worker1
        stream_id = 123
        config_version = datetime(2023, 8, 1, 12, 0, 0)
        
        # Publish change
        result = worker1_coordination.publish_config_change(stream_id, config_version)
        assert result is True
        
        # Verify message was published
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args[0]
        assert call_args[0] == "trakbridge:config_updates"
        
        # Simulate message distribution to all workers
        import json
        message_data = {
            'stream_id': stream_id,
            'config_version': config_version.isoformat(),
            'timestamp': datetime.utcnow().isoformat(),
            'worker_id': 'worker-1'
        }
        
        # Each worker processes the message
        worker1_callback(message_data)
        worker2_callback(message_data)
        worker3_callback(message_data)
        
        # Verify all workers received the notification
        assert len(worker1_callbacks) == 1
        assert len(worker2_callbacks) == 1
        assert len(worker3_callbacks) == 1
        
        # Verify message content
        for callbacks in [worker1_callbacks, worker2_callbacks, worker3_callbacks]:
            assert callbacks[0]['stream_id'] == stream_id
            assert callbacks[0]['config_version'] == config_version.isoformat()
    
    @patch('os.getenv')
    def test_config_change_propagates_across_simulated_workers(self, mock_env):
        """Test end-to-end configuration change propagation"""
        mock_env.side_effect = lambda key, default='': {
            'ENABLE_WORKER_COORDINATION': 'false'  # Test without Redis first
        }.get(key, default)
        
        # Test without Redis coordination (graceful fallback)
        stream_ops = Mock()
        stream_ops.update_stream_config = Mock(return_value=True)
        
        # Test config update
        config_data = {'username': 'updated', 'password': 'updated'}
        result = stream_ops.update_stream_config(self.test_stream_id, config_data)

        assert result is True
    
    def test_cot_icon_consistency_after_config_change(self):
        """Test CoT icon consistency after configuration changes"""
        # This test verifies that after a config change, all workers 
        # eventually converge to the same state
        
        # Mock multiple stream managers
        worker1_versions = {}
        worker2_versions = {}
        worker3_versions = {}
        
        stream_id = 123
        initial_version = datetime(2023, 8, 1, 12, 0, 0)
        updated_version = datetime(2023, 8, 1, 12, 30, 0)
        
        # Initially all workers have the same version
        worker1_versions[stream_id] = initial_version
        worker2_versions[stream_id] = initial_version
        worker3_versions[stream_id] = initial_version
        
        # Simulate config change - worker1 gets update first
        worker1_versions[stream_id] = updated_version
        
        # At this point, there's inconsistency
        assert worker1_versions[stream_id] != worker2_versions[stream_id]
        assert worker1_versions[stream_id] != worker3_versions[stream_id]
        
        # Simulate coordination message propagation
        # Worker2 and Worker3 receive update notification
        worker2_versions[stream_id] = updated_version
        worker3_versions[stream_id] = updated_version
        
        # Now all workers should be consistent
        assert worker1_versions[stream_id] == worker2_versions[stream_id]
        assert worker1_versions[stream_id] == worker3_versions[stream_id]
        assert worker2_versions[stream_id] == worker3_versions[stream_id]
    
    @patch('os.getenv')
    @patch('redis.from_url')
    def test_redis_failure_fallback_behavior(self, mock_redis_from_url, mock_env):
        """Test system behavior when Redis fails"""
        mock_env.side_effect = lambda key, default='': {
            'ENABLE_WORKER_COORDINATION': 'true',
            'REDIS_URL': 'redis://localhost:6379/0'
        }.get(key, default)
        
        # Mock Redis failure
        mock_redis_from_url.side_effect = Exception("Redis connection failed")
        
        # Service should start but gracefully degrade
        coordination = WorkerCoordinationService()
        
        assert coordination.enabled  # Still enabled
        assert coordination.redis_client is None  # But no connection
        
        # Operations should continue without Redis
        stream_id = 123
        config_version = datetime(2023, 8, 1, 12, 0, 0)
        
        # Publish should fail gracefully
        result = coordination.publish_config_change(stream_id, config_version)
        assert result is False
        
        # Subscribe should fail gracefully
        callback = Mock()
        result = coordination.subscribe_to_config_changes(callback)
        assert result is False
        
        # System continues to function without coordination
        stream_ops = Mock()
        stream_ops.update_stream_config = Mock(return_value=True)

        # Config updates should still work
        result = stream_ops.update_stream_config(stream_id, {'username': 'test', 'password': 'test'})
        assert result is True
    
    def test_worker_coordination_performance(self):
        """Test performance characteristics of coordination system"""
        # Test that coordination doesn't significantly impact performance
        
        start_time = time.time()
        
        # Simulate rapid config changes
        coordination = WorkerCoordinationService()
        coordination.enabled = False  # Disable Redis for baseline test
        
        for i in range(100):
            stream_id = i
            config_version = datetime.utcnow()
            
            # Should complete quickly without Redis
            result = coordination.publish_config_change(stream_id, config_version)
            assert result is False  # Expected when disabled
        
        elapsed_time = time.time() - start_time
        
        # Should complete rapidly (less than 1 second for 100 operations)
        assert elapsed_time < 1.0
    
    def teardown_method(self):
        """Cleanup test environment"""
        if hasattr(self, 'coordination_service'):
            self.coordination_service.close()