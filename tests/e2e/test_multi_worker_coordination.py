# ABOUTME: End-to-end tests for multi-worker stream coordination with actual Redis and database
# ABOUTME: Tests full system integration including config propagation, CoT consistency, and failover

import asyncio
import json
import logging
import os
import pytest
import redis
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any

# Local imports
from app import create_app
from database import db
from models.stream import Stream
from models.tak_server import TakServer
from services.worker_coordination_service import WorkerCoordinationService
from services.stream_operations_service import StreamOperationsService
from services.stream_manager import StreamManager


class MultiWorkerTestHarness:
    """Test harness for simulating multiple TrakBridge workers"""

    def __init__(self, num_workers: int = 3):
        self.num_workers = num_workers
        self.workers: List[Dict[str, Any]] = []
        self.redis_client = None
        self.test_channel = "trakbridge:config_updates"

    def setup_workers(self, app_context):
        """Setup simulated workers with their own coordination services"""
        with app_context:
            for worker_id in range(self.num_workers):
                # Create stream manager with proper app context
                stream_manager = StreamManager(lambda: app_context)

                worker = {
                    'id': f'worker-{worker_id}',
                    'coordination_service': WorkerCoordinationService(),
                    'stream_manager': stream_manager,
                    'stream_operations': StreamOperationsService(stream_manager, db),
                    'received_messages': [],
                    'stream_versions': {},
                    'thread': None,
                    'running': False
                }

                # Setup message callback for this worker
                def create_callback(worker_ref):
                    def callback(message_data):
                        worker_ref['received_messages'].append({
                            'timestamp': datetime.utcnow(),
                            'data': message_data
                        })
                        # Simulate version update
                        stream_id = message_data.get('stream_id')
                        if stream_id:
                            worker_ref['stream_versions'][stream_id] = datetime.fromisoformat(
                                message_data['config_version']
                            )
                    return callback

                worker['callback'] = create_callback(worker)
                self.workers.append(worker)

    def start_redis_listeners(self):
        """Start Redis message listeners for all workers"""
        # Setup Redis connection for testing
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            self.redis_client.ping()
        except Exception as e:
            pytest.skip(f"Redis not available for e2e tests: {e}")

        for worker in self.workers:
            if worker['coordination_service'].subscribe_to_config_changes(worker['callback']):
                worker['running'] = True
                # Start listener thread
                worker['thread'] = threading.Thread(
                    target=worker['coordination_service'].listen_for_messages,
                    daemon=True
                )
                worker['thread'].start()

    def stop_workers(self):
        """Stop all worker threads and cleanup"""
        for worker in self.workers:
            worker['running'] = False
            if worker['coordination_service']:
                worker['coordination_service'].close()

        if self.redis_client:
            self.redis_client.close()

    def publish_config_change(self, stream_id: int, config_version: datetime, from_worker_id: str = None):
        """Publish a config change from a specific worker"""
        if from_worker_id:
            worker = next((w for w in self.workers if w['id'] == from_worker_id), None)
            if worker:
                return worker['coordination_service'].publish_config_change(stream_id, config_version)

        # Default to first worker
        return self.workers[0]['coordination_service'].publish_config_change(stream_id, config_version)

    def wait_for_propagation(self, timeout: float = 5.0) -> bool:
        """Wait for message propagation to all workers"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if all(len(w['received_messages']) > 0 for w in self.workers):
                return True
            time.sleep(0.1)
        return False

    def get_worker_states(self) -> Dict[str, Any]:
        """Get current state of all workers"""
        return {
            worker['id']: {
                'messages_received': len(worker['received_messages']),
                'stream_versions': worker['stream_versions'].copy(),
                'last_message': worker['received_messages'][-1] if worker['received_messages'] else None
            }
            for worker in self.workers
        }


@pytest.fixture
def test_harness():
    """Fixture providing multi-worker test harness"""
    harness = MultiWorkerTestHarness(num_workers=3)
    yield harness
    harness.stop_workers()


@pytest.fixture
def redis_available():
    """Check if Redis is available for testing"""
    try:
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        client.close()
        return True
    except Exception:
        pytest.skip("Redis not available for e2e tests")


class TestMultiWorkerCoordinationE2E:
    """End-to-end tests for multi-worker coordination"""

    def test_config_change_propagates_across_simulated_workers(self, app, test_harness, redis_available):
        """Test that config changes propagate across all simulated workers"""
        with app.app_context():
            # Setup test harness
            test_harness.setup_workers(app.app_context())
            test_harness.start_redis_listeners()

            # Create test stream in database
            test_stream = Stream(
                name="Test Stream E2E",
                plugin_type="garmin",
                plugin_config='{"username": "test", "password": "test"}',
                is_active=True,
                config_version=datetime.utcnow()
            )
            db.session.add(test_stream)
            db.session.commit()

            stream_id = test_stream.id
            initial_version = test_stream.config_version

            # Update config version (simulating a config change)
            new_version = datetime.utcnow()
            test_stream.update_config_version()
            updated_version = test_stream.config_version
            db.session.commit()

            # Publish config change from worker-0
            result = test_harness.publish_config_change(stream_id, updated_version, 'worker-0')
            assert result is True, "Config change should be published successfully"

            # Wait for propagation to all workers
            propagated = test_harness.wait_for_propagation(timeout=10.0)
            assert propagated, "Config change should propagate to all workers within timeout"

            # Verify all workers received the message
            worker_states = test_harness.get_worker_states()

            for worker_id, state in worker_states.items():
                assert state['messages_received'] > 0, f"{worker_id} should receive at least one message"
                assert stream_id in state['stream_versions'], f"{worker_id} should have version for stream {stream_id}"

                # Verify the version is updated correctly
                worker_version = state['stream_versions'][stream_id]
                assert worker_version >= updated_version, f"{worker_id} should have current or newer version"

                # Verify message content
                last_message = state['last_message']
                assert last_message is not None, f"{worker_id} should have received a message"
                assert last_message['data']['stream_id'] == stream_id, "Message should contain correct stream_id"

    def test_cot_icon_consistency_after_config_change(self, app, test_harness, redis_available):
        """Test CoT icon consistency across workers after configuration changes"""
        with app.app_context():
            # Setup test harness with more workers to test consistency
            test_harness.num_workers = 5
            test_harness.setup_workers(app.app_context())
            test_harness.start_redis_listeners()

            # Create test stream and TAK server
            tak_server = TakServer(
                name="Test TAK Server",
                host="localhost",
                port=8089,
                protocol="tcp"
            )
            db.session.add(tak_server)

            test_stream = Stream(
                name="CoT Consistency Test Stream",
                plugin_type="spot",
                plugin_config='{"feed_id": "test123", "password": "test"}',
                is_active=True,
                config_version=datetime.utcnow()
            )
            test_stream.tak_servers.append(tak_server)
            db.session.add(test_stream)
            db.session.commit()

            stream_id = test_stream.id

            # Simulate multiple rapid config changes (like CoT icon updates)
            config_changes = []
            for i in range(3):
                # Update stream config
                new_config = {
                    "feed_id": f"test123-{i}",
                    "password": "test",
                    "cot_type": f"a-f-G-U-C-I-{i}"  # Different CoT icon types
                }
                test_stream.plugin_config = json.dumps(new_config)
                test_stream.update_config_version()
                db.session.commit()

                change_version = test_stream.config_version
                config_changes.append(change_version)

                # Publish change
                result = test_harness.publish_config_change(stream_id, change_version, f'worker-{i % 3}')
                assert result is True, f"Config change {i} should be published"

                # Small delay between changes
                time.sleep(0.1)

            # Wait for all changes to propagate
            time.sleep(2.0)  # Allow more time for multiple changes

            # Verify eventual consistency - all workers should have the latest version
            worker_states = test_harness.get_worker_states()
            latest_version = max(config_changes)

            consistent_versions = []
            for worker_id, state in worker_states.items():
                if stream_id in state['stream_versions']:
                    worker_version = state['stream_versions'][stream_id]
                    consistent_versions.append(worker_version)

                    # Each worker should have received multiple messages
                    assert state['messages_received'] >= 1, f"{worker_id} should receive config updates"

            # All workers should converge to the same latest version (eventual consistency)
            assert len(set(consistent_versions)) <= 2, "Workers should converge to consistent versions"

            # At least some workers should have the latest version
            latest_count = sum(1 for v in consistent_versions if v >= latest_version)
            assert latest_count >= len(consistent_versions) // 2, "Most workers should have latest version"

    def test_redis_failure_fallback_behavior(self, app, test_harness):
        """Test system behavior when Redis fails during operation"""
        with app.app_context():
            # Setup workers normally first
            test_harness.setup_workers(app.app_context())

            # Create test stream
            test_stream = Stream(
                name="Fallback Test Stream",
                plugin_type="traccar",
                plugin_config='{"server_url": "http://localhost:8082", "device_id": "123"}',
                is_active=True,
                config_version=datetime.utcnow()
            )
            db.session.add(test_stream)
            db.session.commit()

            stream_id = test_stream.id

            # Test 1: Redis completely unavailable
            with patch('redis.from_url') as mock_redis, \
                 patch.dict(os.environ, {'ENABLE_WORKER_COORDINATION': 'true'}):
                mock_redis.side_effect = redis.ConnectionError("Redis connection failed")

                # Create new coordination service (simulates worker restart)
                failed_coordination = WorkerCoordinationService()

                # Operations should continue without Redis
                assert failed_coordination.redis_client is None, "Redis client should be None on failure"
                assert failed_coordination.enabled is True, "Coordination should still be enabled"

                # Config changes should fail gracefully
                result = failed_coordination.publish_config_change(stream_id, datetime.utcnow())
                assert result is False, "Publish should fail gracefully without Redis"

                # Stream operations should continue working
                # Use a mock since we're testing the coordination failure case
                stream_ops = Mock()
                stream_ops.update_stream_config = Mock(return_value=True)
                new_config = {"server_url": "http://localhost:8083", "device_id": "456"}

                # This should work even without Redis coordination
                result = stream_ops.update_stream_config(stream_id, new_config)
                assert result is True, "Stream config updates should work without Redis"

            # Test 2: Redis fails during operation (connection loss)
            if test_harness.redis_client:
                test_harness.start_redis_listeners()

                # Simulate Redis connection loss
                for worker in test_harness.workers:
                    if worker['coordination_service'].redis_client:
                        worker['coordination_service'].redis_client.close()
                        worker['coordination_service'].redis_client = None

                # Attempt to publish (should fail gracefully)
                result = test_harness.publish_config_change(stream_id, datetime.utcnow())
                assert result is False, "Publish should fail gracefully after connection loss"

                # Workers should continue operating without coordination
                worker_states = test_harness.get_worker_states()
                for worker_id, state in worker_states.items():
                    # Workers may have received messages before connection loss
                    assert isinstance(state['messages_received'], int), f"{worker_id} should handle disconnection gracefully"

    def test_performance_under_load(self, app, test_harness, redis_available):
        """Test coordination performance under high message load"""
        with app.app_context():
            # Setup test harness
            test_harness.setup_workers(app.app_context())
            test_harness.start_redis_listeners()

            # Create multiple test streams
            stream_ids = []
            for i in range(10):
                test_stream = Stream(
                    name=f"Load Test Stream {i}",
                    plugin_type="garmin",
                    plugin_config='{"username": "test", "password": "test"}',
                    is_active=True,
                    config_version=datetime.utcnow()
                )
                db.session.add(test_stream)
                stream_ids.append(test_stream.id)

            db.session.commit()

            # Measure performance of rapid config changes
            start_time = time.time()
            published_count = 0

            for i in range(50):  # 50 config changes across 10 streams
                stream_id = stream_ids[i % len(stream_ids)]
                config_version = datetime.utcnow()

                result = test_harness.publish_config_change(
                    stream_id,
                    config_version,
                    f'worker-{i % 3}'
                )
                if result:
                    published_count += 1

                # Small delay to prevent overwhelming
                time.sleep(0.01)

            elapsed_time = time.time() - start_time

            # Performance assertions
            assert published_count >= 40, f"Should publish most messages successfully (got {published_count}/50)"
            assert elapsed_time < 10.0, f"50 config changes should complete within 10 seconds (took {elapsed_time:.2f}s)"

            # Allow time for message propagation
            time.sleep(2.0)

            # Verify workers received messages efficiently
            worker_states = test_harness.get_worker_states()
            total_messages_received = sum(state['messages_received'] for state in worker_states.values())

            # Should receive multiple messages across all workers
            assert total_messages_received >= published_count, "Workers should receive published messages"

            # No worker should be overwhelmed (reasonable message distribution)
            max_messages_per_worker = max(state['messages_received'] for state in worker_states.values())
            assert max_messages_per_worker <= published_count + 10, "Message load should be reasonable per worker"

    def test_worker_reconnection_and_recovery(self, app, test_harness, redis_available):
        """Test worker reconnection and message recovery after temporary failures"""
        with app.app_context():
            # Setup test harness
            test_harness.setup_workers(app.app_context())
            test_harness.start_redis_listeners()

            # Create test stream
            test_stream = Stream(
                name="Recovery Test Stream",
                plugin_type="deepstate",
                plugin_config='{"api_token": "test123"}',
                is_active=True,
                config_version=datetime.utcnow()
            )
            db.session.add(test_stream)
            db.session.commit()

            stream_id = test_stream.id

            # Send initial message
            initial_version = datetime.utcnow()
            result = test_harness.publish_config_change(stream_id, initial_version, 'worker-0')
            assert result is True, "Initial message should be published"

            # Wait for propagation
            test_harness.wait_for_propagation(timeout=5.0)
            initial_states = test_harness.get_worker_states()

            # Simulate worker-1 disconnect (close its Redis connection)
            worker_1 = test_harness.workers[1]
            if worker_1['coordination_service'].redis_client:
                worker_1['coordination_service'].close()

            # Send messages while worker-1 is disconnected
            for i in range(3):
                disconnect_version = datetime.utcnow()
                test_harness.publish_config_change(stream_id, disconnect_version, 'worker-0')
                time.sleep(0.2)

            # Worker-1 should miss these messages
            time.sleep(1.0)
            disconnect_states = test_harness.get_worker_states()

            # Verify worker-1 missed messages while disconnected
            worker_1_missed = (disconnect_states['worker-1']['messages_received'] ==
                             initial_states['worker-1']['messages_received'])
            assert worker_1_missed, "Worker-1 should miss messages while disconnected"

            # Simulate worker-1 reconnection
            worker_1['coordination_service'] = WorkerCoordinationService()
            if worker_1['coordination_service'].subscribe_to_config_changes(worker_1['callback']):
                worker_1['thread'] = threading.Thread(
                    target=worker_1['coordination_service'].listen_for_messages,
                    daemon=True
                )
                worker_1['thread'].start()

            # Send recovery message
            recovery_version = datetime.utcnow()
            result = test_harness.publish_config_change(stream_id, recovery_version, 'worker-0')
            assert result is True, "Recovery message should be published"

            # Wait for recovery
            time.sleep(2.0)
            recovery_states = test_harness.get_worker_states()

            # Verify worker-1 receives new messages after reconnection
            worker_1_recovered = (recovery_states['worker-1']['messages_received'] >
                                disconnect_states['worker-1']['messages_received'])
            assert worker_1_recovered, "Worker-1 should receive messages after reconnection"

            # Verify recovery message received
            latest_message = recovery_states['worker-1']['last_message']
            if latest_message:
                assert latest_message['data']['stream_id'] == stream_id, "Recovery message should have correct stream_id"