# ABOUTME: Redis pub/sub coordination service for multi-worker deployments
# ABOUTME: Handles worker coordination with graceful fallback when Redis unavailable

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable
import redis
import os

logger = logging.getLogger(__name__)


class WorkerCoordinationService:
    """Redis pub/sub coordination service with graceful fallback"""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None
        self.enabled = os.getenv('ENABLE_WORKER_COORDINATION', 'false').lower() == 'true'
        self.channel = "trakbridge:config_updates"
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        self.reconnect_delay = 1.0
        self.subscribers: Dict[str, Callable] = {}
        
        if self.enabled:
            self._connect()
    
    def _connect(self) -> bool:
        """Connect to Redis with retry logic"""
        try:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            self.redis_client.ping()
            self.pubsub = self.redis_client.pubsub()
            
            logger.info("Connected to Redis for worker coordination")
            self.reconnect_attempts = 0
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Worker coordination disabled.")
            self.redis_client = None
            self.pubsub = None
            return False
    
    def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Max Redis reconnection attempts reached. Coordination disabled.")
            return False
        
        delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 30.0)
        logger.info(f"Attempting Redis reconnection in {delay}s (attempt {self.reconnect_attempts + 1})")
        
        time.sleep(delay)
        self.reconnect_attempts += 1
        
        return self._connect()
    
    def publish_config_change(self, stream_id: int, config_version: datetime) -> bool:
        """Publish configuration change notification"""
        if not self.enabled or not self.redis_client:
            logger.debug("Worker coordination disabled, skipping config change notification")
            return False
        
        try:
            message = {
                'stream_id': stream_id,
                'config_version': config_version.isoformat(),
                'timestamp': datetime.utcnow().isoformat(),
                'worker_id': os.getenv('WORKER_ID', 'unknown')
            }
            
            result = self.redis_client.publish(self.channel, json.dumps(message))
            logger.debug(f"Published config change for stream {stream_id} to {result} subscribers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish config change: {e}")
            if self._should_reconnect():
                self._reconnect_with_backoff()
            return False
    
    def subscribe_to_config_changes(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Subscribe to configuration change notifications"""
        if not self.enabled or not self.pubsub:
            logger.debug("Worker coordination disabled, skipping subscription")
            return False
        
        try:
            self.pubsub.subscribe(self.channel)
            callback_id = id(callback)
            self.subscribers[str(callback_id)] = callback
            
            logger.info(f"Subscribed to config changes on channel {self.channel}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to config changes: {e}")
            return False
    
    def listen_for_messages(self) -> None:
        """Listen for Redis messages and dispatch to subscribers"""
        if not self.enabled or not self.pubsub:
            return
        
        try:
            for message in self.pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        logger.debug(f"Received config change notification: {data}")
                        
                        # Dispatch to all subscribers
                        for callback in self.subscribers.values():
                            try:
                                callback(data)
                            except Exception as e:
                                logger.error(f"Error in config change callback: {e}")
                                
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in config change message: {e}")
                        
        except Exception as e:
            logger.error(f"Error listening for Redis messages: {e}")
            if self._should_reconnect():
                self._reconnect_with_backoff()
    
    def _should_reconnect(self) -> bool:
        """Determine if we should attempt reconnection"""
        return (self.enabled and 
                self.reconnect_attempts < self.max_reconnect_attempts)
    
    def unsubscribe(self, callback: Callable) -> None:
        """Unsubscribe a callback from config changes"""
        callback_id = str(id(callback))
        if callback_id in self.subscribers:
            del self.subscribers[callback_id]
    
    def close(self) -> None:
        """Close Redis connections"""
        try:
            if self.pubsub:
                self.pubsub.close()
            if self.redis_client:
                self.redis_client.close()
                
            logger.info("Closed Redis connections")
            
        except Exception as e:
            logger.error(f"Error closing Redis connections: {e}")


# Global instance
worker_coordination = WorkerCoordinationService()