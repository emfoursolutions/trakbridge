"""
ABOUTME: Automated recovery service for self-healing capabilities and failure recovery
ABOUTME: providing intelligent restart logic, health monitoring, and automatic component recovery

File: services/recovery_service.py

Description:
    Comprehensive automated recovery service for TrakBridge providing self-healing
    capabilities for failed components. Integrates with health monitoring, circuit
    breakers, and system monitoring to automatically detect failures and initiate
    recovery procedures with intelligent retry logic and escalation policies.

Key features:
    - Automatic failure detection and recovery initiation
    - Integration with circuit breakers and health monitoring services
    - Component-specific recovery strategies (streams, TAK servers, plugins)
    - Escalating recovery procedures with configurable retry policies
    - Recovery metrics tracking and performance monitoring
    - Notification and alerting capabilities for recovery events
    - Dependency analysis and ordered recovery sequencing
    - Recovery state management and coordination

Author: TrakBridge Development Team
Created: 2025-09-27
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Set
from dataclasses import dataclass, field
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)


class RecoveryStatus(Enum):
    """Recovery attempt status"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


class ComponentType(Enum):
    """Types of components that can be recovered"""

    STREAM = "stream"
    TAK_SERVER = "tak_server"
    PLUGIN = "plugin"
    DATABASE = "database"
    QUEUE = "queue"
    CIRCUIT_BREAKER = "circuit_breaker"


@dataclass
class RecoveryConfig:
    """Configuration for recovery behavior"""

    max_retry_attempts: int = 3
    initial_retry_delay: float = 5.0
    max_retry_delay: float = 300.0
    exponential_backoff_factor: float = 2.0
    health_check_interval: float = 30.0
    recovery_timeout: float = 120.0
    escalation_enabled: bool = True
    notification_enabled: bool = True

    # Component-specific settings
    stream_restart_enabled: bool = True
    tak_server_reconnect_enabled: bool = True
    plugin_reload_enabled: bool = True
    circuit_breaker_reset_enabled: bool = True

    # Dependency management
    respect_dependencies: bool = True
    parallel_recovery: bool = False


@dataclass
class RecoveryAttempt:
    """Record of a recovery attempt"""

    component_id: str
    component_type: ComponentType
    attempt_number: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: RecoveryStatus = RecoveryStatus.PENDING
    error_message: Optional[str] = None
    recovery_method: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class RecoveryPlan:
    """Recovery plan for a component"""

    component_id: str
    component_type: ComponentType
    recovery_methods: List[str] = field(default_factory=list)
    dependencies: Set[str] = field(default_factory=set)
    priority: int = 1  # Higher number = higher priority
    config: Optional[RecoveryConfig] = None


