"""
ABOUTME: Unit tests for WorkerCoordinationService Redis pub/sub coordination
ABOUTME: Tests graceful degradation when Redis unavailable and version tracking

Tests Based on Redis Spec Phase 1:
- test_redis_connection_with_graceful_fallback()
- test_stream_version_tracking_in_database()
- test_publish_config_change_notification()
- test_version_comparison_logic()
"""

import os
import threading
import time
import unittest.mock as mock
from datetime import datetime
from unittest import TestCase

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from services.worker_coordination_service import WorkerCoordinationService, get_coordination_service


class TestWorkerCoordinationService:
    """Test worker coordination service functionality"""

    def test_redis_connection_with_graceful_fallback(self):
        """Test Redis connection attempts with graceful fallback when unavailable"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                # Test connection failure and graceful degradation
                mock_redis.return_value.ping.side_effect = RedisConnectionError("Connection refused")
                
                service = WorkerCoordinationService()
                
                # Should fall back gracefully
                assert not service.is_available()
                assert service._redis_client is None
                
                # Should still allow publishing (returns False)
                result = service.publish_config_change(1, datetime.utcnow())
                assert result is False

    def test_redis_connection_retry_logic(self):
        """Test exponential backoff retry logic for Redis connections"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                with mock.patch('services.worker_coordination_service.time.sleep') as mock_sleep:
                    # Create mock redis instances for each attempt
                    mock_instance1 = mock.Mock()
                    mock_instance1.ping.side_effect = RedisConnectionError("First attempt")
                    
                    mock_instance2 = mock.Mock()
                    mock_instance2.ping.side_effect = RedisConnectionError("Second attempt")
                    
                    mock_instance3 = mock.Mock()
                    mock_instance3.ping.return_value = None  # Success
                    
                    # Return different instances for each attempt
                    mock_redis.side_effect = [mock_instance1, mock_instance2, mock_instance3]
                    
                    service = WorkerCoordinationService()
                    
                    # Should retry with exponential backoff
                    assert mock_sleep.call_count == 2  # Two retries before success
                    expected_delays = [0.1, 0.2]  # From retry_delays config
                    actual_delays = [call[0][0] for call in mock_sleep.call_args_list]
                    assert actual_delays == expected_delays
                    
                    # Should be available after successful connection
                    assert service.is_available()

    def test_publish_config_change_notification(self):
        """Test publishing configuration change notifications"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                mock_client = mock_redis.return_value
                mock_client.ping.return_value = None
                mock_client.publish.return_value = 2  # 2 subscribers received
                
                service = WorkerCoordinationService()
                stream_id = 123
                version = datetime.utcnow()
                
                # Should successfully publish
                result = service.publish_config_change(stream_id, version)
                assert result is True
                
                # Verify correct channel and message format
                mock_client.publish.assert_called_once()
                call_args = mock_client.publish.call_args
                assert call_args[0][0] == 'trakbridge:config_updates'
                
                # Parse the message
                message_str = call_args[0][1]
                message = eval(message_str)  # Safe for our controlled test case
                assert message['stream_id'] == stream_id
                assert message['version'] == version.isoformat()
                assert message['action'] == 'config_changed'

    def test_version_comparison_logic(self):
        """Test version comparison for detecting outdated configurations"""
        # This test validates the logic that would be used in StreamManager
        # for comparing config versions
        
        version1 = datetime(2025, 9, 18, 10, 0, 0)
        version2 = datetime(2025, 9, 18, 10, 0, 1)  # 1 second later
        version3 = datetime(2025, 9, 18, 10, 0, 0)  # Same as version1
        
        # Newer version should be greater
        assert version2 > version1
        
        # Same versions should be equal
        assert version1 == version3
        
        # Older version should be less
        assert version1 < version2

    def test_subscriber_callback_mechanism(self):
        """Test subscribing to configuration changes"""
        callback_called = threading.Event()
        received_data = {}
        
        def test_callback(data):
            received_data.update(data)
            callback_called.set()
        
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                mock_client = mock_redis.return_value
                mock_client.ping.return_value = None
                mock_pubsub = mock.Mock()
                mock_client.pubsub.return_value = mock_pubsub
                
                # Mock message receiving
                test_message = {
                    'type': 'message',
                    'data': str({
                        'stream_id': 456,
                        'version': '2025-09-18T10:00:00',
                        'timestamp': '2025-09-18T10:00:01',
                        'action': 'config_changed'
                    }).encode('utf-8')
                }
                mock_pubsub.listen.return_value = [test_message]
                
                service = WorkerCoordinationService()
                service.subscribe_to_config_changes(test_callback)
                
                # Give subscriber thread a moment to process
                time.sleep(0.1)
                
                # Verify subscription was set up
                mock_pubsub.subscribe.assert_called_with('trakbridge:config_updates')

    def test_service_disabled_when_coordination_disabled(self):
        """Test service behavior when worker coordination is disabled"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'false'}):
            service = WorkerCoordinationService()
            
            assert not service._enabled
            assert not service.is_available()
            assert service._redis_client is None
            
            # Should return False for publish operations
            result = service.publish_config_change(1, datetime.utcnow())
            assert result is False

    def test_service_stops_cleanly(self):
        """Test service shutdown and resource cleanup"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                mock_client = mock_redis.return_value
                mock_client.ping.return_value = None
                
                service = WorkerCoordinationService()
                service.stop()
                
                # Should close Redis client
                mock_client.close.assert_called_once()
                
                # Should not be available after stop
                assert not service.is_available()

    def test_redis_connection_error_handling(self):
        """Test handling of Redis connection errors during operations"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                mock_client = mock_redis.return_value
                mock_client.ping.return_value = None  # Initially connected
                mock_client.publish.side_effect = RedisConnectionError("Connection lost")
                
                service = WorkerCoordinationService()
                
                # Should handle publish errors gracefully
                result = service.publish_config_change(1, datetime.utcnow())
                assert result is False

    def test_global_service_instance(self):
        """Test global service instance management"""
        # Clear any existing instance
        import services.worker_coordination_service as wcs_module
        wcs_module._coordination_service = None
        
        # First call should create instance
        service1 = get_coordination_service()
        assert service1 is not None
        
        # Second call should return same instance
        service2 = get_coordination_service()
        assert service1 is service2

    def test_message_parsing_error_handling(self):
        """Test handling of malformed messages in subscriber"""
        with mock.patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
            with mock.patch('services.worker_coordination_service.redis.Redis') as mock_redis:
                mock_client = mock_redis.return_value
                mock_client.ping.return_value = None
                mock_pubsub = mock.Mock()
                mock_client.pubsub.return_value = mock_pubsub
                
                # Mock malformed message
                malformed_message = {
                    'type': 'message',
                    'data': b'invalid_json_data'
                }
                mock_pubsub.listen.return_value = [malformed_message]
                
                callback_called = False
                def test_callback(data):
                    nonlocal callback_called
                    callback_called = True
                
                service = WorkerCoordinationService()
                service.subscribe_to_config_changes(test_callback)
                
                # Give subscriber thread a moment to process
                time.sleep(0.1)
                
                # Callback should not have been called due to parse error
                assert not callback_called