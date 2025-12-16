"""
ABOUTME: Monitoring service for bidirectional TAK communication RX worker providing
ABOUTME: metrics collection, performance analysis, and alerting for received CoT messages

File: services/rx_monitoring.py

Description:
    Comprehensive monitoring service for the RX worker component of bidirectional
    TAK communication. Tracks message reception rates, plugin performance, buffer
    usage, and provides alerting for anomalies and performance issues.

Key features:
    - Real-time RX worker metrics collection
    - Per-TAK-server and per-plugin performance tracking
    - Buffer usage monitoring and overflow detection
    - Message throughput analysis
    - Plugin timeout and error tracking
    - Historical data retention and trend analysis
    - Integration with existing monitoring infrastructure

Author: TrakBridge Development Team
Created: 2025-12-16
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque, defaultdict
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


@dataclass
class RxWorkerMetrics:
    """Metrics for RX worker performance"""

    tak_server_id: int
    timestamp: datetime
    messages_received: int
    messages_processed: int
    messages_dropped: int
    messages_malicious: int
    bytes_received: int
    buffer_size: int
    buffer_max_size: int
    buffer_overflow_count: int
    messages_per_second: float
    bytes_per_second: float
    active_plugins: int
    plugin_errors: int
    plugin_timeouts: int
    average_plugin_latency: float  # milliseconds
    health_score: float = 100.0


@dataclass
class PluginPerformanceMetrics:
    """Per-plugin performance metrics"""

    plugin_type: str
    tak_server_id: int
    stream_id: int
    timestamp: datetime
    messages_handled: int
    messages_filtered: int
    errors: int
    timeouts: int
    total_latency_ms: float
    average_latency_ms: float
    max_latency_ms: float
    min_latency_ms: float


@dataclass
class RxAlert:
    """Alert for RX worker issues"""

    alert_id: str
    tak_server_id: int
    alert_type: str  # throughput, buffer, plugin, error
    severity: str  # info, warning, critical
    message: str
    timestamp: datetime
    metrics: Dict[str, Any] = field(default_factory=dict)


class RxMonitoringService:
    """
    Monitoring service for bidirectional TAK RX worker.

    Tracks performance, throughput, errors, and plugin behavior
    for received CoT messages from TAK servers.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize RX monitoring service.

        Args:
            config: Monitoring configuration dictionary
        """
        self.config = config or self._get_default_config()

        # Metrics storage
        self.rx_metrics_history: Dict[int, deque] = {}  # per TAK server
        self.plugin_metrics_history: Dict[str, deque] = {}  # per plugin+server combo
        self.alerts_history: deque = deque(maxlen=1000)

        # Real-time counters (per TAK server)
        self.message_counters: Dict[int, Dict[str, int]] = defaultdict(lambda: {
            'received': 0,
            'processed': 0,
            'dropped': 0,
            'malicious': 0
        })
        self.byte_counters: Dict[int, int] = defaultdict(int)
        self.buffer_stats: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
            'current_size': 0,
            'max_size': 0,
            'overflow_count': 0
        })

        # Plugin tracking
        self.plugin_latencies: Dict[str, List[float]] = defaultdict(list)
        self.plugin_counters: Dict[str, Dict[str, int]] = defaultdict(lambda: {
            'handled': 0,
            'filtered': 0,
            'errors': 0,
            'timeouts': 0
        })

        # Last metrics snapshot
        self.last_rx_metrics: Dict[int, RxWorkerMetrics] = {}
        self.last_plugin_metrics: Dict[str, PluginPerformanceMetrics] = {}

        # Alerting
        self.alert_callbacks = []
        self.alert_cooldowns: Dict[str, datetime] = {}

        # Monitoring state
        self.monitoring_active = False
        self.monitoring_task: Optional[asyncio.Task] = None

        logger.info(f"RxMonitoringService initialized with config: {self.config}")

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default monitoring configuration"""
        return {
            "monitoring_interval_seconds": 10,
            "metrics_retention_hours": 24,
            "performance_window_minutes": 5,
            "thresholds": {
                "messages_per_second_warning": 100,
                "messages_per_second_critical": 500,
                "buffer_utilization_warning": 80,  # percent
                "buffer_utilization_critical": 95,
                "plugin_latency_warning": 1000,  # milliseconds
                "plugin_latency_critical": 5000,
                "plugin_error_rate_warning": 0.01,  # 1%
                "plugin_error_rate_critical": 0.05,  # 5%
                "drop_rate_warning": 0.01,
                "drop_rate_critical": 0.05,
            },
            "alerting": {
                "enabled": True,
                "cooldown_minutes": 15,
                "max_alerts_per_hour": 10,
            },
            "plugin_latency_samples": 100,  # Keep last N latency samples
        }

    async def start_monitoring(self):
        """Start the monitoring service"""
        if self.monitoring_active:
            logger.warning("RX monitoring service is already active")
            return

        try:
            self.monitoring_active = True
            self.monitoring_task = asyncio.create_task(self._monitoring_loop())
            logger.info("RX monitoring service started")

        except Exception as e:
            logger.error(f"Failed to start RX monitoring service: {e}")
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
            except RuntimeError as e:
                if "attached to a different loop" in str(e):
                    logger.debug("RX monitoring task cancelled in different loop context")
                else:
                    raise
            self.monitoring_task = None

        logger.info("RX monitoring service stopped")

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
                logger.error(f"Error in RX monitoring loop: {e}")
                await asyncio.sleep(interval)

    async def _collect_and_analyze_metrics(self):
        """Collect metrics and perform analysis"""
        try:
            current_time = datetime.now(timezone.utc)

            # Collect metrics for each TAK server
            for tak_server_id in self.message_counters.keys():
                metrics = self._calculate_rx_metrics(tak_server_id, current_time)
                self._store_rx_metrics(tak_server_id, metrics)
                await self._analyze_rx_health(metrics)
                self.last_rx_metrics[tak_server_id] = metrics

            # Collect plugin metrics
            for plugin_key in self.plugin_counters.keys():
                metrics = self._calculate_plugin_metrics(plugin_key, current_time)
                self._store_plugin_metrics(plugin_key, metrics)
                await self._analyze_plugin_health(metrics)
                self.last_plugin_metrics[plugin_key] = metrics

            # Cleanup old data
            self._cleanup_old_data()

        except Exception as e:
            logger.error(f"Failed to collect and analyze RX metrics: {e}")

    def _calculate_rx_metrics(
        self, tak_server_id: int, timestamp: datetime
    ) -> RxWorkerMetrics:
        """Calculate RX worker metrics for a TAK server"""
        try:
            counters = self.message_counters[tak_server_id]
            buffer = self.buffer_stats[tak_server_id]
            bytes_recv = self.byte_counters[tak_server_id]

            # Calculate rates
            messages_per_second = self._calculate_message_rate(tak_server_id)
            bytes_per_second = self._calculate_byte_rate(tak_server_id)

            # Calculate plugin stats
            active_plugins = len([
                k for k in self.plugin_counters.keys()
                if k.startswith(f"{tak_server_id}_")
            ])
            plugin_errors = sum(
                self.plugin_counters[k]['errors']
                for k in self.plugin_counters.keys()
                if k.startswith(f"{tak_server_id}_")
            )
            plugin_timeouts = sum(
                self.plugin_counters[k]['timeouts']
                for k in self.plugin_counters.keys()
                if k.startswith(f"{tak_server_id}_")
            )

            # Calculate average plugin latency
            avg_latency = self._calculate_average_plugin_latency(tak_server_id)

            # Calculate health score
            health_score = self._calculate_rx_health_score(
                counters, buffer, plugin_errors, plugin_timeouts
            )

            return RxWorkerMetrics(
                tak_server_id=tak_server_id,
                timestamp=timestamp,
                messages_received=counters['received'],
                messages_processed=counters['processed'],
                messages_dropped=counters['dropped'],
                messages_malicious=counters['malicious'],
                bytes_received=bytes_recv,
                buffer_size=buffer['current_size'],
                buffer_max_size=buffer['max_size'],
                buffer_overflow_count=buffer['overflow_count'],
                messages_per_second=messages_per_second,
                bytes_per_second=bytes_per_second,
                active_plugins=active_plugins,
                plugin_errors=plugin_errors,
                plugin_timeouts=plugin_timeouts,
                average_plugin_latency=avg_latency,
                health_score=health_score
            )

        except Exception as e:
            logger.error(f"Failed to calculate RX metrics for TAK server {tak_server_id}: {e}")
            return RxWorkerMetrics(
                tak_server_id=tak_server_id,
                timestamp=timestamp,
                messages_received=0,
                messages_processed=0,
                messages_dropped=0,
                messages_malicious=0,
                bytes_received=0,
                buffer_size=0,
                buffer_max_size=1,
                buffer_overflow_count=0,
                messages_per_second=0.0,
                bytes_per_second=0.0,
                active_plugins=0,
                plugin_errors=0,
                plugin_timeouts=0,
                average_plugin_latency=0.0
            )

    def _calculate_plugin_metrics(
        self, plugin_key: str, timestamp: datetime
    ) -> PluginPerformanceMetrics:
        """Calculate metrics for a specific plugin"""
        try:
            # Parse plugin key: "{tak_server_id}_{stream_id}_{plugin_type}"
            parts = plugin_key.split('_', 2)
            tak_server_id = int(parts[0])
            stream_id = int(parts[1])
            plugin_type = parts[2]

            counters = self.plugin_counters[plugin_key]
            latencies = self.plugin_latencies.get(plugin_key, [])

            total_latency = sum(latencies)
            avg_latency = total_latency / len(latencies) if latencies else 0.0
            max_latency = max(latencies) if latencies else 0.0
            min_latency = min(latencies) if latencies else 0.0

            return PluginPerformanceMetrics(
                plugin_type=plugin_type,
                tak_server_id=tak_server_id,
                stream_id=stream_id,
                timestamp=timestamp,
                messages_handled=counters['handled'],
                messages_filtered=counters['filtered'],
                errors=counters['errors'],
                timeouts=counters['timeouts'],
                total_latency_ms=total_latency,
                average_latency_ms=avg_latency,
                max_latency_ms=max_latency,
                min_latency_ms=min_latency
            )

        except Exception as e:
            logger.error(f"Failed to calculate plugin metrics for {plugin_key}: {e}")
            return PluginPerformanceMetrics(
                plugin_type="unknown",
                tak_server_id=0,
                stream_id=0,
                timestamp=timestamp,
                messages_handled=0,
                messages_filtered=0,
                errors=0,
                timeouts=0,
                total_latency_ms=0.0,
                average_latency_ms=0.0,
                max_latency_ms=0.0,
                min_latency_ms=0.0
            )

    def _calculate_message_rate(self, tak_server_id: int) -> float:
        """Calculate messages per second rate"""
        try:
            if tak_server_id not in self.rx_metrics_history:
                return 0.0

            history = self.rx_metrics_history[tak_server_id]
            if len(history) < 2:
                return 0.0

            # Calculate rate over last minute
            current_time = datetime.now(timezone.utc)
            recent_metrics = [
                m for m in history
                if (current_time - m.timestamp).total_seconds() <= 60
            ]

            if len(recent_metrics) < 2:
                return 0.0

            time_diff = (recent_metrics[-1].timestamp - recent_metrics[0].timestamp).total_seconds()
            if time_diff > 0:
                msg_diff = recent_metrics[-1].messages_received - recent_metrics[0].messages_received
                return max(0, msg_diff / time_diff)

            return 0.0

        except Exception as e:
            logger.debug(f"Failed to calculate message rate for TAK server {tak_server_id}: {e}")
            return 0.0

    def _calculate_byte_rate(self, tak_server_id: int) -> float:
        """Calculate bytes per second rate"""
        try:
            if tak_server_id not in self.rx_metrics_history:
                return 0.0

            history = self.rx_metrics_history[tak_server_id]
            if len(history) < 2:
                return 0.0

            # Calculate rate over last minute
            current_time = datetime.now(timezone.utc)
            recent_metrics = [
                m for m in history
                if (current_time - m.timestamp).total_seconds() <= 60
            ]

            if len(recent_metrics) < 2:
                return 0.0

            time_diff = (recent_metrics[-1].timestamp - recent_metrics[0].timestamp).total_seconds()
            if time_diff > 0:
                byte_diff = recent_metrics[-1].bytes_received - recent_metrics[0].bytes_received
                return max(0, byte_diff / time_diff)

            return 0.0

        except Exception as e:
            logger.debug(f"Failed to calculate byte rate for TAK server {tak_server_id}: {e}")
            return 0.0

    def _calculate_average_plugin_latency(self, tak_server_id: int) -> float:
        """Calculate average plugin latency for a TAK server"""
        try:
            total_latency = 0.0
            sample_count = 0

            for plugin_key in self.plugin_latencies.keys():
                if plugin_key.startswith(f"{tak_server_id}_"):
                    latencies = self.plugin_latencies[plugin_key]
                    if latencies:
                        total_latency += sum(latencies)
                        sample_count += len(latencies)

            return total_latency / sample_count if sample_count > 0 else 0.0

        except Exception as e:
            logger.debug(f"Failed to calculate average plugin latency: {e}")
            return 0.0

    def _calculate_rx_health_score(
        self,
        counters: Dict[str, int],
        buffer: Dict[str, Any],
        plugin_errors: int,
        plugin_timeouts: int
    ) -> float:
        """Calculate RX worker health score (0-100)"""
        try:
            score = 100.0

            # Deduct for message drops
            total_messages = counters['received']
            if total_messages > 0:
                drop_rate = counters['dropped'] / total_messages
                if drop_rate > 0.05:
                    score -= 30
                elif drop_rate > 0.01:
                    score -= 15

            # Deduct for buffer issues
            if buffer['max_size'] > 0:
                buffer_util = (buffer['current_size'] / buffer['max_size']) * 100
                if buffer_util > 95:
                    score -= 25
                elif buffer_util > 80:
                    score -= 10

            if buffer['overflow_count'] > 0:
                score -= 20

            # Deduct for plugin issues
            if total_messages > 0:
                plugin_error_rate = (plugin_errors + plugin_timeouts) / total_messages
                if plugin_error_rate > 0.05:
                    score -= 20
                elif plugin_error_rate > 0.01:
                    score -= 10

            return max(0.0, score)

        except Exception as e:
            logger.debug(f"Failed to calculate RX health score: {e}")
            return 50.0

    def _store_rx_metrics(self, tak_server_id: int, metrics: RxWorkerMetrics):
        """Store RX metrics in history"""
        if tak_server_id not in self.rx_metrics_history:
            retention_hours = self.config.get("metrics_retention_hours", 24)
            max_samples = retention_hours * 360  # 10-second intervals
            self.rx_metrics_history[tak_server_id] = deque(maxlen=max_samples)

        self.rx_metrics_history[tak_server_id].append(metrics)

    def _store_plugin_metrics(self, plugin_key: str, metrics: PluginPerformanceMetrics):
        """Store plugin metrics in history"""
        if plugin_key not in self.plugin_metrics_history:
            retention_hours = self.config.get("metrics_retention_hours", 24)
            max_samples = retention_hours * 360
            self.plugin_metrics_history[plugin_key] = deque(maxlen=max_samples)

        self.plugin_metrics_history[plugin_key].append(metrics)

    async def _analyze_rx_health(self, metrics: RxWorkerMetrics):
        """Analyze RX worker health and generate alerts"""
        try:
            alerts = []
            thresholds = self.config.get("thresholds", {})

            # Check message rate
            if metrics.messages_per_second >= thresholds.get("messages_per_second_critical", 500):
                alerts.append(self._create_alert(
                    metrics.tak_server_id,
                    "throughput",
                    "critical",
                    f"Critical message rate: {metrics.messages_per_second:.1f} msg/s",
                    {"messages_per_second": metrics.messages_per_second}
                ))
            elif metrics.messages_per_second >= thresholds.get("messages_per_second_warning", 100):
                alerts.append(self._create_alert(
                    metrics.tak_server_id,
                    "throughput",
                    "warning",
                    f"High message rate: {metrics.messages_per_second:.1f} msg/s",
                    {"messages_per_second": metrics.messages_per_second}
                ))

            # Check buffer utilization
            if metrics.buffer_max_size > 0:
                buffer_util = (metrics.buffer_size / metrics.buffer_max_size) * 100
                if buffer_util >= thresholds.get("buffer_utilization_critical", 95):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "buffer",
                        "critical",
                        f"Buffer nearly full: {buffer_util:.1f}%",
                        {"buffer_utilization": buffer_util}
                    ))
                elif buffer_util >= thresholds.get("buffer_utilization_warning", 80):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "buffer",
                        "warning",
                        f"Buffer utilization high: {buffer_util:.1f}%",
                        {"buffer_utilization": buffer_util}
                    ))

            # Check drop rate
            if metrics.messages_received > 0:
                drop_rate = metrics.messages_dropped / metrics.messages_received
                if drop_rate >= thresholds.get("drop_rate_critical", 0.05):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "error",
                        "critical",
                        f"High message drop rate: {drop_rate*100:.1f}%",
                        {"drop_rate": drop_rate}
                    ))
                elif drop_rate >= thresholds.get("drop_rate_warning", 0.01):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "error",
                        "warning",
                        f"Elevated message drop rate: {drop_rate*100:.1f}%",
                        {"drop_rate": drop_rate}
                    ))

            # Process alerts
            for alert in alerts:
                await self._process_alert(alert)

        except Exception as e:
            logger.error(f"Failed to analyze RX health for TAK server {metrics.tak_server_id}: {e}")

    async def _analyze_plugin_health(self, metrics: PluginPerformanceMetrics):
        """Analyze plugin health and generate alerts"""
        try:
            alerts = []
            thresholds = self.config.get("thresholds", {})

            # Check plugin latency
            if metrics.average_latency_ms >= thresholds.get("plugin_latency_critical", 5000):
                alerts.append(self._create_alert(
                    metrics.tak_server_id,
                    "plugin",
                    "critical",
                    f"Plugin {metrics.plugin_type} latency critical: {metrics.average_latency_ms:.0f}ms",
                    {"plugin_type": metrics.plugin_type, "latency_ms": metrics.average_latency_ms}
                ))
            elif metrics.average_latency_ms >= thresholds.get("plugin_latency_warning", 1000):
                alerts.append(self._create_alert(
                    metrics.tak_server_id,
                    "plugin",
                    "warning",
                    f"Plugin {metrics.plugin_type} latency high: {metrics.average_latency_ms:.0f}ms",
                    {"plugin_type": metrics.plugin_type, "latency_ms": metrics.average_latency_ms}
                ))

            # Check plugin error rate
            total_handled = metrics.messages_handled
            if total_handled > 0:
                error_rate = (metrics.errors + metrics.timeouts) / total_handled
                if error_rate >= thresholds.get("plugin_error_rate_critical", 0.05):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "plugin",
                        "critical",
                        f"Plugin {metrics.plugin_type} error rate critical: {error_rate*100:.1f}%",
                        {"plugin_type": metrics.plugin_type, "error_rate": error_rate}
                    ))
                elif error_rate >= thresholds.get("plugin_error_rate_warning", 0.01):
                    alerts.append(self._create_alert(
                        metrics.tak_server_id,
                        "plugin",
                        "warning",
                        f"Plugin {metrics.plugin_type} error rate elevated: {error_rate*100:.1f}%",
                        {"plugin_type": metrics.plugin_type, "error_rate": error_rate}
                    ))

            # Process alerts
            for alert in alerts:
                await self._process_alert(alert)

        except Exception as e:
            logger.error(f"Failed to analyze plugin health for {metrics.plugin_type}: {e}")

    def _create_alert(
        self,
        tak_server_id: int,
        alert_type: str,
        severity: str,
        message: str,
        metrics: Dict[str, Any]
    ) -> RxAlert:
        """Create an RX alert"""
        alert_id = f"{tak_server_id}_{alert_type}_{severity}_{int(time.time())}"

        return RxAlert(
            alert_id=alert_id,
            tak_server_id=tak_server_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            timestamp=datetime.now(timezone.utc),
            metrics=metrics
        )

    async def _process_alert(self, alert: RxAlert):
        """Process and potentially send an alert"""
        try:
            if not self.config.get("alerting", {}).get("enabled", True):
                return

            # Check cooldown
            cooldown_key = f"{alert.tak_server_id}_{alert.alert_type}_{alert.severity}"
            cooldown_minutes = self.config.get("alerting", {}).get("cooldown_minutes", 15)

            if cooldown_key in self.alert_cooldowns:
                time_since_last = (
                    datetime.now(timezone.utc) - self.alert_cooldowns[cooldown_key]
                )
                if time_since_last.total_seconds() < cooldown_minutes * 60:
                    return

            # Log the alert
            log_level = logging.CRITICAL if alert.severity == "critical" else logging.WARNING
            logger.log(log_level, f"RX Alert: {alert.message}")

            # Store in history
            self.alerts_history.append(alert)

            # Update cooldown
            self.alert_cooldowns[cooldown_key] = alert.timestamp

            # Call alert callbacks
            for callback in self.alert_callbacks:
                try:
                    await callback(alert)
                except Exception as e:
                    logger.error(f"RX alert callback failed: {e}")

        except Exception as e:
            logger.error(f"Failed to process RX alert: {e}")

    def _cleanup_old_data(self):
        """Clean up old metrics and alerts"""
        try:
            retention_hours = self.config.get("metrics_retention_hours", 24)
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=retention_hours)

            # Clean up alert cooldowns
            expired_cooldowns = [
                key for key, timestamp in self.alert_cooldowns.items()
                if timestamp < cutoff_time
            ]
            for key in expired_cooldowns:
                del self.alert_cooldowns[key]

            # Trim plugin latency samples
            max_samples = self.config.get("plugin_latency_samples", 100)
            for plugin_key in self.plugin_latencies.keys():
                if len(self.plugin_latencies[plugin_key]) > max_samples:
                    self.plugin_latencies[plugin_key] = self.plugin_latencies[plugin_key][-max_samples:]

        except Exception as e:
            logger.error(f"Failed to cleanup old RX data: {e}")

    # Public API for recording metrics

    def record_message_received(self, tak_server_id: int, message_size: int):
        """Record a received message"""
        self.message_counters[tak_server_id]['received'] += 1
        self.byte_counters[tak_server_id] += message_size

    def record_message_processed(self, tak_server_id: int):
        """Record a processed message"""
        self.message_counters[tak_server_id]['processed'] += 1

    def record_message_dropped(self, tak_server_id: int):
        """Record a dropped message"""
        self.message_counters[tak_server_id]['dropped'] += 1

    def record_message_malicious(self, tak_server_id: int):
        """Record a malicious message"""
        self.message_counters[tak_server_id]['malicious'] += 1

    def record_buffer_stats(self, tak_server_id: int, current_size: int, max_size: int):
        """Record buffer statistics"""
        self.buffer_stats[tak_server_id]['current_size'] = current_size
        self.buffer_stats[tak_server_id]['max_size'] = max_size

    def record_buffer_overflow(self, tak_server_id: int):
        """Record a buffer overflow event"""
        self.buffer_stats[tak_server_id]['overflow_count'] += 1

    def record_plugin_execution(
        self,
        tak_server_id: int,
        stream_id: int,
        plugin_type: str,
        latency_ms: float,
        handled: bool,
        error: bool = False,
        timeout: bool = False
    ):
        """Record plugin execution metrics"""
        plugin_key = f"{tak_server_id}_{stream_id}_{plugin_type}"

        # Record latency
        max_samples = self.config.get("plugin_latency_samples", 100)
        if len(self.plugin_latencies[plugin_key]) >= max_samples:
            self.plugin_latencies[plugin_key].pop(0)
        self.plugin_latencies[plugin_key].append(latency_ms)

        # Record counters
        if handled:
            self.plugin_counters[plugin_key]['handled'] += 1
        else:
            self.plugin_counters[plugin_key]['filtered'] += 1

        if error:
            self.plugin_counters[plugin_key]['errors'] += 1

        if timeout:
            self.plugin_counters[plugin_key]['timeouts'] += 1

    def add_alert_callback(self, callback):
        """Add a callback function for alert notifications"""
        self.alert_callbacks.append(callback)

    def get_rx_metrics(self, tak_server_id: int) -> Optional[RxWorkerMetrics]:
        """Get latest RX metrics for a TAK server"""
        return self.last_rx_metrics.get(tak_server_id)

    def get_plugin_metrics(self, plugin_key: str) -> Optional[PluginPerformanceMetrics]:
        """Get latest plugin metrics"""
        return self.last_plugin_metrics.get(plugin_key)

    def get_rx_metrics_history(
        self, tak_server_id: int, hours: int = 1
    ) -> List[RxWorkerMetrics]:
        """Get historical RX metrics for a TAK server"""
        if tak_server_id not in self.rx_metrics_history:
            return []

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            m for m in self.rx_metrics_history[tak_server_id]
            if m.timestamp >= cutoff_time
        ]

    def get_recent_alerts(self, hours: int = 1) -> List[RxAlert]:
        """Get recent RX alerts"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            alert for alert in self.alerts_history
            if alert.timestamp >= cutoff_time
        ]


# Global monitoring service instance
_rx_monitoring_service = None


def get_rx_monitoring_service(
    config: Optional[Dict[str, Any]] = None
) -> RxMonitoringService:
    """
    Get the global RX monitoring service instance (singleton pattern).

    Args:
        config: Configuration dictionary (only used on first call)

    Returns:
        RxMonitoringService instance
    """
    global _rx_monitoring_service
    if _rx_monitoring_service is None:
        _rx_monitoring_service = RxMonitoringService(config)
    return _rx_monitoring_service


def reset_rx_monitoring_service():
    """Reset the global RX monitoring service (mainly for testing)"""
    global _rx_monitoring_service
    _rx_monitoring_service = None
