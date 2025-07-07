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

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

# Third-party imports
import asyncio
import psutil
from flask import Blueprint, jsonify, current_app

# Local application imports
from database import db
from services.health_service import health_service
from services.stream_display_service import StreamDisplayService
from services.stream_config_service import StreamConfigService
from services.stream_operations_service import StreamOperationsService
from services.connection_test_service import ConnectionTestService
from services.stream_status_service import StreamStatusService

# Module-level logger
logger = logging.getLogger(__name__)

bp = Blueprint('api', __name__)

# Cache for health check results to avoid excessive checks
_health_cache = {}
_cache_lock = threading.Lock()
CACHE_DURATION = 30  # seconds

def get_display_service():
    """Get the display service with current app context"""
    return StreamDisplayService(current_app.plugin_manager)


def get_config_service():
    """Get the config service with current app context"""
    return StreamConfigService(current_app.plugin_manager)


def get_stream_services():
    app_context_factory = getattr(current_app, "app_context_factory", None)
    if app_context_factory is None:
        # Fallback to the default Flask app context method
        app_context_factory = current_app.app_context
    stream_manager = getattr(current_app, "stream_manager", None)
    if stream_manager is None:
        raise ValueError("Stream manager not found in current_app")
    return {
        'operations_service': StreamOperationsService(stream_manager, db),
        'test_service': ConnectionTestService(current_app.plugin_manager, stream_manager),
        'status_service': StreamStatusService(stream_manager),
    }