class RecoveryService:
    """
    Automated recovery service providing self-healing capabilities.

    This service monitors component health and automatically initiates
    recovery procedures when failures are detected, with intelligent
    retry logic and escalation policies.
    """

    def __init__(self, config: Optional[RecoveryConfig] = None):
        """Initialize recovery service"""
        self.config = config or RecoveryConfig()

        # Recovery state tracking
        self.active_recoveries: Dict[str, RecoveryAttempt] = {}
        self.recovery_history: List[RecoveryAttempt] = []
        self.recovery_plans: Dict[str, RecoveryPlan] = {}

        # Service management
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None

        # Recovery methods registry
        self.recovery_methods: Dict[ComponentType, Dict[str, Callable]] = {
            ComponentType.STREAM: {},
            ComponentType.TAK_SERVER: {},
            ComponentType.PLUGIN: {},
            ComponentType.DATABASE: {},
            ComponentType.QUEUE: {},
            ComponentType.CIRCUIT_BREAKER: {},
        }

        # Health check functions registry
        self.health_checkers: Dict[str, Callable] = {}

        # Dependencies tracking
        self.component_dependencies: Dict[str, Set[str]] = {}

        # Metrics
        self.recovery_stats = {
            "total_attempts": 0,
            "successful_recoveries": 0,
            "failed_recoveries": 0,
            "escalated_recoveries": 0,
            "abandoned_recoveries": 0,
        }

        logger.info("Recovery service initialized")

    async def start(self):
        """Start the recovery service monitoring"""
        if self.running:
            logger.warning("Recovery service already running")
            return

        self.running = True
        self.monitor_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Recovery service started")

    async def stop(self):
        """Stop the recovery service"""
        self.running = False

        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

        # Wait for active recoveries to complete
        if self.active_recoveries:
            logger.info(
                f"Waiting for {len(self.active_recoveries)} active recoveries to complete"
            )
            await asyncio.sleep(5)  # Give some time for completion

        logger.info("Recovery service stopped")

    async def _monitoring_loop(self):
        """Main monitoring loop for health checks and recovery initiation"""
        while self.running:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in recovery monitoring loop: {e}")
                await asyncio.sleep(self.config.health_check_interval)

    async def _perform_health_checks(self):
        """Perform health checks on registered components"""
        for component_id, health_checker in self.health_checkers.items():
            if component_id in self.active_recoveries:
                continue  # Skip if already recovering

            try:
                is_healthy = await health_checker()
                if not is_healthy:
                    logger.warning(f"Health check failed for component {component_id}")
                    await self.initiate_recovery(component_id)

            except Exception as e:
                logger.error(f"Health check error for component {component_id}: {e}")
                await self.initiate_recovery(component_id)

    def register_component(
        self,
        component_id: str,
        component_type: ComponentType,
        health_checker: Callable[[], bool],
        recovery_plan: Optional[RecoveryPlan] = None,
    ):
        """
        Register a component for automated recovery.

        Args:
            component_id: Unique identifier for the component
            component_type: Type of component
            health_checker: Async function that returns True if component is healthy
            recovery_plan: Optional custom recovery plan
        """
        self.health_checkers[component_id] = health_checker

        if recovery_plan:
            self.recovery_plans[component_id] = recovery_plan
        else:
            # Create default recovery plan
            self.recovery_plans[component_id] = RecoveryPlan(
                component_id=component_id,
                component_type=component_type,
                recovery_methods=self._get_default_recovery_methods(component_type),
                config=self.config,
            )

        logger.info(f"Registered component {component_id} for automated recovery")

    def _get_default_recovery_methods(self, component_type: ComponentType) -> List[str]:
        """Get default recovery methods for a component type"""
        defaults = {
            ComponentType.STREAM: ["restart_stream", "reset_plugin", "reconnect_tak"],
            ComponentType.TAK_SERVER: [
                "reconnect",
                "reset_circuit_breaker",
                "recreate_connection",
            ],
            ComponentType.PLUGIN: [
                "reload_plugin",
                "reset_configuration",
                "restart_stream",
            ],
            ComponentType.DATABASE: [
                "reconnect",
                "reset_connection_pool",
                "restart_service",
            ],
            ComponentType.QUEUE: ["flush_queue", "restart_queue", "reset_manager"],
            ComponentType.CIRCUIT_BREAKER: [
                "reset_circuit",
                "force_close",
                "reconfigure",
            ],
        }
        return defaults.get(component_type, ["generic_restart"])

    def register_recovery_method(
        self,
        component_type: ComponentType,
        method_name: str,
        method_func: Callable[[str], bool],
    ):
        """
        Register a recovery method for a component type.

        Args:
            component_type: Type of component this method can recover
            method_name: Name of the recovery method
            method_func: Async function that takes component_id and returns success status
        """
        self.recovery_methods[component_type][method_name] = method_func
        logger.info(
            f"Registered recovery method {method_name} for {component_type.value}"
        )

    async def initiate_recovery(self, component_id: str, force: bool = False) -> bool:
        """
        Initiate recovery for a failed component.

        Args:
            component_id: Component to recover
            force: Force recovery even if already in progress

        Returns:
            True if recovery was initiated successfully
        """
        if component_id in self.active_recoveries and not force:
            logger.info(f"Recovery already in progress for component {component_id}")
            return False

        if component_id not in self.recovery_plans:
            logger.error(f"No recovery plan found for component {component_id}")
            return False

        plan = self.recovery_plans[component_id]

        # Check dependencies if enabled
        if self.config.respect_dependencies and plan.dependencies:
            for dependency in plan.dependencies:
                if dependency in self.active_recoveries:
                    logger.info(
                        f"Waiting for dependency {dependency} recovery to complete"
                    )
                    return False

        # Create recovery attempt
        attempt = RecoveryAttempt(
            component_id=component_id,
            component_type=plan.component_type,
            attempt_number=self._get_next_attempt_number(component_id),
            started_at=datetime.now(timezone.utc),
            status=RecoveryStatus.IN_PROGRESS,
        )

        self.active_recoveries[component_id] = attempt
        self.recovery_stats["total_attempts"] += 1

        logger.info(
            f"Initiating recovery for component {component_id} (attempt #{attempt.attempt_number})"
        )

        # Start recovery task
        asyncio.create_task(self._execute_recovery(attempt, plan))
        return True

    def _get_next_attempt_number(self, component_id: str) -> int:
        """Get the next attempt number for a component"""
        attempts = [
            r.attempt_number
            for r in self.recovery_history
            if r.component_id == component_id
        ]
        return max(attempts, default=0) + 1

    async def _execute_recovery(self, attempt: RecoveryAttempt, plan: RecoveryPlan):
        """Execute recovery for a component"""
        try:
            config = plan.config or self.config

            # Try each recovery method
            for method_name in plan.recovery_methods:
                if attempt.attempt_number > config.max_retry_attempts:
                    attempt.status = RecoveryStatus.ABANDONED
                    break

                logger.info(
                    f"Attempting recovery method {method_name} for {attempt.component_id}"
                )
                attempt.recovery_method = method_name

                try:
                    # Get recovery method
                    recovery_func = self.recovery_methods[plan.component_type].get(
                        method_name
                    )
                    if not recovery_func:
                        logger.warning(
                            f"Recovery method {method_name} not found for {plan.component_type.value}"
                        )
                        continue

                    # Execute recovery with timeout
                    success = await asyncio.wait_for(
                        recovery_func(attempt.component_id),
                        timeout=config.recovery_timeout,
                    )

                    if success:
                        # Verify recovery with health check
                        if await self._verify_recovery(attempt.component_id):
                            attempt.status = RecoveryStatus.SUCCEEDED
                            self.recovery_stats["successful_recoveries"] += 1
                            logger.info(
                                f"Recovery succeeded for {attempt.component_id} using {method_name}"
                            )
                            break
                        else:
                            logger.warning(
                                f"Recovery method {method_name} completed but health check still fails"
                            )

                except asyncio.TimeoutError:
                    logger.error(
                        f"Recovery method {method_name} timed out for {attempt.component_id}"
                    )
                except Exception as e:
                    logger.error(
                        f"Recovery method {method_name} failed for {attempt.component_id}: {e}"
                    )
                    attempt.error_message = str(e)

                # Apply exponential backoff between attempts
                if (
                    method_name != plan.recovery_methods[-1]
                ):  # Don't delay after last method
                    delay = min(
                        config.initial_retry_delay
                        * (
                            config.exponential_backoff_factor
                            ** (attempt.attempt_number - 1)
                        ),
                        config.max_retry_delay,
                    )
                    await asyncio.sleep(delay)

            # Handle final status
            if attempt.status == RecoveryStatus.IN_PROGRESS:
                if (
                    config.escalation_enabled
                    and attempt.attempt_number <= config.max_retry_attempts
                ):
                    attempt.status = RecoveryStatus.ESCALATED
                    self.recovery_stats["escalated_recoveries"] += 1
                    await self._escalate_recovery(attempt, plan)
                else:
                    attempt.status = RecoveryStatus.FAILED
                    self.recovery_stats["failed_recoveries"] += 1

        except Exception as e:
            logger.error(f"Error executing recovery for {attempt.component_id}: {e}")
            attempt.status = RecoveryStatus.FAILED
            attempt.error_message = str(e)
            self.recovery_stats["failed_recoveries"] += 1

        finally:
            # Complete recovery attempt
            attempt.completed_at = datetime.now(timezone.utc)
            attempt.duration_seconds = (
                attempt.completed_at - attempt.started_at
            ).total_seconds()

            # Move to history and clean up
            self.recovery_history.append(attempt)
            if attempt.component_id in self.active_recoveries:
                del self.active_recoveries[attempt.component_id]

            # Limit history size
            if len(self.recovery_history) > 1000:
                self.recovery_history = self.recovery_history[-1000:]

            logger.info(
                f"Recovery completed for {attempt.component_id}: "
                f"status={attempt.status.value}, duration={attempt.duration_seconds:.2f}s"
            )

    async def _verify_recovery(self, component_id: str) -> bool:
        """Verify that recovery was successful by running health check"""
        if component_id not in self.health_checkers:
            return True  # Can't verify, assume success

        try:
            return await self.health_checkers[component_id]()
        except Exception as e:
            logger.error(f"Health check verification failed for {component_id}: {e}")
            return False

    async def _escalate_recovery(self, attempt: RecoveryAttempt, plan: RecoveryPlan):
        """Escalate recovery to higher-level procedures"""
        logger.warning(f"Escalating recovery for {attempt.component_id}")

        # Try more aggressive recovery methods
        escalation_methods = {
            ComponentType.STREAM: ["force_restart_stream", "recreate_stream"],
            ComponentType.TAK_SERVER: ["force_disconnect", "recreate_tak_server"],
            ComponentType.PLUGIN: ["force_reload_plugin", "reset_plugin_state"],
            ComponentType.DATABASE: [
                "restart_database_service",
                "recreate_database_connection",
            ],
            ComponentType.QUEUE: ["recreate_queue_manager", "restart_queue_service"],
            ComponentType.CIRCUIT_BREAKER: [
                "force_reset_all_circuits",
                "reinitialize_circuit_breaker",
            ],
        }

        escalation_list = escalation_methods.get(plan.component_type, [])

        for method_name in escalation_list:
            try:
                recovery_func = self.recovery_methods[plan.component_type].get(
                    method_name
                )
                if recovery_func:
                    success = await recovery_func(attempt.component_id)
                    if success and await self._verify_recovery(attempt.component_id):
                        attempt.status = RecoveryStatus.SUCCEEDED
                        logger.info(
                            f"Escalated recovery succeeded for {attempt.component_id} using {method_name}"
                        )
                        return

            except Exception as e:
                logger.error(f"Escalated recovery method {method_name} failed: {e}")

        # If all escalation methods failed
        attempt.status = RecoveryStatus.FAILED
        logger.error(f"All escalation methods failed for {attempt.component_id}")

    def get_recovery_status(self, component_id: str) -> Optional[Dict[str, Any]]:
        """Get current recovery status for a component"""
        if component_id in self.active_recoveries:
            attempt = self.active_recoveries[component_id]
            return {
                "status": attempt.status.value,
                "attempt_number": attempt.attempt_number,
                "started_at": attempt.started_at.isoformat(),
                "recovery_method": attempt.recovery_method,
                "duration": (
                    datetime.now(timezone.utc) - attempt.started_at
                ).total_seconds(),
            }

        # Check recent history
        recent_attempts = [
            r
            for r in self.recovery_history[-50:]  # Last 50 attempts
            if r.component_id == component_id
        ]

        if recent_attempts:
            latest = recent_attempts[-1]
            return {
                "status": latest.status.value,
                "attempt_number": latest.attempt_number,
                "completed_at": (
                    latest.completed_at.isoformat() if latest.completed_at else None
                ),
                "recovery_method": latest.recovery_method,
                "duration": latest.duration_seconds,
                "error_message": latest.error_message,
            }

        return None

    def get_service_status(self) -> Dict[str, Any]:
        """Get overall recovery service status"""
        return {
            "running": self.running,
            "active_recoveries": len(self.active_recoveries),
            "registered_components": len(self.health_checkers),
            "statistics": self.recovery_stats.copy(),
            "config": {
                "health_check_interval": self.config.health_check_interval,
                "max_retry_attempts": self.config.max_retry_attempts,
                "escalation_enabled": self.config.escalation_enabled,
            },
        }

    async def force_recovery(self, component_id: str) -> bool:
        """Force immediate recovery for a component"""
        logger.info(f"Forcing recovery for component {component_id}")
        return await self.initiate_recovery(component_id, force=True)

    async def cancel_recovery(self, component_id: str) -> bool:
        """Cancel ongoing recovery for a component"""
        if component_id in self.active_recoveries:
            attempt = self.active_recoveries[component_id]
            attempt.status = RecoveryStatus.ABANDONED
            attempt.completed_at = datetime.now(timezone.utc)

            self.recovery_history.append(attempt)
            del self.active_recoveries[component_id]
            self.recovery_stats["abandoned_recoveries"] += 1

            logger.info(f"Cancelled recovery for component {component_id}")
            return True

        return False


# Global recovery service instance
_recovery_service: Optional[RecoveryService] = None


def get_recovery_service(config: Optional[RecoveryConfig] = None) -> RecoveryService:
    """Get the global recovery service instance"""
    global _recovery_service
    if _recovery_service is None:
        _recovery_service = RecoveryService(config)
    return _recovery_service


def reset_recovery_service():
    """Reset the global recovery service (mainly for testing)"""
    global _recovery_service
    if _recovery_service:
        asyncio.create_task(_recovery_service.stop())
    _recovery_service = None
