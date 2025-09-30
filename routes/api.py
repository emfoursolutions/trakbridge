"""
File: routes/api.py

Description:
    Comprehensive API blueprint providing health monitoring, system status, and stream management endpoints
    for the TrakBridge application. This module serves as the primary API interface for monitoring system
    health, managing stream operations, and retrieving operational statistics. The blueprint implements
    both basic and detailed health checks with caching mechanisms to optimize performance.

Key features:
    - System health monitoring with detailed component checks (database, encryption, stream manager, system resources)
    - Kubernetes-compatible readiness and liveness probes for container orchestration
    - Stream management APIs for statistics, status monitoring, and configuration export
    - Plugin health checks and configuration metadata retrieval
    - Bulk operations for starting/stopping all streams and running system-wide health checks
    - Threaded caching system for health check results to reduce system load
    - Comprehensive error handling with appropriate HTTP status codes
    - Real-time system resource monitoring (CPU, memory, disk usage)
    - Security status monitoring and configuration validation
    - Background cache cleanup to prevent memory leaks

Author: Emfour Solutions
Created: 18-Jul-2025
"""

# Third-party imports
import asyncio

# Standard library imports
import threading
import time
from datetime import datetime, timedelta, timezone

import psutil
from flask import Blueprint, current_app, jsonify, request

# Local application imports
from database import db

# Authentication imports
from services.auth import (
    api_key_or_auth_required,
    optional_auth,
    require_auth,
    require_permission,
)
from services.connection_test_service import ConnectionTestService
from services.health_service import health_service

# Module-level logger
from services.logging_service import get_module_logger

# Team member configuration constants
TEAM_MEMBER_ROLES = [
    "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
    "Forward Observer", "RTO", "K9"
]

TEAM_MEMBER_COLORS = [
    "Teal", "Green", "Dark Green", "Brown", "White", "Yellow",
    "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue",
    "Blue", "Cyan"
]

COT_TYPE_OPTIONS = ["Default", "Standard Point", "Team Member"]


def validate_team_member_configuration(cot_type_override, team_role, team_color):
    """
    Validate team member configuration and return error message if invalid.

    Returns:
        None if valid, error message string if invalid
    """
    if cot_type_override == "team_member":
        if not team_role or not team_color:
            return "Team member configuration requires both role and color"

        if team_role not in TEAM_MEMBER_ROLES:
            return f"Invalid team role: {team_role}. Must be one of: {', '.join(TEAM_MEMBER_ROLES)}"

        if team_color not in TEAM_MEMBER_COLORS:
            return f"Invalid team color: {team_color}. Must be one of: {', '.join(TEAM_MEMBER_COLORS)}"

    return None


from services.plugin_category_service import get_category_service
from services.stream_config_service import StreamConfigService
from services.stream_display_service import StreamDisplayService
from services.stream_operations_service import StreamOperationsService
from services.stream_status_service import StreamStatusService
from services.version import format_version, get_version
from utils.app_helpers import get_plugin_manager

logger = get_module_logger(__name__)

bp = Blueprint("api", __name__)

# Cache for health check results to avoid excessive checks
_health_cache = {}
_cache_lock = threading.Lock()
CACHE_DURATION = 30  # seconds


def get_display_service():
    """Get the display service with current app context"""
    return StreamDisplayService(get_plugin_manager())


def get_config_service():
    """Get the config service with current app context"""
    return StreamConfigService(get_plugin_manager())


def get_stream_services():
    """Get stream services with safe attribute access"""
    app_context_factory = getattr(current_app, "app_context_factory", None)
    if app_context_factory is None:
        # Fallback to the default Flask app context method
        app_context_factory = current_app.app_context

    stream_manager = getattr(current_app, "stream_manager", None)
    if stream_manager is None:
        raise ValueError("Stream manager not found in current_app")

    plugin_manager = getattr(current_app, "plugin_manager", None)
    if plugin_manager is None:
        raise ValueError("Plugin manager not found in current_app")

    return {
        "operations_service": StreamOperationsService(stream_manager, db),
        "test_service": ConnectionTestService(plugin_manager, stream_manager),
        "status_service": StreamStatusService(stream_manager),
    }


