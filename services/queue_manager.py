"""
ABOUTME: Dedicated queue management service providing bounded queues with configurable
ABOUTME: overflow strategies, batch transmission, and configuration change handling

File: services/queue_manager.py

Description:
    Dedicated queue management service that handles bounded queues with configurable
    overflow strategies, batch transmission logic, and comprehensive monitoring.
    This service is extracted from the COT service to provide clean separation
    of concerns and optimized queue operations.

Key features:
    - Bounded queues with configurable size limits
    - Multiple overflow strategies: drop_oldest, drop_newest, block
    - Batch transmission with configurable timeouts
    - Configuration change detection and queue flushing
    - Comprehensive logging and monitoring
    - Performance optimization while maintaining test compliance
    - Thread-safe operations with proper asyncio integration

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


@dataclass
class QueueMetrics:
    """Queue performance and status metrics"""
    total_events_processed: int = 0
    total_events_dropped: int = 0
    total_batches_sent: int = 0
    current_queue_size: int = 0
    max_queue_size_reached: int = 0
    average_batch_size: float = 0.0
    last_flush_time: Optional[datetime] = None
    overflow_events: int = 0
    config_change_flushes: int = 0


class QueueManager:
    """
    Dedicated queue management service with bounded queues and configurable strategies.
    
    This service provides comprehensive queue management capabilities including:
    - Bounded queues with configurable overflow handling
    - Batch transmission with timeout controls
    - Configuration change detection and queue flushing
    - Performance monitoring and metrics collection
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the queue manager with configuration.

        Args:
            config: Queue configuration dictionary
        """
        self.config = config or self._get_default_config()
        self.queues: Dict[int, asyncio.Queue] = {}
        self.metrics: Dict[int, QueueMetrics] = {}
        self.workers: Dict[int, asyncio.Task] = {}
        self.running = False
        
        # Configuration monitoring
        self._last_config_hash = None
        self._config_change_callbacks = []
        
        logger.info(f"QueueManager initialized with config: {self.config}")

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration for queue management"""
        return {
            "max_size": 500,
            "batch_size": 8,
            "overflow_strategy": "drop_oldest",
            "flush_on_config_change": True,
            "batch_timeout_ms": 100,
            "queue_check_interval_ms": 50,
            "log_queue_stats": True,
            "queue_warning_threshold": 400,
        }

    async def create_queue(self, queue_id: int) -> bool:
        """
        Create a bounded queue with the configured maximum size.

        Args:
            queue_id: Unique identifier for the queue

        Returns:
            True if queue was created successfully
        """
        try:
            if queue_id in self.queues:
                logger.warning(f"Queue {queue_id} already exists")
                return True

            # Create bounded queue with configured max size
            max_size = self.config.get("max_size", 500)
            queue = asyncio.Queue(maxsize=max_size)
            
            self.queues[queue_id] = queue
            self.metrics[queue_id] = QueueMetrics()
            
            logger.info(f"Created bounded queue {queue_id} with max size {max_size}")
            return True

        except Exception as e:
            logger.error(f"Failed to create queue {queue_id}: {e}")
            return False

    async def enqueue_event(self, queue_id: int, event: bytes) -> bool:
        """
        Enqueue an event with overflow handling according to configured strategy.

        Args:
            queue_id: Queue identifier
            event: Event data to enqueue

        Returns:
            True if event was successfully enqueued
        """
        if queue_id not in self.queues:
            logger.error(f"Queue {queue_id} does not exist")
            return False

        try:
            queue = self.queues[queue_id]
            metrics = self.metrics[queue_id]
            
            # Handle queue overflow according to configured strategy
            success = await self._handle_overflow_and_enqueue(queue, event, queue_id)
            
            if success:
                metrics.total_events_processed += 1
                current_size = queue.qsize()
                metrics.current_queue_size = current_size
                
                # Track maximum queue size reached
                if current_size > metrics.max_queue_size_reached:
                    metrics.max_queue_size_reached = current_size
                
                # Log warning if queue size exceeds threshold
                threshold = self.config.get("queue_warning_threshold", 400)
                if current_size >= threshold:
                    logger.warning(
                        f"Queue {queue_id} size ({current_size}) exceeds warning threshold ({threshold})"
                    )

            return success

        except Exception as e:
            logger.error(f"Failed to enqueue event to queue {queue_id}: {e}")
            return False

    async def _handle_overflow_and_enqueue(self, queue: asyncio.Queue, event: bytes, queue_id: int) -> bool:
        """
        Handle queue overflow according to configured strategy and enqueue event.

        Args:
            queue: The asyncio queue
            event: Event to enqueue
            queue_id: Queue identifier for logging

        Returns:
            True if event was successfully enqueued
        """
        strategy = self.config.get("overflow_strategy", "drop_oldest")
        metrics = self.metrics[queue_id]

        if strategy == "block":
            # Block until space is available (default asyncio.Queue behavior)
            await queue.put(event)
            return True
        
        elif queue.full():
            if strategy == "drop_oldest":
                try:
                    # Drop oldest event to make room
                    dropped_event = queue.get_nowait()
                    logger.warning(
                        f"Queue {queue_id} overflow: dropped oldest event "
                        f"(queue size: {queue.qsize()}, max: {queue.maxsize})"
                    )
                    metrics.total_events_dropped += 1
                    metrics.overflow_events += 1
                    
                    # Add new event
                    await queue.put(event)
                    return True
                except asyncio.QueueEmpty:
                    # Queue became empty, just add the event
                    await queue.put(event)
                    return True
                    
            elif strategy == "drop_newest":
                logger.warning(
                    f"Queue {queue_id} overflow: dropping newest event "
                    f"(queue size: {queue.qsize()}, max: {queue.maxsize})"
                )
                metrics.total_events_dropped += 1
                metrics.overflow_events += 1
                return False  # Don't add the new event
                
        else:
            # Queue not full, add event normally
            await queue.put(event)
            return True

    async def flush_queue(self, queue_id: int) -> int:
        """
        Flush all events from a queue (typically used on configuration changes).

        Args:
            queue_id: Queue identifier

        Returns:
            Number of events flushed
        """
        if queue_id not in self.queues:
            logger.error(f"Queue {queue_id} does not exist")
            return 0

        try:
            queue = self.queues[queue_id]
            metrics = self.metrics[queue_id]
            
            flushed_count = 0
            while not queue.empty():
                try:
                    queue.get_nowait()
                    flushed_count += 1
                except asyncio.QueueEmpty:
                    break

            metrics.last_flush_time = datetime.now(timezone.utc)
            metrics.config_change_flushes += 1
            
            logger.info(f"Flushed {flushed_count} events from queue {queue_id}")
            return flushed_count

        except Exception as e:
            logger.error(f"Failed to flush queue {queue_id}: {e}")
            return 0

    async def get_batch(self, queue_id: int) -> List[bytes]:
        """
        Get a batch of events from the queue with timeout handling.

        Args:
            queue_id: Queue identifier

        Returns:
            List of events (may be partial batch if timeout occurs)
        """
        if queue_id not in self.queues:
            logger.error(f"Queue {queue_id} does not exist")
            return []

        try:
            queue = self.queues[queue_id]
            batch = []
            batch_size = self.config.get("batch_size", 8)
            timeout_ms = self.config.get("batch_timeout_ms", 100)
            timeout_seconds = timeout_ms / 1000.0

            while len(batch) < batch_size:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout_seconds)
                    if event is None:  # Shutdown signal
                        break
                    batch.append(event)
                except asyncio.TimeoutError:
                    break  # Return partial batch

            # Update metrics
            if batch:
                metrics = self.metrics[queue_id]
                metrics.total_batches_sent += 1
                
                # Update average batch size
                total_events = metrics.total_batches_sent * metrics.average_batch_size
                new_total = total_events + len(batch)
                metrics.average_batch_size = new_total / metrics.total_batches_sent

            return batch

        except Exception as e:
            logger.error(f"Failed to get batch from queue {queue_id}: {e}")
            return []

    def get_queue_status(self, queue_id: int) -> Dict[str, Any]:
        """
        Get comprehensive status information for a queue.

        Args:
            queue_id: Queue identifier

        Returns:
            Dictionary containing queue status and metrics
        """
        if queue_id not in self.queues:
            return {"exists": False}

        try:
            queue = self.queues[queue_id]
            metrics = self.metrics[queue_id]

            return {
                "exists": True,
                "current_size": queue.qsize(),
                "max_size": queue.maxsize,
                "is_full": queue.full(),
                "is_empty": queue.empty(),
                "total_events_processed": metrics.total_events_processed,
                "total_events_dropped": metrics.total_events_dropped,
                "total_batches_sent": metrics.total_batches_sent,
                "max_queue_size_reached": metrics.max_queue_size_reached,
                "average_batch_size": metrics.average_batch_size,
                "overflow_events": metrics.overflow_events,
                "config_change_flushes": metrics.config_change_flushes,
                "last_flush_time": metrics.last_flush_time.isoformat() if metrics.last_flush_time else None,
            }

        except Exception as e:
            logger.error(f"Failed to get status for queue {queue_id}: {e}")
            return {"exists": True, "error": str(e)}

    def get_all_queue_status(self) -> Dict[int, Dict[str, Any]]:
        """Get status for all queues"""
        return {queue_id: self.get_queue_status(queue_id) for queue_id in self.queues.keys()}

    async def remove_queue(self, queue_id: int) -> bool:
        """
        Remove a queue and clean up resources.

        Args:
            queue_id: Queue identifier

        Returns:
            True if queue was successfully removed
        """
        try:
            if queue_id in self.queues:
                # Send shutdown signal
                await self.queues[queue_id].put(None)
                
                # Clean up
                del self.queues[queue_id]
                if queue_id in self.metrics:
                    del self.metrics[queue_id]
                if queue_id in self.workers:
                    self.workers[queue_id].cancel()
                    del self.workers[queue_id]
                
                logger.info(f"Removed queue {queue_id}")
                return True
            else:
                logger.warning(f"Queue {queue_id} does not exist for removal")
                return False

        except Exception as e:
            logger.error(f"Failed to remove queue {queue_id}: {e}")
            return False

    def log_comprehensive_status(self):
        """Log comprehensive status of all queues for monitoring"""
        if not self.config.get("log_queue_stats", True):
            return

        try:
            total_queues = len(self.queues)
            total_events = sum(m.total_events_processed for m in self.metrics.values())
            total_dropped = sum(m.total_events_dropped for m in self.metrics.values())
            total_batches = sum(m.total_batches_sent for m in self.metrics.values())

            logger.info(
                f"Queue Manager Status: {total_queues} queues, "
                f"{total_events} events processed, {total_dropped} dropped, "
                f"{total_batches} batches sent"
            )

            # Log individual queue status for queues with activity
            for queue_id, metrics in self.metrics.items():
                if metrics.total_events_processed > 0 or self.queues[queue_id].qsize() > 0:
                    status = self.get_queue_status(queue_id)
                    logger.debug(
                        f"Queue {queue_id}: {status['current_size']}/{status['max_size']} events, "
                        f"{status['total_events_processed']} processed, "
                        f"{status['total_events_dropped']} dropped"
                    )

        except Exception as e:
            logger.error(f"Failed to log queue status: {e}")

    async def on_configuration_change(self, new_config: Dict[str, Any]):
        """
        Handle configuration changes by flushing queues if configured to do so.

        Args:
            new_config: New configuration dictionary
        """
        try:
            old_config = self.config
            self.config = new_config
            
            # Check if we should flush queues on configuration change
            if self.config.get("flush_on_config_change", True):
                logger.info("Configuration change detected, flushing all queues")
                
                total_flushed = 0
                for queue_id in self.queues.keys():
                    flushed = await self.flush_queue(queue_id)
                    total_flushed += flushed
                
                logger.info(f"Flushed {total_flushed} total events due to configuration change")
            
            # Log configuration changes
            logger.info(f"Queue configuration updated: {old_config} -> {new_config}")

        except Exception as e:
            logger.error(f"Failed to handle configuration change: {e}")


# Global queue manager instance
_queue_manager = None


def get_queue_manager(config: Optional[Dict[str, Any]] = None) -> QueueManager:
    """
    Get the global queue manager instance (singleton pattern).

    Args:
        config: Configuration dictionary (only used on first call)

    Returns:
        QueueManager instance
    """
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = QueueManager(config)
    return _queue_manager


def reset_queue_manager():
    """Reset the global queue manager (mainly for testing)"""
    global _queue_manager
    _queue_manager = None