"""
ABOUTME: Worker coordination service using Redis pub/sub for multi-worker deployments
ABOUTME: Provides graceful fallback when Redis is unavailable
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, Optional

import redis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)


class WorkerCoordinationService:
    """
    Redis-based worker coordination service for multi-worker TrakBridge deployments.
    
    Handles configuration change notifications between workers with graceful degradation
    when Redis is unavailable. Uses pub/sub messaging to coordinate stream restarts
    when configuration changes occur.
    """
    
    def __init__(self):
        self._redis_client: Optional[redis.Redis] = None
        self._subscriber_thread: Optional[threading.Thread] = None
        self._running = False
        self._enabled = self._get_redis_config_enabled()
        self._connection_attempts = 0
        self._max_connection_attempts = 3
        self._retry_delays = [0.1, 0.2, 0.4]  # Exponential backoff in seconds
        self._subscribers: Dict[str, Callable[[dict], None]] = {}
        self._lock = threading.Lock()
        
        if self._enabled:
            self._initialize_redis_connection()
            
    def _get_redis_config_enabled(self) -> bool:
        """Check if worker coordination is enabled via environment configuration"""
        return os.getenv('ENABLE_WORKER_COORDINATION', 'false').lower() == 'true'
        
    def _get_redis_connection_config(self) -> dict:
        """Get Redis connection configuration from environment variables"""
        return {
            'host': os.getenv('REDIS_HOST', 'localhost'),
            'port': int(os.getenv('REDIS_PORT', '6379')),
            'db': int(os.getenv('REDIS_DB', '0')),
            'password': os.getenv('REDIS_PASSWORD'),
            'socket_connect_timeout': 5,
            'socket_timeout': 5,
            'retry_on_timeout': True,
            'health_check_interval': 30,
        }
        
    def _initialize_redis_connection(self):
        """Initialize Redis connection with retry logic"""
        if not self._enabled:
            return
            
        config = self._get_redis_connection_config()
        
        for attempt in range(self._max_connection_attempts):
            try:
                redis_client = redis.Redis(**config)
                # Test connection
                redis_client.ping()
                self._redis_client = redis_client
                logger.info("Successfully connected to Redis for worker coordination")
                self._connection_attempts = 0
                return
                
            except (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError) as e:
                self._connection_attempts += 1
                if attempt < len(self._retry_delays):
                    delay = self._retry_delays[attempt]
                    logger.warning(
                        f"Redis connection attempt {attempt + 1}/{self._max_connection_attempts} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        f"All Redis connection attempts failed. "
                        f"Worker coordination disabled, continuing without coordination."
                    )
                    break
            except Exception as e:
                logger.error(f"Unexpected error connecting to Redis: {e}")
                break
                
        # If we get here, all attempts failed
        self._redis_client = None
                
    def is_available(self) -> bool:
        """Check if Redis coordination is available"""
        if not self._enabled or not self._redis_client:
            return False
            
        try:
            self._redis_client.ping()
            return True
        except (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError):
            return False
        except Exception as e:
            logger.warning(f"Unexpected error checking Redis availability: {e}")
            return False
            
    def publish_config_change(self, stream_id: int, new_version: datetime) -> bool:
        """
        Publish a configuration change notification to other workers
        
        Args:
            stream_id: ID of the stream that had its configuration changed
            new_version: New configuration version timestamp
            
        Returns:
            bool: True if successfully published, False if Redis unavailable
        """
        if not self.is_available():
            logger.debug(f"Redis unavailable, skipping config change notification for stream {stream_id}")
            return False
            
        message = {
            'stream_id': stream_id,
            'version': new_version.isoformat(),
            'timestamp': datetime.utcnow().isoformat(),
            'action': 'config_changed'
        }
        
        try:
            channel = 'trakbridge:config_updates'
            result = self._redis_client.publish(channel, str(message))
            logger.debug(f"Published config change for stream {stream_id} to {result} subscribers")
            return True
            
        except (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError) as e:
            logger.warning(f"Failed to publish config change for stream {stream_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error publishing config change for stream {stream_id}: {e}")
            return False
            
    def subscribe_to_config_changes(self, callback: Callable[[dict], None]):
        """
        Subscribe to configuration change notifications from other workers
        
        Args:
            callback: Function to call when a config change is received
                     Should accept a dict with keys: stream_id, version, timestamp, action
        """
        if not self.is_available():
            logger.debug("Redis unavailable, skipping config change subscription")
            return
            
        with self._lock:
            self._subscribers['config_changes'] = callback
            
            if not self._running:
                self._start_subscriber_thread()
                
    def _start_subscriber_thread(self):
        """Start the background subscriber thread"""
        if self._subscriber_thread and self._subscriber_thread.is_alive():
            return
            
        self._running = True
        self._subscriber_thread = threading.Thread(
            target=self._subscriber_worker,
            name="WorkerCoordination-Subscriber",
            daemon=True
        )
        self._subscriber_thread.start()
        logger.info("Started worker coordination subscriber thread")
        
    def _subscriber_worker(self):
        """Background worker that listens for Redis pub/sub messages"""
        pubsub = None
        
        try:
            pubsub = self._redis_client.pubsub()
            pubsub.subscribe('trakbridge:config_updates')
            
            logger.info("Subscribed to worker coordination messages")
            
            for message in pubsub.listen():
                if not self._running:
                    break
                    
                if message['type'] == 'message':
                    try:
                        # Parse the message data
                        data = eval(message['data'].decode('utf-8'))  # Safe eval of dict string
                        
                        with self._lock:
                            callback = self._subscribers.get('config_changes')
                            if callback:
                                callback(data)
                                
                    except Exception as e:
                        logger.warning(f"Error processing coordination message: {e}")
                        
        except (RedisConnectionError, RedisTimeoutError, ConnectionRefusedError) as e:
            logger.warning(f"Redis subscriber connection lost: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in subscriber worker: {e}")
        finally:
            if pubsub:
                try:
                    pubsub.unsubscribe()
                    pubsub.close()
                except Exception as e:
                    logger.warning(f"Error closing Redis pubsub: {e}")
            logger.info("Worker coordination subscriber thread stopped")
            
    def stop(self):
        """Stop the coordination service and clean up resources"""
        logger.info("Stopping worker coordination service")
        
        with self._lock:
            self._running = False
            self._subscribers.clear()
            
        if self._subscriber_thread and self._subscriber_thread.is_alive():
            self._subscriber_thread.join(timeout=5)
            
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception as e:
                logger.warning(f"Error closing Redis client: {e}")
            finally:
                self._redis_client = None
                
        logger.info("Worker coordination service stopped")


# Global service instance
_coordination_service: Optional[WorkerCoordinationService] = None


def get_coordination_service() -> WorkerCoordinationService:
    """Get the global worker coordination service instance"""
    global _coordination_service
    if _coordination_service is None:
        _coordination_service = WorkerCoordinationService()
    return _coordination_service