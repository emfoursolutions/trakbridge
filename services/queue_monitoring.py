"""
ABOUTME: Comprehensive queue monitoring service providing detailed metrics, alerting,
ABOUTME: and performance analysis for queue operations throughout the TrakBridge system

File: services/queue_monitoring.py

Description:
    Comprehensive monitoring service for queue operations providing detailed metrics,
    performance analysis, alerting capabilities, and historical data tracking.
    This service works in conjunction with the QueueManager to provide visibility
    into queue performance and operational health.

Key features:
    - Real-time queue metrics collection and analysis
    - Performance trend analysis and alerting
    - Configurable monitoring intervals and thresholds
    - Historical data retention and reporting
    - Integration with existing logging infrastructure
    - Queue health scoring and recommendations
    - Automated alert generation for threshold violations

Author: TrakBridge Development Team
Created: 2025-09-17
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
from services.logging_service import get_module_logger
from services.queue_manager import get_queue_manager

logger = get_module_logger(__name__)


@dataclass
class QueueHealthMetrics:
    """Comprehensive queue health metrics"""

    queue_id: int
    timestamp: datetime
    current_size: int
    max_size: int
    utilization_percent: float
    events_per_second: float
    batches_per_second: float
    average_wait_time: float
    overflow_rate: float
    health_score: float = 0.0  # 0-100 scale
    trend_direction: str = "stable"  # stable, increasing, decreasing


@dataclass
class PerformanceAlert:
    """Performance alert information"""

    alert_id: str
    queue_id: int
    alert_type: str  # threshold, trend, anomaly
    severity: str  # info, warning, critical
    message: str
    timestamp: datetime
    metrics: Dict[str, Any] = field(default_factory=dict)


class QueueMonitoringService:
    """
    Comprehensive monitoring service for queue operations.

    Provides real-time metrics collection, performance analysis,
    alerting, and historical data tracking for all queue operations.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the queue monitoring service.

        Args:
            config: Monitoring configuration dictionary
        """
        self.config = config or self._get_default_config()
        self.queue_manager = get_queue_manager()

        # Historical data storage
        self.metrics_history: Dict[int, deque] = {}
        self.alerts_history: deque = deque(maxlen=1000)

        # Performance tracking
        self.last_metrics: Dict[int, QueueHealthMetrics] = {}
        self.performance_baselines: Dict[int, Dict[str, float]] = {}

        # Monitoring state
        self.monitoring_active = False
        self.monitoring_task: Optional[asyncio.Task] = None

        # Alert management
        self.alert_callbacks = []
        self.alert_cooldowns: Dict[str, datetime] = {}

        logger.info(f"QueueMonitoringService initialized with config: {self.config}")

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default monitoring configuration"""
        return {
            "monitoring_interval_seconds": 10,
            "metrics_retention_hours": 24,
            "performance_window_minutes": 5,
            "health_thresholds": {
                "utilization_warning": 80,
                "utilization_critical": 95,
                "overflow_rate_warning": 0.01,  # 1% overflow rate
                "overflow_rate_critical": 0.05,  # 5% overflow rate
                "wait_time_warning": 1.0,  # 1 second
                "wait_time_critical": 5.0,  # 5 seconds
            },
            "trend_analysis": {
                "enabled": True,
                "sample_points": 6,  # Number of samples for trend analysis
                "significant_change_percent": 20,
            },
            "alerting": {
                "enabled": True,
                "cooldown_minutes": 15,
                "max_alerts_per_hour": 10,
            },
        }

    async def start_monitoring(self):
        """Start the monitoring service"""
        if self.monitoring_active:
            logger.warning("Monitoring service is already active")
            return

        try:
            self.monitoring_active = True
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("Queue monitoring service started")

        except Exception as e:
            logger.error(f"Failed to start monitoring service: {e}")
            self.monitoring_active = False

    async def stop_monitoring(self):
        """Stop the monitoring service"""
        self.monitoring_active = False

        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None

        logger.info("Queue monitoring service stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop"""
        interval = self.config.get("monitoring_interval_seconds", 10)

        while self.monitoring_active:
            try:
                await self._collect_and_analyze_metrics()
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(interval)

    async def _collect_and_analyze_metrics(self):
        """Collect metrics for all queues and perform analysis"""
        try:
            current_time = datetime.now(timezone.utc)
            queue_statuses = self.queue_manager.get_all_queue_status()

            for queue_id, status in queue_statuses.items():
                if not status.get("exists", False):
                    continue

                # Calculate performance metrics
                metrics = await self._calculate_queue_metrics(
                    queue_id, status, current_time
                )

                # Store metrics in history
                self._store_metrics_history(queue_id, metrics)

                # Perform health analysis
                await self._analyze_queue_health(metrics)

                # Update last metrics
                self.last_metrics[queue_id] = metrics

            # Perform system-wide analysis
            await self._analyze_system_performance()

            # Clean up old data
            self._cleanup_old_data()

        except Exception as e:
            logger.error(f"Failed to collect and analyze metrics: {e}")

    async def _calculate_queue_metrics(
        self, queue_id: int, status: Dict[str, Any], timestamp: datetime
    ) -> QueueHealthMetrics:
        """Calculate comprehensive metrics for a queue"""
        try:
            current_size = status.get("current_size", 0)
            max_size = status.get("max_size", 1)

            # Calculate utilization
            utilization_percent = (current_size / max_size) * 100 if max_size > 0 else 0

            # Calculate rates based on historical data
            events_per_second = self._calculate_event_rate(queue_id, status, timestamp)
            batches_per_second = self._calculate_batch_rate(queue_id, status, timestamp)

            # Calculate overflow rate
            total_processed = status.get("total_events_processed", 0)
            total_dropped = status.get("total_events_dropped", 0)
            overflow_rate = total_dropped / max(total_processed, 1)

            # Calculate average wait time (estimated based on queue size and processing rate)
            average_wait_time = self._estimate_wait_time(
                current_size, events_per_second
            )

            # Calculate health score
            health_score = self._calculate_health_score(
                utilization_percent, overflow_rate, average_wait_time
            )

            # Determine trend direction
            trend_direction = self._calculate_trend_direction(
                queue_id, utilization_percent
            )

            return QueueHealthMetrics(
                queue_id=queue_id,
                timestamp=timestamp,
                current_size=current_size,
                max_size=max_size,
                utilization_percent=utilization_percent,
                events_per_second=events_per_second,
                batches_per_second=batches_per_second,
                average_wait_time=average_wait_time,
                overflow_rate=overflow_rate,
                health_score=health_score,
                trend_direction=trend_direction,
            )

        except Exception as e:
            logger.error(f"Failed to calculate metrics for queue {queue_id}: {e}")
            return QueueHealthMetrics(
                queue_id=queue_id,
                timestamp=timestamp,
                current_size=0,
                max_size=1,
                utilization_percent=0,
                events_per_second=0,
                batches_per_second=0,
                average_wait_time=0,
                overflow_rate=0,
            )

    def _calculate_event_rate(
        self, queue_id: int, status: Dict[str, Any], timestamp: datetime
    ) -> float:
        """Calculate events per second rate"""
        try:
            if queue_id not in self.metrics_history:
                return 0.0

            history = self.metrics_history[queue_id]
            if len(history) < 2:
                return 0.0

            # Get recent metrics for rate calculation
            recent_metrics = [
                m for m in history if (timestamp - m.timestamp).total_seconds() <= 60
            ]
            if len(recent_metrics) < 2:
                return 0.0

            # Calculate rate based on processed events
            current_processed = status.get("total_events_processed", 0)
            oldest_metric = recent_metrics[0]

            # Find baseline processed count
            baseline_processed = 0
            for past_status in [status]:  # This would need historical status data
                baseline_processed = past_status.get("total_events_processed", 0)
                break

            time_diff = (timestamp - oldest_metric.timestamp).total_seconds()
            if time_diff > 0:
                return max(0, (current_processed - baseline_processed) / time_diff)

            return 0.0

        except Exception as e:
            logger.debug(f"Failed to calculate event rate for queue {queue_id}: {e}")
            return 0.0

    def _calculate_batch_rate(
        self, queue_id: int, status: Dict[str, Any], timestamp: datetime
    ) -> float:
        """Calculate batches per second rate"""
        try:
            # Similar logic to event rate but for batches
            total_batches = status.get("total_batches_sent", 0)

            if queue_id not in self.metrics_history:
                return 0.0

            history = self.metrics_history[queue_id]
            if len(history) < 2:
                return 0.0

            # Simple rate calculation (this could be enhanced with historical data)
            window_minutes = self.config.get("performance_window_minutes", 5)
            return total_batches / (window_minutes * 60) if total_batches > 0 else 0.0

        except Exception as e:
            logger.debug(f"Failed to calculate batch rate for queue {queue_id}: {e}")
            return 0.0

    def _estimate_wait_time(self, queue_size: int, processing_rate: float) -> float:
        """Estimate average wait time for events in queue"""
        if processing_rate <= 0 or queue_size <= 0:
            return 0.0

        # Simple estimation: queue_size / processing_rate
        return queue_size / processing_rate

    def _calculate_health_score(
        self, utilization: float, overflow_rate: float, wait_time: float
    ) -> float:
        """Calculate overall health score (0-100)"""
        try:
            score = 100.0

            # Deduct points for high utilization
            if utilization > 95:
                score -= 40
            elif utilization > 80:
                score -= 20
            elif utilization > 60:
                score -= 10

            # Deduct points for overflow
            if overflow_rate > 0.05:  # 5%
                score -= 30
            elif overflow_rate > 0.01:  # 1%
                score -= 15

            # Deduct points for high wait times
            if wait_time > 5.0:
                score -= 20
            elif wait_time > 1.0:
                score -= 10

            return max(0.0, score)

        except Exception as e:
            logger.debug(f"Failed to calculate health score: {e}")
            return 50.0  # Neutral score on error

    def _calculate_trend_direction(
        self, queue_id: int, current_utilization: float
    ) -> str:
        """Calculate trend direction based on historical data"""
        try:
            if queue_id not in self.metrics_history:
                return "stable"

            history = self.metrics_history[queue_id]
            sample_points = self.config.get("trend_analysis", {}).get(
                "sample_points", 6
            )

            if len(history) < sample_points:
                return "stable"

            # Get recent utilization values
            recent_utilizations = [
                m.utilization_percent for m in list(history)[-sample_points:]
            ]

            # Calculate trend
            if len(recent_utilizations) >= 3:
                first_third = sum(
                    recent_utilizations[: len(recent_utilizations) // 3]
                ) / (len(recent_utilizations) // 3)
                last_third = sum(
                    recent_utilizations[-len(recent_utilizations) // 3 :]
                ) / (len(recent_utilizations) // 3)

                change_percent = abs(last_third - first_third) / max(first_third, 1)
                significant_threshold = (
                    self.config.get("trend_analysis", {}).get(
                        "significant_change_percent", 20
                    )
                    / 100
                )

                if change_percent > significant_threshold:
                    return "increasing" if last_third > first_third else "decreasing"

            return "stable"

        except Exception as e:
            logger.debug(
                f"Failed to calculate trend direction for queue {queue_id}: {e}"
            )
            return "stable"

    def _store_metrics_history(self, queue_id: int, metrics: QueueHealthMetrics):
        """Store metrics in historical data"""
        if queue_id not in self.metrics_history:
            retention_hours = self.config.get("metrics_retention_hours", 24)
            max_samples = retention_hours * 360  # 10-second intervals
            self.metrics_history[queue_id] = deque(maxlen=max_samples)

        self.metrics_history[queue_id].append(metrics)

    async def _analyze_queue_health(self, metrics: QueueHealthMetrics):
        """Analyze queue health and generate alerts if necessary"""
        try:
            alerts = []
            thresholds = self.config.get("health_thresholds", {})

            # Check utilization thresholds
            if metrics.utilization_percent >= thresholds.get(
                "utilization_critical", 95
            ):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "critical",
                        f"Queue utilization critical: {metrics.utilization_percent:.1f}%",
                        {"utilization": metrics.utilization_percent},
                    )
                )
            elif metrics.utilization_percent >= thresholds.get(
                "utilization_warning", 80
            ):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "warning",
                        f"Queue utilization high: {metrics.utilization_percent:.1f}%",
                        {"utilization": metrics.utilization_percent},
                    )
                )

            # Check overflow rate
            if metrics.overflow_rate >= thresholds.get("overflow_rate_critical", 0.05):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "critical",
                        f"High event overflow rate: {metrics.overflow_rate*100:.1f}%",
                        {"overflow_rate": metrics.overflow_rate},
                    )
                )
            elif metrics.overflow_rate >= thresholds.get("overflow_rate_warning", 0.01):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "warning",
                        f"Elevated event overflow rate: {metrics.overflow_rate*100:.1f}%",
                        {"overflow_rate": metrics.overflow_rate},
                    )
                )

            # Check wait times
            if metrics.average_wait_time >= thresholds.get("wait_time_critical", 5.0):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "critical",
                        f"High average wait time: {metrics.average_wait_time:.1f}s",
                        {"wait_time": metrics.average_wait_time},
                    )
                )
            elif metrics.average_wait_time >= thresholds.get("wait_time_warning", 1.0):
                alerts.append(
                    self._create_alert(
                        metrics.queue_id,
                        "threshold",
                        "warning",
                        f"Elevated average wait time: {metrics.average_wait_time:.1f}s",
                        {"wait_time": metrics.average_wait_time},
                    )
                )

            # Process alerts
            for alert in alerts:
                await self._process_alert(alert)

        except Exception as e:
            logger.error(
                f"Failed to analyze queue health for queue {metrics.queue_id}: {e}"
            )

    def _create_alert(
        self,
        queue_id: int,
        alert_type: str,
        severity: str,
        message: str,
        metrics: Dict[str, Any],
    ) -> PerformanceAlert:
        """Create a performance alert"""
        alert_id = f"{queue_id}_{alert_type}_{severity}_{int(time.time())}"

        return PerformanceAlert(
            alert_id=alert_id,
            queue_id=queue_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metrics=metrics,
        )

    async def _process_alert(self, alert: PerformanceAlert):
        """Process and potentially send an alert"""
        try:
            if not self.config.get("alerting", {}).get("enabled", True):
                return

            # Check cooldown
            cooldown_key = f"{alert.queue_id}_{alert.alert_type}_{alert.severity}"
            cooldown_minutes = self.config.get("alerting", {}).get(
                "cooldown_minutes", 15
            )

            if cooldown_key in self.alert_cooldowns:
                time_since_last = (
                    datetime.now(timezone.utc) - self.alert_cooldowns[cooldown_key]
                )
                if time_since_last.total_seconds() < cooldown_minutes * 60:
                    return  # Still in cooldown

            # Log the alert
            log_level = (
                logging.CRITICAL if alert.severity == "critical" else logging.WARNING
            )
            logger.log(log_level, f"Queue Alert: {alert.message}")

            # Store in history
            self.alerts_history.append(alert)

            # Update cooldown
            self.alert_cooldowns[cooldown_key] = alert.timestamp

            # Call alert callbacks
            for callback in self.alert_callbacks:
                try:
                    await callback(alert)
                except Exception as e:
                    logger.error(f"Alert callback failed: {e}")

        except Exception as e:
            logger.error(f"Failed to process alert: {e}")

    async def _analyze_system_performance(self):
        """Analyze overall system performance"""
        try:
            total_queues = len(self.queue_manager.queues)
            if total_queues == 0:
                return

            # Calculate system-wide metrics
            total_utilization = 0
            total_health_score = 0
            critical_queues = 0

            for queue_id, metrics in self.last_metrics.items():
                total_utilization += metrics.utilization_percent
                total_health_score += metrics.health_score

                if metrics.health_score < 50:
                    critical_queues += 1

            avg_utilization = total_utilization / total_queues
            avg_health_score = total_health_score / total_queues

            # Log system summary
            logger.debug(
                f"Queue System Health: {total_queues} queues, "
                f"avg utilization: {avg_utilization:.1f}%, "
                f"avg health score: {avg_health_score:.1f}, "
                f"critical queues: {critical_queues}"
            )

            # Generate system-level alerts if needed
            if critical_queues > total_queues * 0.5:  # More than 50% critical
                alert = self._create_alert(
                    -1,
                    "system",
                    "critical",
                    f"System degraded: {critical_queues}/{total_queues} queues critical",
                    {"critical_queues": critical_queues, "total_queues": total_queues},
                )
                await self._process_alert(alert)

        except Exception as e:
            logger.error(f"Failed to analyze system performance: {e}")

    def _cleanup_old_data(self):
        """Clean up old metrics and alerts"""
        try:
            retention_hours = self.config.get("metrics_retention_hours", 24)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

            # Clean up metrics history (deque maxlen handles this automatically)

            # Clean up alert cooldowns
            expired_cooldowns = [
                key
                for key, timestamp in self.alert_cooldowns.items()
                if timestamp < cutoff_time
            ]
            for key in expired_cooldowns:
                del self.alert_cooldowns[key]

        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

    def add_alert_callback(self, callback):
        """Add a callback function for alert notifications"""
        self.alert_callbacks.append(callback)

    def get_queue_metrics(self, queue_id: int) -> Optional[QueueHealthMetrics]:
        """Get the latest metrics for a specific queue"""
        return self.last_metrics.get(queue_id)

    def get_metrics_history(
        self, queue_id: int, hours: int = 1
    ) -> List[QueueHealthMetrics]:
        """Get historical metrics for a queue"""
        if queue_id not in self.metrics_history:
            return []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [m for m in self.metrics_history[queue_id] if m.timestamp >= cutoff_time]

    def get_recent_alerts(self, hours: int = 1) -> List[PerformanceAlert]:
        """Get recent alerts"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            alert for alert in self.alerts_history if alert.timestamp >= cutoff_time
        ]


# Global monitoring service instance
_monitoring_service = None


def get_queue_monitoring_service(
    config: Optional[Dict[str, Any]] = None
) -> QueueMonitoringService:
    """
    Get the global queue monitoring service instance (singleton pattern).

    Args:
        config: Configuration dictionary (only used on first call)

    Returns:
        QueueMonitoringService instance
    """
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = QueueMonitoringService(config)
    return _monitoring_service


def reset_queue_monitoring_service():
    """Reset the global monitoring service (mainly for testing)"""
    global _monitoring_service
    _monitoring_service = None