def get_cached_health_check(check_name, check_function, *args, **kwargs):
    """Get cached health check result or run fresh check if cache expired"""
    with _cache_lock:
        now = time.time()
        cache_key = check_name

        # Check if we have a valid cached result
        if (
            cache_key in _health_cache
            and now - _health_cache[cache_key]["timestamp"] < CACHE_DURATION
        ):
            return _health_cache[cache_key]["result"]

        # Run fresh check
        try:
            result = check_function(*args, **kwargs)
            _health_cache[cache_key] = {"result": result, "timestamp": now}
            return result
        except Exception as e:
            error_result = {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _health_cache[cache_key] = {"result": error_result, "timestamp": now}
            return error_result


# =============================================================================
# System Health API Routes
# =============================================================================


@bp.route("/status")
@optional_auth
def api_status():
    """API endpoint for system status"""
    # Import models inside the route to avoid circular imports
    from models.stream import Stream
    from models.tak_server import TakServer

    streams = Stream.query.all()

    # Handle stream_manager import carefully
    try:
        from services.stream_manager import get_stream_manager

        stream_manager = get_stream_manager()

        running_workers = len(stream_manager.workers) if stream_manager else 0
    except ImportError:
        running_workers = 0

    return jsonify(
        {
            "total_streams": len(streams),
            "active_streams": sum(1 for s in streams if s.is_active),
            "tak_servers": TakServer.query.count(),
            "running_workers": running_workers,
        }
    )


@bp.route("/health")
def health_check():
    """Basic health check endpoint - always responds even during startup"""
    try:
        from app import get_startup_status

        startup_status = get_startup_status()

        # Return different status based on startup state
        if startup_status["complete"]:
            status = "healthy"
            http_code = 200
        elif startup_status["error"]:
            status = "unhealthy"
            http_code = 503
        else:
            status = "starting"
            http_code = 200  # Return 200 during startup so health checks pass

        response_data = {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": get_version(),
            "service": "trakbridge",
        }

        # Add startup info if not complete
        if not startup_status["complete"]:
            response_data["startup"] = {
                "complete": startup_status["complete"],
                "error": startup_status["error"],
                "progress_count": len(startup_status["progress"]),
            }

        return jsonify(response_data), http_code

    except Exception as e:
        # Fallback if startup status check fails
        logger.warning(f"Startup status check failed: {e}")
        return (
            jsonify(
                {
                    "status": "healthy",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "version": get_version(),
                    "service": "trakbridge",
                }
            ),
            200,
        )


@bp.route("/health/detailed")
@optional_auth
def detailed_health_check():
    """Detailed health check with all components"""
    start_time = time.time()

    checks = {
        "database": get_cached_health_check(
            "database", health_service.run_all_database_checks
        ),
        "encryption": get_cached_health_check("encryption", check_encryption_health),
        "configuration": get_cached_health_check(
            "configuration", check_configuration_health
        ),
        "stream_manager": get_cached_health_check(
            "stream_manager", check_stream_manager_health
        ),
        "system": get_cached_health_check("system", check_system_health),
        "streams": get_cached_health_check("streams", check_streams_health),
        "tak_servers": get_cached_health_check("tak_servers", check_tak_servers_health),
    }

    # Determine overall status
    overall_status = "healthy"
    critical_failures = []

    for check_name, check_result in checks.items():
        if check_result.get("status") == "unhealthy":
            if check_name in ["database", "encryption"]:  # Critical components
                overall_status = "unhealthy"
                critical_failures.append(check_name)
            elif overall_status != "unhealthy":
                overall_status = "degraded"

    response_time = round((time.time() - start_time) * 1000, 2)  # ms

    result = {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "response_time_ms": response_time,
        "version": get_version(),
        "service": "trakbridge",
        "checks": checks,
    }

    if critical_failures:
        result["critical_failures"] = critical_failures

    # Return appropriate HTTP status code
    status_code = 200
    if overall_status == "unhealthy":
        status_code = 503  # Service Unavailable
    elif overall_status == "degraded":
        status_code = 200  # OK but with warnings

    return jsonify(result), status_code


@bp.route("/health/ready")
def readiness_check():
    """Kubernetes readiness probe - checks if app is ready to serve traffic"""

    checks = {
        "database": health_service.check_database_connectivity,
        "encryption": check_encryption_health,
    }

    for check_name, check_func in checks.items():
        result = get_cached_health_check(check_name, check_func)

        if result.get("status") != "healthy":
            return (
                jsonify(
                    {
                        "status": "not_ready",
                        "failed_check": check_name,
                        "error": result.get("error", "Unknown error"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ),
                503,
            )

    return jsonify(
        {"status": "ready", "timestamp": datetime.now(timezone.utc).isoformat()}
    )


@bp.route("/health/live")
def liveness_check():
    """Kubernetes liveness probe - basic check if app is alive"""
    return jsonify(
        {
            "status": "alive",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": get_uptime_seconds(),
        }
    )


@bp.route("/health/database")
@optional_auth
def database_health():
    """Database-specific health check"""
    result = get_cached_health_check("database", health_service.run_all_database_checks)

    # Return appropriate HTTP status code
    status_code = 503 if result.get("status") == "unhealthy" else 200
    return jsonify(result), status_code


# Legacy function for backward compatibility
def check_database_health():
    """Legacy database health check - now delegates to health service"""
    return health_service.check_database_connectivity()


def check_encryption_health():
    """Check encryption service health"""
    try:
        from services.encryption_service import encryption_service

        return encryption_service.health_check()
    except Exception as e:
        logger.error(f"Encryption health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "error_type": type(e).__name__}


def check_configuration_health():
    """Check configuration management health with validation and status"""
    try:
        from utils.config_manager import config_manager

        # Get detailed configuration validation results
        results = config_manager.validate_all_configs()

        # Count status
        total_configs = len(results)
        valid_configs = len([r for r in results.values() if r is True])
        invalid_configs = total_configs - valid_configs

        # Determine overall configuration health status
        if invalid_configs == 0:
            overall_status = "healthy"
            message = f"All {total_configs} configuration files are valid"
        elif invalid_configs < total_configs / 2:
            overall_status = "degraded"
            message = f"{valid_configs}/{total_configs} configuration files are valid"
        else:
            overall_status = "unhealthy"
            message = (
                f"Only {valid_configs}/{total_configs} configuration files are valid"
            )

        # Build detailed response
        health_response = {
            "status": overall_status,
            "message": message,
            "details": {
                "total_configs": total_configs,
                "valid_configs": valid_configs,
                "invalid_configs": invalid_configs,
                "config_status": results,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Add summary for invalid configurations
        if invalid_configs > 0:
            invalid_details = []
            for config_name, result in results.items():
                if result is not True:
                    invalid_details.append(
                        {"config": config_name, "error": str(result)}
                    )
            health_response["details"]["invalid_configs_details"] = invalid_details

        return health_response

    except Exception as e:
        logger.error(f"Configuration health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "error_type": type(e).__name__,
            "message": "Configuration health check system failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@bp.route("/health/plugins", methods=["GET"])
@require_permission("api", "read")
def plugin_health():
    """Plugin health check with safe attribute access"""
    plugin_manager = getattr(current_app, "plugin_manager", None)
    stream_manager = getattr(current_app, "stream_manager", None)

    if not plugin_manager:
        return jsonify({"error": "Plugin manager not available"}), 500
    if not stream_manager:
        return jsonify({"error": "Stream manager not available"}), 500

    # Use the background event loop from stream_manager
    future = asyncio.run_coroutine_threadsafe(
        plugin_manager.check_all_plugins_health(), stream_manager.loop
    )
    health_status = future.result()
    return jsonify(health_status)


@bp.route("/health/configuration", methods=["GET"])
@optional_auth
def configuration_health():
    """Configuration health check endpoint with detailed status"""
    result = check_configuration_health()

    # Return appropriate HTTP status code
    status_code = 503 if result.get("status") == "unhealthy" else 200
    return jsonify(result), status_code


@bp.route("/health/circuit-breakers", methods=["GET"])
@optional_auth
def circuit_breaker_health():
    """Circuit breaker health and status monitoring"""
    try:
        from services.circuit_breaker import get_circuit_breaker_manager

        manager = get_circuit_breaker_manager()
        all_status = manager.get_all_status()

        # Calculate overall health
        total_breakers = len(all_status)
        open_breakers = sum(
            1 for status in all_status.values() if status.get("state") == "open"
        )
        warning_breakers = sum(
            1 for status in all_status.values() if status.get("state") == "half_open"
        )

        overall_status = "healthy"
        if open_breakers > 0:
            overall_status = "unhealthy"
        elif warning_breakers > 0:
            overall_status = "warning"

        result = {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_circuit_breakers": total_breakers,
                "healthy_breakers": total_breakers - open_breakers - warning_breakers,
                "warning_breakers": warning_breakers,
                "failed_breakers": open_breakers,
            },
            "circuit_breakers": all_status,
        }

        status_code = 503 if overall_status == "unhealthy" else 200
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error checking circuit breaker health: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


@bp.route("/health/recovery", methods=["GET"])
@optional_auth
def recovery_service_health():
    """Recovery service health and status monitoring"""
    try:
        from services.recovery_service import get_recovery_service

        recovery_service = get_recovery_service()
        service_status = recovery_service.get_service_status()

        # Get recent recovery attempts
        recent_recoveries = []
        for attempt in recovery_service.recovery_history[-10:]:  # Last 10 attempts
            recent_recoveries.append(
                {
                    "component_id": attempt.component_id,
                    "component_type": attempt.component_type.value,
                    "status": attempt.status.value,
                    "started_at": attempt.started_at.isoformat(),
                    "completed_at": (
                        attempt.completed_at.isoformat()
                        if attempt.completed_at
                        else None
                    ),
                    "duration_seconds": attempt.duration_seconds,
                    "recovery_method": attempt.recovery_method,
                    "error_message": attempt.error_message,
                }
            )

        # Calculate health based on recent recovery success rate
        stats = service_status["statistics"]
        total_attempts = stats.get("total_attempts", 0)
        successful_recoveries = stats.get("successful_recoveries", 0)

        if total_attempts == 0:
            success_rate = 1.0
        else:
            success_rate = successful_recoveries / total_attempts

        overall_status = "healthy"
        if success_rate < 0.5:
            overall_status = "unhealthy"
        elif success_rate < 0.8:
            overall_status = "warning"

        result = {
            "status": overall_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service_status": service_status,
            "success_rate": success_rate,
            "recent_recoveries": recent_recoveries,
        }

        status_code = 503 if overall_status == "unhealthy" else 200
        return jsonify(result), status_code

    except Exception as e:
        logger.error(f"Error checking recovery service health: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


@bp.route("/monitoring/dashboard", methods=["GET"])
@optional_auth
def monitoring_dashboard():
    """Comprehensive monitoring dashboard data"""
    try:
        dashboard_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queues": {},
            "streams": {},
            "performance": {},
            "circuit_breakers": {},
            "recovery": {},
        }

        # Get queue monitoring data
        try:
            from services.queue_monitoring import get_queue_monitoring_service

            monitoring_service = get_queue_monitoring_service()
            # Get metrics for all queues
            from models.tak_server import TakServer

            tak_servers = TakServer.query.all()

            for tak_server in tak_servers:
                # HOTFIX: Ensure monitoring service uses correct queue manager instance
                try:
                    queue_manager = getattr(monitoring_service, "queue_manager", None)
                    if queue_manager:
                        from services.queue_manager import get_queue_manager

                        global_queue_manager = get_queue_manager()

                        # Fix queue manager instance mismatch if needed
                        if queue_manager is not global_queue_manager:
                            monitoring_service.queue_manager = global_queue_manager
                            logger.debug(
                                "Updated monitoring service to use global queue manager"
                            )
                except Exception as fix_error:
                    logger.debug(f"Queue manager fix attempt: {fix_error}")

                metrics = monitoring_service.get_queue_metrics(tak_server.id)

                if metrics:
                    dashboard_data["queues"][f"server_{tak_server.id}"] = {
                        "name": tak_server.name,  # Include actual server name
                        "size": metrics.current_size,
                        "throughput": metrics.events_per_second,
                        "errors": getattr(
                            metrics, "error_count", 0
                        ),  # fallback if not present
                        "health_score": metrics.health_score,
                        "utilization": metrics.utilization_percent,
                        "batches_per_second": metrics.batches_per_second,
                        "overflow_rate": metrics.overflow_rate,
                    }
                else:
                    logger.warning(
                        f"No queue metrics returned for TAK server {tak_server.id}"
                    )

                    # FALLBACK: Use global queue manager data directly
                    try:
                        from services.queue_manager import get_queue_manager

                        fallback_queue_manager = get_queue_manager()
                        fallback_statuses = (
                            fallback_queue_manager.get_all_queue_status()
                        )

                        if tak_server.id in fallback_statuses:
                            queue_status = fallback_statuses[tak_server.id]
                            logger.debug(
                                f"Using fallback queue data for server {tak_server.id}: {queue_status}"
                            )

                            # Create basic metrics from queue status
                            dashboard_data["queues"][f"server_{tak_server.id}"] = {
                                "name": tak_server.name,  # Include actual server name
                                "size": queue_status.get("current_size", 0),
                                "throughput": round(
                                    queue_status.get("total_events_processed", 0) / 60,
                                    1,
                                ),  # rough throughput
                                "errors": queue_status.get("total_events_dropped", 0),
                                "health_score": (
                                    100.0 if queue_status.get("exists", False) else 0.0
                                ),
                                "total_processed": queue_status.get(
                                    "total_events_processed", 0
                                ),
                                "total_batches": queue_status.get(
                                    "total_batches_sent", 0
                                ),
                                "utilization": round(
                                    (
                                        queue_status.get("current_size", 0)
                                        / max(queue_status.get("max_size", 1), 1)
                                    )
                                    * 100,
                                    1,
                                ),
                            }
                            logger.debug(
                                f"Created fallback queue metrics for server {tak_server.id}"
                            )
                        else:
                            logger.warning(
                                f"No fallback queue data found for server {tak_server.id}"
                            )
                    except Exception as fallback_error:
                        logger.error(f"Fallback queue data failed: {fallback_error}")
        except Exception as e:
            logger.error(f"Queue monitoring not available: {e}", exc_info=True)

        # Get stream status data
        try:
            services = get_stream_services()
            status_service = services["status_service"]
            logger.debug(f"Stream status service obtained: {status_service}")
            streams_data = status_service.get_all_streams_status()
            logger.debug(f"Stream status data: {streams_data}")

            # Extract the streams array from the response
            if isinstance(streams_data, dict) and "streams" in streams_data:
                streams_list = streams_data["streams"]
                logger.debug(f"Found {len(streams_list)} streams in status data")

                for stream_data in streams_list:
                    stream_id = str(stream_data.get("id"))
                    logger.debug(
                        f"Processing stream {stream_id} with data: {stream_data}"
                    )
                    dashboard_data["streams"][stream_id] = {
                        "status": stream_data.get(
                            "status",
                            "running" if stream_data.get("running") else "stopped",
                        ),
                        "devices": stream_data.get(
                            "device_count", 1 if stream_data.get("running") else 0
                        ),
                        "last_update": stream_data.get("last_poll", "never"),
                        "error": stream_data.get("last_error"),
                        "stream_name": stream_data.get("name"),
                        "plugin_type": stream_data.get("plugin_type"),
                        "total_messages": stream_data.get("total_messages_sent", 0),
                    }
            else:
                logger.warning(
                    f"Unexpected stream status data format: {type(streams_data)}"
                )
        except Exception as e:
            logger.error(f"Stream status not available: {e}", exc_info=True)

        # Get performance data
        try:
            from services.queue_performance_optimizer import get_performance_optimizer

            optimizer = get_performance_optimizer()
            performance_report = optimizer.get_optimization_report()

            if "latest_metrics" in performance_report:
                metrics = performance_report["latest_metrics"]
                dashboard_data["performance"] = {
                    "avg_response_time": metrics.get("average_response_time", 0),
                    "cache_hit_ratio": metrics.get("cache_hit_ratio", 0),
                    "memory_usage": metrics.get("memory_usage_mb", 0),
                    "cpu_usage": metrics.get("cpu_usage_percent", 0),
                }
        except Exception as e:
            logger.debug(f"Performance metrics not available: {e}")

        # Get circuit breaker data
        try:
            from services.circuit_breaker import get_circuit_breaker_manager

            manager = get_circuit_breaker_manager()
            all_status = manager.get_all_status()

            for service_name, status in all_status.items():
                dashboard_data["circuit_breakers"][service_name] = {
                    "state": status.get("state"),
                    "failure_count": status.get("failure_count", 0),
                    "last_failure": status.get("last_failure_time"),
                }
        except Exception as e:
            logger.debug(f"Circuit breaker data not available: {e}")

        # Get recovery service data
        try:
            from services.recovery_service import get_recovery_service

            recovery_service = get_recovery_service()
            service_status = recovery_service.get_service_status()

            dashboard_data["recovery"] = {
                "active_recoveries": service_status.get("active_recoveries", 0),
                "success_rate": (
                    service_status["statistics"]["successful_recoveries"]
                    / max(service_status["statistics"]["total_attempts"], 1)
                ),
                "running": service_status.get("running", False),
            }
        except Exception as e:
            logger.debug(f"Recovery service data not available: {e}")

        return jsonify(dashboard_data)

    except Exception as e:
        logger.error(f"Error generating monitoring dashboard: {e}")
        return (
            jsonify(
                {
                    "error": "Failed to generate dashboard data",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


# =============================================================================
# Stream API Routes
# =============================================================================


@bp.route("/streams/stats")
@api_key_or_auth_required
def api_stats():
    """Get statistics for all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services["status_service"]

    try:
        stats = status_service.get_stream_statistics()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({"error": "Failed to get statistics"}), 500


@bp.route("/streams/status")
@api_key_or_auth_required
def streams_status():
    """Get detailed status of all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services["status_service"]

    try:
        status_data = status_service.get_all_streams_status()
        return jsonify({"streams": status_data})

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({"error": "Failed to get status"}), 500


@bp.route("/streams/plugins/<plugin_name>/config")
@require_permission("api", "read")
def get_plugin_config(plugin_name):
    """Get plugin configuration metadata"""
    try:
        metadata = get_config_service().get_plugin_metadata(plugin_name)
        if metadata:
            metadata = get_config_service().serialize_plugin_metadata(metadata)
            return jsonify(metadata)
        return jsonify({"error": "Plugin not found"}), 404

    except Exception as e:
        logger.error(f"Error getting plugin config for {plugin_name}: {e}")
        return jsonify({"error": "Failed to get plugin configuration"}), 500


@bp.route("/plugins/metadata")
@require_permission("api", "read")
def get_all_plugin_metadata():
    """Get metadata for all available plugins"""
    try:
        metadata = get_config_service().get_all_plugin_metadata()
        # Serialize all plugin metadata for safe JSON transmission
        serialized_metadata = {
            k: get_config_service().serialize_plugin_metadata(v)
            for k, v in metadata.items()
        }
        return jsonify(serialized_metadata)

    except Exception as e:
        logger.error(f"Error getting all plugin metadata: {e}")
        return jsonify({"error": "Failed to get plugin metadata"}), 500


@bp.route("/plugins/categories")
@require_permission("api", "read")
def get_plugin_categories():
    """Get all available plugin categories"""
    try:
        category_service = get_category_service(get_plugin_manager())
        categories = category_service.get_available_categories()

        # Convert CategoryInfo objects to dictionaries
        categories_data = {
            key: {
                "key": cat.key,
                "display_name": cat.display_name,
                "description": cat.description,
                "icon": cat.icon,
                "plugin_count": cat.plugin_count,
            }
            for key, cat in categories.items()
        }

        return jsonify(categories_data)

    except Exception as e:
        logger.error(f"Error getting plugin categories: {e}")
        return jsonify({"error": "Failed to get plugin categories"}), 500


@bp.route("/plugins/by-category/<category>")
@require_permission("api", "read")
def get_plugins_by_category(category):
    """Get all plugins in a specific category"""
    try:
        category_service = get_category_service(get_plugin_manager())
        plugins = category_service.get_plugins_by_category(category)

        # Convert PluginInfo objects to dictionaries
        plugins_data = [
            {
                "key": plugin.key,
                "display_name": plugin.display_name,
                "description": plugin.description,
                "icon": plugin.icon,
                "category": plugin.category,
            }
            for plugin in plugins
        ]

        return jsonify({"category": category, "plugins": plugins_data})

    except Exception as e:
        logger.error(f"Error getting plugins for category '{category}': {e}")
        return (
            jsonify({"error": f"Failed to get plugins for category '{category}'"}),
            500,
        )


@bp.route("/plugins/categorized")
@require_permission("api", "read")
def get_categorized_plugins():
    """Get all plugins grouped by category"""
    try:
        category_service = get_category_service(get_plugin_manager())
        categorized = category_service.get_categorized_plugins()

        # Convert to serializable format
        categorized_data = {}
        for category, plugins in categorized.items():
            categorized_data[category] = [
                {
                    "key": plugin.key,
                    "display_name": plugin.display_name,
                    "description": plugin.description,
                    "icon": plugin.icon,
                    "category": plugin.category,
                }
                for plugin in plugins
            ]

        return jsonify(categorized_data)

    except Exception as e:
        logger.error(f"Error getting categorized plugins: {e}")
        return jsonify({"error": "Failed to get categorized plugins"}), 500


@bp.route("/plugins/category-statistics")
@require_permission("api", "read")
def get_category_statistics():
    """Get statistics about plugin categories"""
    try:
        category_service = get_category_service(get_plugin_manager())
        stats = category_service.get_category_statistics()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting category statistics: {e}")
        return jsonify({"error": "Failed to get category statistics"}), 500


@bp.route("/streams/<int:stream_id>/export-config")
@require_permission("streams", "read")
def export_stream_config(stream_id):
    """Export stream configuration (sensitive fields masked)"""
    try:
        export_data = get_config_service().export_stream_config(
            stream_id, include_sensitive=False
        )
        return jsonify(export_data)

    except Exception as e:
        logger.error(f"Error exporting stream config {stream_id}: {e}")
        return jsonify({"error": "Failed to export configuration"}), 500


@bp.route("/streams/<int:stream_id>/config")
@require_permission("streams", "read")
def get_stream_config(stream_id):
    """Get stream configuration (sensitive fields masked) for editing"""
    try:
        from models.stream import Stream

        stream = Stream.query.get_or_404(stream_id)
        # Get plugin config with sensitive fields masked for security
        config = stream.to_dict(include_sensitive=False)
        return jsonify(config.get("plugin_config", {}))

    except Exception as e:
        logger.error(f"Error getting stream config {stream_id}: {e}")
        return jsonify({"error": "Failed to get stream configuration"}), 500


@bp.route("/streams/<int:stream_id>/refresh-workers", methods=["POST"])
@require_permission("streams", "write")
def refresh_stream_tak_workers(stream_id):
    """Refresh TAK workers for a specific stream after configuration changes"""
    try:
        from services.stream_manager import get_stream_manager

        stream_manager = get_stream_manager()
        success = stream_manager.refresh_stream_tak_workers(stream_id)

        if success:
            return jsonify(
                {
                    "success": True,
                    "message": f"TAK workers refreshed successfully for stream {stream_id}",
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Failed to refresh TAK workers"}),
                500,
            )

    except Exception as e:
        logger.error(f"Error refreshing TAK workers for stream {stream_id}: {e}")
        return (
            jsonify({"success": False, "error": "Failed to refresh TAK workers"}),
            500,
        )


@bp.route("/streams/security-status")
@require_permission("admin", "read")
def security_status():
    """Get security status of all streams"""
    try:
        status = get_config_service().get_security_status()
        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting security status: {e}")
        return jsonify({"error": "Failed to get security status"}), 500


@bp.route("/bootstrap/status")
@require_permission("admin", "read")
def bootstrap_status():
    """Get bootstrap service status and diagnostic information"""
    try:
        from services.auth.bootstrap_service import get_bootstrap_service

        bootstrap_service = get_bootstrap_service()
        bootstrap_info = bootstrap_service.get_bootstrap_info()

        return jsonify(
            {
                "status": "success",
                "bootstrap": bootstrap_info,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Error getting bootstrap status: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


# Callsign mapping API endpoints
@bp.route("/streams/discover-trackers", methods=["POST"])
@require_permission("streams", "read")
def discover_trackers():
    """Discover trackers for callsign mapping configuration"""
    try:
        from models.stream import Stream
        from plugins.plugin_manager import get_plugin_manager
        from services.connection_test_service import ConnectionTestService

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        from utils.config_helpers import ConfigHelper

        helper = ConfigHelper(data)
        plugin_type = helper.get("plugin_type")
        plugin_config = helper.get("plugin_config", {})
        stream_id = helper.get("stream_id")  # Optional for edit mode

        if not plugin_type:
            return jsonify({"error": "Plugin type is required"}), 400

        plugin_manager = get_plugin_manager()

        # Check if plugin class exists
        if plugin_type not in plugin_manager.plugins:
            return jsonify({"error": f"Plugin {plugin_type} not found"}), 404

        # Create temporary plugin instance with empty config for metadata only
        plugin_class = plugin_manager.plugins[plugin_type]
        plugin = plugin_class({})

        # For edit mode, merge with existing config
        if stream_id:
            stream = Stream.query.get(stream_id)
            if stream:
                existing_config = stream.get_plugin_config()
                # In edit mode, prioritize existing config over potentially empty form values
                # Only override with new values if they are non-empty
                merged_config = existing_config.copy()
                for key, value in plugin_config.items():
                    if value:  # Only use non-empty values from form
                        merged_config[key] = value
                plugin_config = merged_config

        # Use ConnectionTestService to discover actual tracker data for callsign mapping
        from flask import current_app

        stream_manager = getattr(current_app, "stream_manager", None)
        connection_service = ConnectionTestService(plugin_manager, stream_manager)
        result = connection_service.discover_plugin_trackers_sync(
            plugin_type, plugin_config
        )

        if not result["success"]:
            return (
                jsonify({"error": result.get("error", "Failed to discover trackers")}),
                400,
            )

        # Extract tracker data from the successful discovery
        tracker_data = result.get("tracker_data", [])

        # Get existing callsign mappings to preserve enabled state for existing trackers
        existing_mappings = {}
        if stream_id:
            from models.callsign_mapping import CallsignMapping

            mappings = CallsignMapping.query.filter_by(stream_id=stream_id).all()
            for mapping in mappings:
                existing_mappings[mapping.identifier_value] = {
                    "enabled": mapping.enabled,
                    "custom_callsign": mapping.custom_callsign,
                    "cot_type": mapping.cot_type,
                }

        # Add enabled field to each tracker, defaulting to True for new trackers
        # and preserving existing state for known trackers
        for tracker in tracker_data:
            identifier_value = tracker.get("identifier", "")
            if identifier_value in existing_mappings:
                tracker["enabled"] = existing_mappings[identifier_value]["enabled"]
            else:
                tracker["enabled"] = True  # Default enabled for new trackers

        # Get available fields from plugin if it supports callsign mapping
        available_fields = []
        if hasattr(plugin, "get_available_fields"):
            try:
                fields = plugin.get_available_fields()
                available_fields = [
                    {
                        "name": field.name,
                        "display_name": field.display_name,
                        "type": field.type,
                        "recommended": field.recommended,
                        "description": field.description,
                    }
                    for field in fields
                ]
            except Exception as e:
                logger.warning(
                    f"Error getting available fields from {plugin_type}: {e}"
                )

        # Add team member options for UI dropdowns
        return jsonify(
            {
                "success": True,
                "tracker_count": len(tracker_data),
                "trackers": tracker_data,
                "available_fields": available_fields,
                "cot_type_options": COT_TYPE_OPTIONS,
                "team_role_options": TEAM_MEMBER_ROLES,
                "team_color_options": TEAM_MEMBER_COLORS,
            }
        )

    except Exception as e:
        logger.error(f"Error discovering trackers: {e}")
        return jsonify({"error": "Failed to discover trackers"}), 500


@bp.route("/streams/<int:stream_id>/callsign-mappings", methods=["GET"])
@require_permission("streams", "read")
def get_callsign_mappings(stream_id):
    """Get callsign mappings for a stream"""
    try:
        from models.callsign_mapping import CallsignMapping
        from models.stream import Stream

        stream = Stream.query.get_or_404(stream_id)
        mappings = CallsignMapping.query.filter_by(stream_id=stream_id).all()

        return jsonify(
            {
                "success": True,
                "stream_id": stream_id,
                "enable_callsign_mapping": stream.enable_callsign_mapping,
                "callsign_identifier_field": stream.callsign_identifier_field,
                "callsign_error_handling": stream.callsign_error_handling,
                "enable_per_callsign_cot_types": stream.enable_per_callsign_cot_types,
                "mappings": [mapping.to_dict() for mapping in mappings],
            }
        )

    except Exception as e:
        logger.error(f"Error getting callsign mappings for stream {stream_id}: {e}")
        return jsonify({"error": "Failed to get callsign mappings"}), 500


@bp.route("/streams/<int:stream_id>/callsign-mappings", methods=["POST", "PUT"])
@require_permission("streams", "write")
def update_callsign_mappings(stream_id):
    """Create or update callsign mappings for a stream"""
    try:
        from models.callsign_mapping import CallsignMapping
        from models.stream import Stream

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        stream = Stream.query.get_or_404(stream_id)

        # Update stream callsign configuration
        from utils.config_helpers import ConfigHelper

        helper = ConfigHelper(data)
        stream.enable_callsign_mapping = helper.get_bool(
            "enable_callsign_mapping", False
        )
        stream.callsign_identifier_field = helper.get("callsign_identifier_field")
        stream.callsign_error_handling = helper.get(
            "callsign_error_handling", "fallback"
        )
        stream.enable_per_callsign_cot_types = helper.get_bool(
            "enable_per_callsign_cot_types", False
        )

        # Handle mappings if provided
        mappings_data = helper.get_list("mappings", [])

        if mappings_data:
            # Clear existing mappings
            CallsignMapping.query.filter_by(stream_id=stream_id).delete()

            # Create new mappings
            for mapping_data in mappings_data:
                if not mapping_data.get("identifier_value") or not mapping_data.get(
                    "custom_callsign"
                ):
                    continue

                # Extract team member fields
                cot_type_override = mapping_data.get("cot_type_override")
                team_role = mapping_data.get("team_role")
                team_color = mapping_data.get("team_color")

                # Validate team member configuration
                validation_error = validate_team_member_configuration(
                    cot_type_override, team_role, team_color
                )
                if validation_error:
                    return jsonify({"error": validation_error}), 400

                mapping = CallsignMapping(
                    stream_id=stream_id,
                    identifier_value=mapping_data["identifier_value"],
                    custom_callsign=mapping_data["custom_callsign"],
                    cot_type=mapping_data.get("cot_type"),
                    enabled=mapping_data.get("enabled", True),
                    cot_type_override=cot_type_override,
                    team_role=team_role,
                    team_color=team_color,
                )

                # Validate using model method
                try:
                    mapping.validate_team_member_fields()
                except ValueError as e:
                    return jsonify({"error": str(e)}), 400

                db.session.add(mapping)

        db.session.commit()

        return jsonify(
            {"success": True, "message": "Callsign mappings updated successfully"}
        )

    except Exception as e:
        logger.error(f"Error updating callsign mappings for stream {stream_id}: {e}")
        db.session.rollback()
        return jsonify({"error": "Failed to update callsign mappings"}), 500


@bp.route("/plugins/<plugin_type>/available-fields", methods=["GET"])
@require_permission("streams", "read")
def get_plugin_available_fields(plugin_type):
    """Get available identifier fields for a plugin"""
    try:
        from plugins.plugin_manager import get_plugin_manager

        plugin_manager = get_plugin_manager()

        # Check if plugin class exists
        if plugin_type not in plugin_manager.plugins:
            return jsonify({"error": f"Plugin {plugin_type} not found"}), 404

        # Create temporary plugin instance with empty config for metadata only
        plugin_class = plugin_manager.plugins[plugin_type]
        plugin = plugin_class({})

        available_fields = []
        if hasattr(plugin, "get_available_fields"):
            try:
                fields = plugin.get_available_fields()
                available_fields = [
                    {
                        "name": field.name,
                        "display_name": field.display_name,
                        "type": field.type,
                        "recommended": field.recommended,
                        "description": field.description,
                    }
                    for field in fields
                ]
            except Exception as e:
                logger.warning(
                    f"Error getting available fields from {plugin_type}: {e}"
                )

        return jsonify(
            {
                "success": True,
                "plugin_type": plugin_type,
                "available_fields": available_fields,
                "supports_callsign_mapping": len(available_fields) > 0,
            }
        )

    except Exception as e:
        logger.error(f"Error getting available fields for {plugin_type}: {e}")
        return jsonify({"error": "Failed to get available fields"}), 500


# =============================================================================
# Team Member API Routes
# =============================================================================


@bp.route("/team-member/role-options", methods=["GET"])
@require_permission("api", "read")
def get_team_member_role_options():
    """Get available team member role options"""
    try:
        return jsonify({"roles": TEAM_MEMBER_ROLES})

    except Exception as e:
        logger.error(f"Error getting team member role options: {e}")
        return jsonify({"error": "Failed to get team member role options"}), 500


@bp.route("/team-member/color-options", methods=["GET"])
@require_permission("api", "read")
def get_team_member_color_options():
    """Get available team member color options"""
    try:
        return jsonify({"colors": TEAM_MEMBER_COLORS})

    except Exception as e:
        logger.error(f"Error getting team member color options: {e}")
        return jsonify({"error": "Failed to get team member color options"}), 500


@bp.route("/version")
def version():
    return {"version": format_version()}


# =============================================================================
# Monitoring Dashboard API
# =============================================================================


@bp.route("/monitoring/dashboard-legacy")
@require_permission("api", "read")
def monitoring_dashboard_legacy():
    """
    Web dashboard endpoint for real-time metrics as specified in Phase 2 of RC6.
    Returns queue metrics, stream health, performance data, and configuration status.
    """
    try:
        from services.stream_manager import get_stream_manager
        from services.queue_manager import get_queue_manager

        # Get stream manager and monitoring services
        stream_manager = get_stream_manager()
        queue_manager = get_queue_manager()

        # Get queue metrics from monitoring service
        queues = {}
        try:
            if (
                hasattr(stream_manager, "monitoring_service")
                and stream_manager.monitoring_service
            ):
                # Get queue status from queue manager
                queue_statuses = queue_manager.get_all_queue_status()

                for queue_id, status in queue_statuses.items():
                    # Get metrics from monitoring service
                    metrics = stream_manager.monitoring_service.get_queue_metrics(
                        queue_id
                    )

                    if metrics:
                        queues[f"server_{queue_id}"] = {
                            "size": metrics.current_size,
                            "throughput": round(metrics.events_per_second, 1),
                            "errors": status.get("total_events_dropped", 0),
                            "utilization": round(metrics.utilization_percent, 1),
                            "health_score": round(metrics.health_score, 1),
                        }
                    else:
                        # Fallback to basic queue status
                        queues[f"server_{queue_id}"] = {
                            "size": status.get("current_size", 0),
                            "throughput": 0.0,
                            "errors": status.get("total_events_dropped", 0),
                            "utilization": 0.0,
                            "health_score": 100.0,
                        }
        except Exception as e:
            logger.debug(f"Error getting queue metrics: {e}")
            queues = {
                "server_1": {
                    "size": 0,
                    "throughput": 0.0,
                    "errors": 0,
                    "utilization": 0.0,
                    "health_score": 100.0,
                }
            }

        # Get stream health information
        streams = {}
        try:
            all_status = stream_manager.get_all_stream_status()
            for stream_id, status in all_status.items():
                if isinstance(stream_id, int):  # Skip non-stream entries like errors
                    streams[str(stream_id)] = {
                        "status": (
                            "running" if status.get("running", False) else "stopped"
                        ),
                        "devices": (
                            1 if status.get("running", False) else 0
                        ),  # Simplified device count
                        "last_update": status.get("last_poll"),
                        "error": (
                            status.get("last_error")
                            if status.get("last_error")
                            else None
                        ),
                        "stream_name": status.get("stream_name", f"Stream {stream_id}"),
                        "plugin_type": status.get("plugin_type", "unknown"),
                        "tak_server": status.get("tak_server", "unknown"),
                    }
        except Exception as e:
            logger.debug(f"Error getting stream health: {e}")
            streams = {}

        # Get performance data
        performance = {
            "avg_response_time": 0.25,  # Default values
            "cache_hit_ratio": 0.85,
            "memory_usage": 0,
        }

        try:
            # Get performance data from optimizer if available
            if (
                hasattr(stream_manager, "performance_optimizer")
                and stream_manager.performance_optimizer
            ):
                report = stream_manager.performance_optimizer.get_optimization_report()
                if "latest_metrics" in report:
                    metrics = report["latest_metrics"]
                    performance.update(
                        {
                            "avg_response_time": round(
                                metrics.get("processing_latency_ms", 250) / 1000, 3
                            ),
                            "cache_hit_ratio": round(
                                metrics.get("cache_hit_ratio", 0.85), 2
                            ),
                            "memory_usage": round(metrics.get("memory_usage_mb", 0), 1),
                            "cpu_usage": round(metrics.get("cpu_usage_percent", 0), 1),
                            "queue_throughput": round(
                                metrics.get("queue_throughput", 0), 1
                            ),
                            "batch_efficiency": round(
                                metrics.get("batch_efficiency", 0), 2
                            ),
                        }
                    )
        except Exception as e:
            logger.debug(f"Error getting performance metrics: {e}")

        # Get configuration status
        try:
            from models.stream import Stream

            total_streams = Stream.query.count()
            active_streams = Stream.query.filter_by(is_active=True).count()

            config_status = {
                "total_streams": total_streams,
                "active_streams": active_streams,
                "inactive_streams": total_streams - active_streams,
                "last_config_change": None,  # Could be enhanced with change tracking
            }
        except Exception as e:
            logger.debug(f"Error getting configuration status: {e}")
            config_status = {
                "total_streams": 0,
                "active_streams": 0,
                "inactive_streams": 0,
                "last_config_change": None,
            }

        dashboard_data = {
            "queues": queues,
            "streams": streams,
            "performance": performance,
            "configuration": config_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monitoring_active": getattr(
                stream_manager, "_monitoring_initialized", False
            ),
        }

        return jsonify(dashboard_data)

    except Exception as e:
        logger.error(f"Error generating monitoring dashboard: {e}")
        return (
            jsonify(
                {
                    "error": "Failed to generate monitoring dashboard",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


def check_stream_manager_health():
    """Check stream manager health"""
    try:
        stream_manager = getattr(current_app, "stream_manager", None)

        if stream_manager is None:
            return {"status": "unhealthy", "error": "Stream manager not initialized"}

        # Check if background loop is running
        loop_running = (
            hasattr(stream_manager, "_loop")
            and stream_manager._loop
            and stream_manager._loop.is_running()
        )

        # Count active workers
        worker_count = (
            len(stream_manager.workers) if hasattr(stream_manager, "workers") else 0
        )

        # Check session manager
        session_manager_healthy = (
            getattr(stream_manager, "session_manager", None) is not None
        )

        status = (
            "healthy" if (loop_running and session_manager_healthy) else "unhealthy"
        )

        return {
            "status": status,
            "event_loop_running": loop_running,
            "worker_count": worker_count,
            "session_manager_initialized": session_manager_healthy,
            "max_workers": getattr(current_app.config, "MAX_WORKER_THREADS", "unknown"),
        }

    except Exception as e:
        logger.error(f"Stream manager health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "error_type": type(e).__name__}


def check_system_health():
    """Check system resource health"""
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Memory usage
        memory = psutil.virtual_memory()

        # Disk usage
        disk = psutil.disk_usage("/")

        # Process info
        process = psutil.Process()
        process_memory = process.memory_info()

        # Determine status based on thresholds
        status = "healthy"
        warnings = []

        if cpu_percent > 90:
            status = "unhealthy"
            warnings.append(f"High CPU usage: {cpu_percent}%")
        elif cpu_percent > 75:
            if status == "healthy":
                status = "degraded"
            warnings.append(f"Elevated CPU usage: {cpu_percent}%")

        if memory.percent > 90:
            status = "unhealthy"
            warnings.append(f"High memory usage: {memory.percent}%")
        elif memory.percent > 75:
            if status == "healthy":
                status = "degraded"
            warnings.append(f"Elevated memory usage: {memory.percent}%")

        if disk.percent > 90:
            status = "unhealthy"
            warnings.append(f"High disk usage: {disk.percent}%")
        elif disk.percent > 80:
            if status == "healthy":
                status = "degraded"
            warnings.append(f"Elevated disk usage: {disk.percent}%")

        result = {
            "status": status,
            "cpu_percent": cpu_percent,
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
            },
            "process": {
                "memory_mb": round(process_memory.rss / (1024**2), 2),
                "pid": process.pid,
            },
        }

        if warnings:
            result["warnings"] = warnings

        return result

    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "error_type": type(e).__name__}


def check_streams_health():
    """Check streams health and status"""
    try:
        from models.stream import Stream

        streams = Stream.query.all()
        total_streams = len(streams)
        active_streams = sum(1 for s in streams if s.is_active)

        # Check for streams with recent errors
        recent_errors = 0
        error_threshold = datetime.now(timezone.utc) - timedelta(minutes=15)

        for stream in streams:
            if (
                stream.last_error
                and stream.updated_at
                and stream.updated_at > error_threshold
            ):
                recent_errors += 1

        # Determine status
        status = "healthy"
        warnings = []

        if recent_errors > 0:
            if recent_errors >= total_streams * 0.5:  # More than 50% have errors
                status = "unhealthy"
            else:
                status = "degraded"
            warnings.append(f"{recent_errors} streams with recent errors")

        return {
            "status": status,
            "total_streams": total_streams,
            "active_streams": active_streams,
            "inactive_streams": total_streams - active_streams,
            "recent_errors": recent_errors,
            "warnings": warnings if warnings else None,
        }

    except Exception as e:
        logger.error(f"Streams health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "error_type": type(e).__name__}


def check_tak_servers_health():
    """Check TAK servers health"""
    try:
        from models.tak_server import TakServer

        tak_servers = TakServer.query.all()

        return {
            "status": "healthy",
            "total_tak_servers": len(tak_servers),
            "servers": [
                {"name": server.name, "host": server.host, "port": server.port}
                for server in tak_servers
            ],
        }

    except Exception as e:
        logger.error(f"TAK servers health check failed: {e}")
        return {"status": "unhealthy", "error": str(e), "error_type": type(e).__name__}


def get_uptime_seconds():
    """Get application uptime in seconds"""
    try:
        process = psutil.Process()
        return int(time.time() - process.create_time())
    except psutil.NoSuchProcess:
        # Process no longer exists
        logger.warning("Process no longer exists when calculating uptime")
        return 0
    except psutil.AccessDenied:
        # Insufficient permissions to access process info
        logger.warning("Access denied when trying to get process creation time")
        return 0
    except (OSError, ValueError) as e:
        # Handle system-level errors or value conversion issues
        logger.error(f"Error calculating uptime: {e}")
        return 0


# Clear health check cache periodically
def clear_expired_cache():
    """Clear expired cache entries"""
    with _cache_lock:
        now = time.time()
        expired_keys = [
            key
            for key, value in _health_cache.items()
            if now - value["timestamp"]
            > CACHE_DURATION * 2  # Clear after 2x cache duration
        ]
        for key in expired_keys:
            del _health_cache[key]


# Run cache cleanup every 5 minutes
def start_cache_cleanup():
    """Start background cache cleanup thread"""

    def cleanup_loop():
        while True:
            time.sleep(300)  # 5 minutes
            try:
                clear_expired_cache()
            except Exception as e:
                logger.error(f"Cache cleanup failed: {e}")
                # Continue running despite errors

    cleanup_thread = threading.Thread(
        target=cleanup_loop, daemon=True, name="CacheCleanup"
    )
    cleanup_thread.start()


# Start cache cleanup when module is imported
start_cache_cleanup()