def get_cached_health_check(check_name, check_function, *args, **kwargs):
    """Get cached health check result or run fresh check if cache expired"""
    with _cache_lock:
        now = time.time()
        cache_key = check_name

        # Check if we have a valid cached result
        if (cache_key in _health_cache and
                now - _health_cache[cache_key]['timestamp'] < CACHE_DURATION):
            return _health_cache[cache_key]['result']

        # Run fresh check
        try:
            result = check_function(*args, **kwargs)
            _health_cache[cache_key] = {
                'result': result,
                'timestamp': now
            }
            return result
        except Exception as e:
            error_result = {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            _health_cache[cache_key] = {
                'result': error_result,
                'timestamp': now
            }
            return error_result

# =============================================================================
# System Health API Routes
# =============================================================================

@bp.route('/status')
def api_status():
    """API endpoint for system status"""
    # Import models inside the route to avoid circular imports
    from models.stream import Stream
    from models.tak_server import TakServer

    streams = Stream.query.all()

    # Handle stream_manager import carefully
    try:
        from services.stream_manager import stream_manager
        running_workers = len(stream_manager.workers)
    except ImportError:
        running_workers = 0

    return jsonify({
        'total_streams': len(streams),
        'active_streams': sum(1 for s in streams if s.is_active),
        'tak_servers': TakServer.query.count(),
        'running_workers': running_workers
    })


@bp.route('/health')
def health_check():
    """Basic health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'version': '1.0.0',
        'service': 'trakbridge'
    })


@bp.route('/health/detailed')
def detailed_health_check():
    """Detailed health check with all components"""
    start_time = time.time()

    checks = {
        'database': get_cached_health_check('database', health_service.run_all_database_checks),
        'encryption': get_cached_health_check('encryption', check_encryption_health),
        'stream_manager': get_cached_health_check('stream_manager', check_stream_manager_health),
        'system': get_cached_health_check('system', check_system_health),
        'streams': get_cached_health_check('streams', check_streams_health),
        'tak_servers': get_cached_health_check('tak_servers', check_tak_servers_health)
    }

    # Determine overall status
    overall_status = 'healthy'
    critical_failures = []

    for check_name, check_result in checks.items():
        if check_result.get('status') == 'unhealthy':
            if check_name in ['database', 'encryption']:  # Critical components
                overall_status = 'unhealthy'
                critical_failures.append(check_name)
            elif overall_status != 'unhealthy':
                overall_status = 'degraded'

    response_time = round((time.time() - start_time) * 1000, 2)  # ms

    result = {
        'status': overall_status,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'response_time_ms': response_time,
        'version': '1.0.0',
        'service': 'trakbridge',
        'checks': checks
    }

    if critical_failures:
        result['critical_failures'] = critical_failures

    # Return appropriate HTTP status code
    status_code = 200
    if overall_status == 'unhealthy':
        status_code = 503  # Service Unavailable
    elif overall_status == 'degraded':
        status_code = 200  # OK but with warnings

    return jsonify(result), status_code


@bp.route('/health/ready')
def readiness_check():
    """Kubernetes readiness probe - checks if app is ready to serve traffic"""
    checks = ['database', 'encryption']

    for check_name in checks:
        if check_name == 'database':
            result = get_cached_health_check('database', health_service.check_database_connectivity)
        elif check_name == 'encryption':
            result = get_cached_health_check('encryption', check_encryption_health)

        if result.get('status') != 'healthy':
            return jsonify({
                'status': 'not_ready',
                'failed_check': check_name,
                'error': result.get('error', 'Unknown error'),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 503

    return jsonify({
        'status': 'ready',
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@bp.route('/health/live')
def liveness_check():
    """Kubernetes liveness probe - basic check if app is alive"""
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'uptime_seconds': get_uptime_seconds()
    })


@bp.route('/health/database')
def database_health():
    """Database-specific health check"""
    result = get_cached_health_check('database', health_service.run_all_database_checks)
    
    # Return appropriate HTTP status code
    status_code = 503 if result.get('status') == 'unhealthy' else 200
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
        return {
            'status': 'unhealthy',
            'error': str(e),
            'error_type': type(e).__name__
        }


@bp.route('/health/plugins', methods=['GET'])
def plugin_health():
    plugin_manager = getattr(current_app, "plugin_manager", None)
    stream_manager = getattr(current_app, "stream_manager", None)
    if not plugin_manager:
        return jsonify({"error": "Plugin manager not available"}), 500
    if not stream_manager:
        return jsonify({"error": "Stream manager not available"}), 500

    # Use the background event loop from stream_manager
    future = asyncio.run_coroutine_threadsafe(
        plugin_manager.check_all_plugins_health(),
        stream_manager.loop
    )
    health_status = future.result()
    return jsonify(health_status)

# =============================================================================
# Stream API Routes
# =============================================================================


@bp.route('/streams/stats')
def api_stats():
    """Get statistics for all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services['status_service']

    try:
        stats = status_service.get_stream_statistics()
        return jsonify(stats)

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': 'Failed to get statistics'}), 500


@bp.route('/streams/status')
def streams_status():
    """Get detailed status of all streams"""

    # Get the correct status_service at runtime
    services = get_stream_services()
    status_service = services['status_service']

    try:
        status_data = status_service.get_all_streams_status()
        return jsonify({'streams': status_data})

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({'error': 'Failed to get status'}), 500


@bp.route('/streams/plugins/<plugin_name>/config')
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


@bp.route('/streams/<int:stream_id>/export-config')
def export_stream_config(stream_id):
    """Export stream configuration (sensitive fields masked)"""
    try:
        export_data = get_config_service().export_stream_config(stream_id, include_sensitive=False)
        return jsonify(export_data)

    except Exception as e:
        logger.error(f"Error exporting stream config {stream_id}: {e}")
        return jsonify({'error': 'Failed to export configuration'}), 500


@bp.route('/streams/security-status')
def security_status():
    """Get security status of all streams"""
    try:
        status = get_config_service().get_security_status()
        return jsonify(status)

    except Exception as e:
        logger.error(f"Error getting security status: {e}")
        return jsonify({'error': 'Failed to get security status'}), 500


def check_stream_manager_health():
    """Check stream manager health"""
    try:
        stream_manager = current_app.stream_manager
        
        if stream_manager is None:
            return {
                'status': 'unhealthy',
                'error': 'Stream manager not initialized'
            }

        # Check if background loop is running
        loop_running = (hasattr(stream_manager, '_loop') and
                       stream_manager._loop and
                       stream_manager._loop.is_running())

        # Count active workers
        worker_count = len(stream_manager.workers) if hasattr(stream_manager, 'workers') else 0

        # Check session manager
        session_manager_healthy = getattr(stream_manager, 'session_manager', None) is not None

        status = 'healthy' if (loop_running and session_manager_healthy) else 'unhealthy'

        return {
            'status': status,
            'event_loop_running': loop_running,
            'worker_count': worker_count,
            'session_manager_initialized': session_manager_healthy,
            'max_workers': getattr(current_app.config, 'MAX_WORKER_THREADS', 'unknown')
        }

    except Exception as e:
        logger.error(f"Stream manager health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'error_type': type(e).__name__
        }


def check_system_health():
    """Check system resource health"""
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Memory usage
        memory = psutil.virtual_memory()

        # Disk usage
        disk = psutil.disk_usage('/')

        # Process info
        process = psutil.Process()
        process_memory = process.memory_info()

        # Determine status based on thresholds
        status = 'healthy'
        warnings = []

        if cpu_percent > 90:
            status = 'unhealthy'
            warnings.append(f'High CPU usage: {cpu_percent}%')
        elif cpu_percent > 75:
            if status == 'healthy':
                status = 'degraded'
            warnings.append(f'Elevated CPU usage: {cpu_percent}%')

        if memory.percent > 90:
            status = 'unhealthy'
            warnings.append(f'High memory usage: {memory.percent}%')
        elif memory.percent > 75:
            if status == 'healthy':
                status = 'degraded'
            warnings.append(f'Elevated memory usage: {memory.percent}%')

        if disk.percent > 90:
            status = 'unhealthy'
            warnings.append(f'High disk usage: {disk.percent}%')
        elif disk.percent > 80:
            if status == 'healthy':
                status = 'degraded'
            warnings.append(f'Elevated disk usage: {disk.percent}%')

        result = {
            'status': status,
            'cpu_percent': cpu_percent,
            'memory': {
                'total_gb': round(memory.total / (1024 ** 3), 2),
                'available_gb': round(memory.available / (1024 ** 3), 2),
                'percent': memory.percent
            },
            'disk': {
                'total_gb': round(disk.total / (1024 ** 3), 2),
                'free_gb': round(disk.free / (1024 ** 3), 2),
                'percent': disk.percent
            },
            'process': {
                'memory_mb': round(process_memory.rss / (1024 ** 2), 2),
                'pid': process.pid
            }
        }

        if warnings:
            result['warnings'] = warnings

        return result

    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'error_type': type(e).__name__
        }


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
            if (stream.last_error and
                    stream.updated_at and
                    stream.updated_at > error_threshold):
                recent_errors += 1

        # Determine status
        status = 'healthy'
        warnings = []

        if recent_errors > 0:
            if recent_errors >= total_streams * 0.5:  # More than 50% have errors
                status = 'unhealthy'
            else:
                status = 'degraded'
            warnings.append(f'{recent_errors} streams with recent errors')

        return {
            'status': status,
            'total_streams': total_streams,
            'active_streams': active_streams,
            'inactive_streams': total_streams - active_streams,
            'recent_errors': recent_errors,
            'warnings': warnings if warnings else None
        }

    except Exception as e:
        logger.error(f"Streams health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'error_type': type(e).__name__
        }


def check_tak_servers_health():
    """Check TAK servers health"""
    try:
        from models.tak_server import TakServer

        tak_servers = TakServer.query.all()

        return {
            'status': 'healthy',
            'total_tak_servers': len(tak_servers),
            'servers': [
                {
                    'name': server.name,
                    'host': server.host,
                    'port': server.port
                }
                for server in tak_servers
            ]
        }

    except Exception as e:
        logger.error(f"TAK servers health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'error_type': type(e).__name__
        }


def get_uptime_seconds():
    """Get application uptime in seconds"""
    try:
        process = psutil.Process()
        return int(time.time() - process.create_time())
    except:
        return 0


# Clear health check cache periodically
def clear_expired_cache():
    """Clear expired cache entries"""
    with _cache_lock:
        now = time.time()
        expired_keys = [
            key for key, value in _health_cache.items()
            if now - value['timestamp'] > CACHE_DURATION * 2  # Clear after 2x cache duration
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
            except:
                pass

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True, name="HealthCacheCleanup")
    cleanup_thread.start()


# Start cache cleanup when module is imported
start_cache_cleanup()