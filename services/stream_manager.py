"""
File: services/stream_manager.py

Description:
    Central stream management service providing comprehensive lifecycle management
    for all data streams with robust database integration and persistent COT
    service coordination. This service acts as the core orchestrator for stream
    operations, managing concurrent stream workers and maintaining system health.

Key features:
    - Singleton pattern implementation with thread-safe initialization
    - Asynchronous stream lifecycle management (start/stop/restart operations)
    - Background event loop management with dedicated thread execution
    - Persistent COT service initialization and coordination for TAK servers
    - Comprehensive health monitoring with periodic checks and recovery
    - Database synchronization validation and automatic correction
    - Thread-safe public API for Flask route integration
    - Graceful shutdown handling with proper cleanup and resource management
    - Stream worker orchestration with timeout handling and error recovery
    - Real-time status tracking with detailed health metrics
    - Automatic stream restart on failure detection
    - TAK server worker deduplication and persistent connection management
    - Enhanced error handling with custom exception types
    - Concurrent stream operations with proper resource locking
    - Database status synchronization with active stream validation

Dependencies:
    - StreamWorker: Individual stream execution and management
    - DatabaseManager: Persistent storage and stream configuration
    - SessionManager: HTTP session management for plugin operations
    - COT Service: Persistent TAK server connection management
    - Custom exceptions: StreamManagerError, StreamNotFoundError, etc.

Author: Emfour Solutions
Created: 18-Jul-2025
"""

# Standard library imports
import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Local application imports
from services.cot_service import get_cot_service
from services.config_cache_service import get_config_cache_service
from services.database_manager import DatabaseManager
from services.exceptions import (
    StreamConfigurationError,
    StreamManagerError,
    StreamNotFoundError,
)
from services.logging_service import get_module_logger
from services.queue_monitoring import get_queue_monitoring_service
from services.queue_performance_optimizer import get_performance_optimizer
from services.session_manager import SessionManager
from services.stream_worker import StreamWorker

# Worker coordination import removed for single worker deployment

# Global stream manager instance - use singleton pattern to prevent multiple instances
_stream_manager_instance = None
_stream_manager_lock = threading.Lock()

# Module-level logger
logger = get_module_logger(__name__)


class StreamManager:
    """tream manager with database operations"""

    def __init__(self, app_context_factory=None):
        self.workers: Dict[int, StreamWorker] = {}
        self.running = False
        self._loop = None
        self._background_task = None
        self._lock = threading.Lock()

        # Add these:
        self._initialization_lock = threading.Lock()
        self._initialized = False
        self._shutdown_event = threading.Event()
        self._health_check_task = None
        self._loop_thread = None
        self._manager_lock = threading.Lock()

        # Worker coordination removed for single worker deployment

        # Initialize dependencies
        self.db_manager = DatabaseManager(app_context_factory)
        self.session_manager = SessionManager()
        self.config_cache = get_config_cache_service()

        # Initialize monitoring services (Phase 2)
        self.monitoring_service = get_queue_monitoring_service()
        self.performance_optimizer = get_performance_optimizer()
        self._monitoring_initialized = False

        # Initialize persistent COT service flag
        self._cot_service_initialized = False

        # Worker coordination setup removed for single worker deployment

        # Start background loop
        self._start_background_loop()

    def _has_tak_servers_configured(self, stream) -> bool:
        """
        Check if stream has TAK servers configured (single or multi-server).
        Validation supporting both legacy and multi-server configurations.
        """
        logger.debug(
            f"Checking TAK servers for stream {stream.id}: tak_server={stream.tak_server}, has_tak_servers_attr={hasattr(stream, 'tak_servers')}"
        )

        # Check legacy single-server configuration
        if hasattr(stream, "tak_server") and stream.tak_server:
            logger.debug(
                f"Stream {stream.id} has single server configured: {stream.tak_server.name}"
            )
            return True

        # Check multi-server configuration
        if hasattr(stream, "tak_servers"):
            try:
                # Use the model's get_tak_server_count method which handles both legacy and new relationships
                count = stream.get_tak_server_count()
                logger.debug(f"Stream {stream.id} tak_servers count: {count}")
                return count > 0
            except Exception as e:
                logger.warning(
                    f"Error checking tak_servers count for stream {stream.id}: {e}"
                )
                try:
                    # Fallback if dynamic relationship count fails
                    servers_list = list(stream.tak_servers)
                    logger.debug(
                        f"Stream {stream.id} tak_servers list length: {len(servers_list)}"
                    )
                    return len(servers_list) > 0
                except Exception as fallback_e:
                    logger.warning(
                        f"Error checking tak_servers all() for stream {stream.id}: {fallback_e}"
                    )

        logger.info(f"Stream {stream.id} has no TAK servers configured")
        return False

    def _get_all_tak_servers(self, stream):
        """
        Get all TAK servers for a stream (single or multi-server configuration).

        Args:
            stream: Stream object

        Returns:
            Generator of TAK server objects
        """
        # Handle legacy single-server configuration
        if hasattr(stream, "tak_server") and stream.tak_server:
            yield stream.tak_server

        # Handle multi-server configuration
        if hasattr(stream, "tak_servers"):
            try:
                for tak_server in stream.tak_servers:
                    yield tak_server
            except Exception as e:
                logger.warning(
                    f"Error accessing tak_servers for stream {stream.id}: {e}"
                )

    def _get_tak_server_display(self, stream) -> str:
        """
        Get display string for TAK server configuration.
        Shows both single-server and multi-server configurations.
        """
        try:
            # Check legacy single-server configuration first
            if hasattr(stream, "tak_server") and stream.tak_server:
                return stream.tak_server.name

            # Check multi-server configuration
            if hasattr(stream, "tak_servers"):
                try:
                    # Use the model's get_tak_server_count method
                    server_count = stream.get_tak_server_count()
                    if server_count > 0:
                        if server_count == 1:
                            # Get the single server name for cleaner display
                            servers = list(stream.tak_servers)
                            return (
                                servers[0].name
                                if servers
                                else f"Multi-server (1 server)"
                            )
                        else:
                            return f"Multi-server ({server_count} servers)"
                except Exception as e:
                    logger.debug(
                        f"Error getting tak_servers count for stream {stream.id}: {e}"
                    )
                    try:
                        # Fallback to all() method
                        servers = list(stream.tak_servers)
                        if servers:
                            if len(servers) == 1:
                                return servers[0].name
                            else:
                                return f"Multi-server ({len(servers)} servers)"
                    except Exception as fallback_e:
                        logger.debug(
                            f"Error getting tak_servers all() for stream {stream.id}: {fallback_e}"
                        )

        except Exception as e:
            logger.debug(
                f"Error getting TAK server display for stream {stream.id}: {e}"
            )

        return None

    # Worker coordination subscriber removed for single worker deployment

    # Coordination listener removed for single worker deployment

    # Configuration version tracking and coordination restart methods removed for single worker deployment

    def _is_container_shutdown(self) -> bool:
        """Check if we're in a container-managed shutdown scenario"""
        return os.getenv("CONTAINER_MANAGED", "").lower() == "true"

    async def _preload_configurations(self):
        """Preload stream configurations into cache for faster startup"""
        try:
            logger.info("Preloading stream configurations")

            # Get all streams from database
            all_streams = self.db_manager.get_all_streams_with_relationships()

            preload_count = 0
            for stream in all_streams:
                try:
                    # Create cache key for stream configuration
                    cache_key = f"stream_config:{stream.id}"

                    # Preload stream configuration
                    config_data = {
                        "plugin_type": stream.plugin_type,
                        "plugin_config": stream.plugin_config,
                        "cot_type": stream.cot_type,
                        "poll_interval": stream.poll_interval,
                        "is_active": stream.is_active,
                    }

                    await self.config_cache.preload_configuration(
                        cache_key, config_data
                    )
                    preload_count += 1

                    logger.debug(
                        f"Preloaded config for stream {stream.id} ({stream.name})"
                    )

                except Exception as e:
                    logger.warning(
                        f"Failed to preload config for stream {stream.id}: {e}"
                    )

            logger.info(
                f"Configuration preloading completed: {preload_count} configurations cached"
            )

        except Exception as e:
            logger.error(f"Error during configuration preloading: {e}")

    async def hot_reload_stream_configuration(self, stream_id: int) -> bool:
        """
        Hot-reload configuration for a specific stream without full restart.

        This implements the configuration hot-reload capability from Phase 3,
        allowing configuration changes to be applied without stopping/restarting
        the entire stream where possible.

        Args:
            stream_id: ID of the stream to reload configuration for

        Returns:
            True if configuration was successfully reloaded, False otherwise
        """
        try:
            logger.info(f"Hot-reloading configuration for stream {stream_id}")

            # Get fresh stream data from database
            stream = await asyncio.get_event_loop().run_in_executor(
                None, self.db_manager.get_stream_with_relationships, stream_id
            )

            if not stream:
                logger.error(f"Stream {stream_id} not found for hot-reload")
                return False

            # Create cache key for stream configuration
            cache_key = f"stream_config:{stream.id}"

            # Create new configuration data
            new_config_data = {
                "plugin_type": stream.plugin_type,
                "plugin_config": stream.plugin_config,
                "cot_type": stream.cot_type,
                "poll_interval": stream.poll_interval,
                "is_active": stream.is_active,
                "last_reload": datetime.now(timezone.utc).isoformat(),
            }

            # Check if configuration has actually changed
            config_changed = await self.config_cache.has_configuration_changed(
                cache_key, new_config_data
            )

            if not config_changed:
                logger.debug(
                    f"No configuration changes detected for stream {stream_id}"
                )
                return True

            # Update configuration in cache
            await self.config_cache.update_configuration(cache_key, new_config_data)

            # Check if stream is currently running
            is_running = stream_id in self._stream_workers

            if is_running:
                logger.info(f"Stream {stream_id} is running, applying hot-reload")

                # For certain configuration changes, we can hot-reload without restart
                # Check if only non-critical settings changed
                old_config = await self.config_cache.get_configuration(cache_key)
                can_hot_reload = self._can_hot_reload_changes(
                    old_config, new_config_data
                )

                if can_hot_reload:
                    # Apply configuration changes to running worker
                    worker = self._stream_workers.get(stream_id)
                    if worker and hasattr(worker, "update_configuration"):
                        try:
                            await worker.update_configuration(new_config_data)
                            logger.info(f"Hot-reload successful for stream {stream_id}")
                            return True
                        except Exception as e:
                            logger.warning(
                                f"Hot-reload failed, falling back to restart: {e}"
                            )

                # If hot-reload not possible, restart the stream
                logger.info(f"Restarting stream {stream_id} for configuration changes")
                await self._restart_stream_async(stream_id)
            else:
                logger.info(
                    f"Stream {stream_id} not running, configuration updated in cache"
                )

            # Clear plugin validation cache to force fresh validation
            from plugins.plugin_manager import PluginManager

            plugin_manager = PluginManager()
            plugin_manager.clear_validation_cache()

            return True

        except Exception as e:
            logger.error(f"Error during hot-reload for stream {stream_id}: {e}")
            return False

    def _can_hot_reload_changes(self, old_config: Dict, new_config: Dict) -> bool:
        """
        Determine if configuration changes can be hot-reloaded without restart.

        Safe to hot-reload:
        - poll_interval changes
        - cot_type changes
        - Minor plugin_config updates (non-authentication related)

        Requires restart:
        - plugin_type changes
        - Authentication credential changes
        - TAK server configuration changes
        """
        if not old_config:
            return False

        # Plugin type changes require restart
        if old_config.get("plugin_type") != new_config.get("plugin_type"):
            return False

        # Check for authentication-related plugin config changes
        old_plugin_config = old_config.get("plugin_config", {})
        new_plugin_config = new_config.get("plugin_config", {})

        # Look for credential/authentication changes that require restart
        auth_fields = [
            "username",
            "password",
            "api_key",
            "token",
            "client_id",
            "client_secret",
        ]
        for field in auth_fields:
            if old_plugin_config.get(field) != new_plugin_config.get(field):
                logger.debug(
                    f"Authentication field '{field}' changed, restart required"
                )
                return False

        # Poll interval and CoT type changes are safe for hot-reload
        return True

    async def _optimize_connection_health_checks(self):
        """Optimize connection health checks by running them in parallel"""
        try:
            logger.info("Performing optimized connection health pre-checks")

            # Get all active streams to check connections
            active_streams = self.db_manager.get_active_streams()

            if not active_streams:
                logger.info("No active streams found for health checks")
                return

            # Initialize session manager for connection testing
            await self.session_manager.initialize()

            async def check_connection_health(stream):
                """Check health of a single stream's connections"""
                try:
                    health_status = {
                        "stream_id": stream.id,
                        "stream_name": stream.name,
                        "plugin_health": False,
                        "tak_server_health": False,
                        "overall_health": False,
                    }

                    # Quick plugin API health check if applicable
                    if hasattr(stream, "plugin_config") and stream.plugin_config:
                        plugin_config = stream.plugin_config

                        # Check for API endpoint in plugin config
                        api_url = None
                        for key, value in plugin_config.items():
                            if (
                                "url" in key.lower()
                                and isinstance(value, str)
                                and value.startswith("http")
                            ):
                                api_url = value
                                break

                        if api_url:
                            try:
                                # Quick HEAD request to check if endpoint is reachable
                                session = await self.session_manager.get_session()
                                async with session.head(api_url, timeout=5) as response:
                                    health_status["plugin_health"] = (
                                        response.status < 500
                                    )
                            except Exception:
                                health_status["plugin_health"] = False

                    # TAK server connectivity check
                    if hasattr(stream, "tak_server") and stream.tak_server:
                        try:
                            # Simple connectivity check (not full PyTAK connection)
                            tak_server = stream.tak_server
                            host = tak_server.host
                            port = tak_server.port

                            # Quick socket connection test
                            import socket

                            try:
                                with socket.socket(
                                    socket.AF_INET, socket.SOCK_STREAM
                                ) as sock:
                                    sock.settimeout(3)
                                    result = sock.connect_ex((host, port))
                                    health_status["tak_server_health"] = result == 0
                            except Exception:
                                health_status["tak_server_health"] = False
                        except Exception:
                            health_status["tak_server_health"] = False

                    # Overall health assessment
                    health_status["overall_health"] = (
                        health_status["plugin_health"] or not api_url
                    ) and health_status["tak_server_health"]

                    return health_status

                except Exception as e:
                    logger.debug(f"Error checking health for stream {stream.id}: {e}")
                    return {
                        "stream_id": stream.id,
                        "stream_name": getattr(stream, "name", "Unknown"),
                        "plugin_health": False,
                        "tak_server_health": False,
                        "overall_health": False,
                        "error": str(e),
                    }

            # Run all health checks in parallel
            logger.info(
                f"Running health checks for {len(active_streams)} streams in parallel"
            )
            health_check_tasks = [
                check_connection_health(stream) for stream in active_streams
            ]
            health_results = await asyncio.gather(
                *health_check_tasks, return_exceptions=True
            )

            # Process and report results
            healthy_count = 0
            unhealthy_count = 0
            for result in health_results:
                if isinstance(result, Exception):
                    logger.error(f"Health check task failed: {result}")
                    unhealthy_count += 1
                else:
                    if result["overall_health"]:
                        healthy_count += 1
                        logger.debug(
                            f"Stream {result['stream_id']} ({result['stream_name']}) is healthy"
                        )
                    else:
                        unhealthy_count += 1
                        logger.debug(
                            f"Stream {result['stream_id']} ({result['stream_name']}) has health issues"
                        )

            logger.info(
                f"Connection health pre-checks completed: "
                f"{healthy_count} healthy, {unhealthy_count} unhealthy out of {len(active_streams)} streams"
            )

        except Exception as e:
            logger.error(f"Error during connection health optimization: {e}")

    async def _initialize_persistent_cot_service(self):
        """
        Initialize persistent COT service for all TAK servers.
        Multi-server support with proper deduplication.
        """
        if self._cot_service_initialized:
            return

        try:
            logger.info("Initializing persistent COT service (Multi-server support)")

            # Get all active TAK servers from database
            active_streams = self.db_manager.get_active_streams()

            # Multi-server support with proper deduplication
            tak_servers = {}

            for stream in active_streams:
                # Legacy single-server relationship
                if hasattr(stream, "tak_server") and stream.tak_server:
                    key = getattr(stream.tak_server, "id", None) or getattr(
                        stream.tak_server, "name", None
                    )
                    if key:
                        tak_servers[key] = stream.tak_server

                # Multi-server relationship
                if hasattr(stream, "tak_servers"):
                    try:
                        # Get all servers for this stream via many-to-many relationship
                        multi_servers = stream.tak_servers
                        for server in multi_servers:
                            key = getattr(server, "id", None) or getattr(
                                server, "name", None
                            )
                            if key:
                                tak_servers[key] = server
                    except Exception as e:
                        logger.debug(
                            f"Error accessing multi-server relationship for stream {stream.id}: {e}"
                        )

            # Start persistent workers for each unique TAK server in parallel
            workers_started = 0
            workers_failed = 0

            if tak_servers:
                logger.info(f"Starting {len(tak_servers)} TAK workers in parallel")

                # Create tasks for parallel TAK server connection
                async def start_tak_worker(tak_server):
                    """Start a single TAK worker with error handling"""
                    try:
                        logger.info(
                            f"Starting persistent worker for TAK server: {tak_server.name}"
                        )
                        success = await get_cot_service().start_worker(tak_server)
                        return tak_server, success, None
                    except Exception as e:
                        logger.error(
                            f"Error starting worker for TAK server {tak_server.name}: {e}"
                        )
                        return tak_server, False, e

                # Execute all TAK worker startups concurrently
                tasks = [
                    start_tak_worker(tak_server) for tak_server in tak_servers.values()
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results
                for result in results:
                    if isinstance(result, Exception):
                        workers_failed += 1
                        logger.error(
                            f"Unexpected error in TAK worker startup task: {result}"
                        )
                    else:
                        tak_server, success, error = result
                        if success:
                            workers_started += 1
                            logger.info(
                                f"Successfully started worker for TAK server: {tak_server.name}"
                            )
                        else:
                            workers_failed += 1
                            if error:
                                logger.error(
                                    f"Failed to start worker for TAK server {tak_server.name}: {error}"
                                )
                            else:
                                logger.warning(
                                    f"Failed to start worker for TAK server: {tak_server.name}"
                                )
            else:
                logger.info("No TAK servers found to initialize")

            logger.info(
                f"Initialized persistent COT service: {workers_started} workers started, "
                f"{workers_failed} failed, {len(tak_servers)} total unique servers"
            )
            self._cot_service_initialized = True

        except Exception as e:
            logger.error(
                f"Error initializing persistent COT service: {e}", exc_info=True
            )

    async def _initialize_monitoring_services(self):
        """
        Initialize monitoring services as specified in Phase 2 of RC6.
        Activates existing QueueMonitoringService and QueuePerformanceOptimizer.
        """
        if self._monitoring_initialized:
            return

        try:
            logger.info("Initializing monitoring services (Phase 2)")

            # Start queue monitoring service
            logger.info("Starting QueueMonitoringService")
            await self.monitoring_service.start_monitoring()

            # Start performance optimizer
            logger.info("Starting QueuePerformanceOptimizer")
            await self.performance_optimizer.start_optimization()

            self._monitoring_initialized = True
            logger.info("Monitoring services initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing monitoring services: {e}", exc_info=True)

    async def _cleanup_monitoring_services(self):
        """Clean up monitoring services during shutdown"""
        try:
            logger.info("Stopping monitoring services")

            # Stop queue monitoring service
            if hasattr(self.monitoring_service, "stop_monitoring"):
                await self.monitoring_service.stop_monitoring()
                logger.info("QueueMonitoringService stopped")

            # Stop performance optimizer
            if hasattr(self.performance_optimizer, "stop_optimization"):
                await self.performance_optimizer.stop_optimization()
                logger.info("QueuePerformanceOptimizer stopped")

        except Exception as e:
            logger.error(f"Error cleaning up monitoring services: {e}", exc_info=True)

    def _start_background_loop(self):
        """Start the background event loop in a separate thread"""
        with self._initialization_lock:
            if self._initialized:
                logger.warning("StreamManager already initialized, skipping")
                return
            self._initialized = True

        def run_loop():
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                # Initialize session manager
                self._loop.run_until_complete(self.session_manager.initialize())

                # Start health check task
                self._health_check_task = self._loop.create_task(
                    self._periodic_health_check()
                )

                # Run the background loop
                self._loop.run_until_complete(self._background_loop())

            except Exception as e:
                logger.error(f"Error in background loop: {e}", exc_info=True)
            finally:
                # Cancel health check task
                if self._health_check_task and not self._health_check_task.done():
                    self._health_check_task.cancel()

                # Clean up session manager
                try:
                    self._loop.run_until_complete(self.session_manager.cleanup())
                except (OSError, RuntimeError) as e:
                    logger.error(f"System error cleaning up session manager: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error cleaning up session manager: {e}")

                # Clean up remaining tasks
                pending = asyncio.all_tasks(self._loop)
                if pending:
                    logger.info(f"Cancelling {len(pending)} pending tasks")
                    for task in pending:
                        task.cancel()

                    try:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except (OSError, RuntimeError) as e:
                        logger.error(
                            f"System error while gathering pending tasks during cleanup: {e}",
                            exc_info=True,
                        )
                    except Exception as e:
                        logger.error(
                            f"Unexpected error while gathering pending tasks during cleanup: {e}",
                            exc_info=True,
                        )

                self._loop.close()
                logger.info("Background event loop closed")

        self._loop_thread = threading.Thread(
            target=run_loop, daemon=True, name="StreamManager-Loop"
        )
        self._loop_thread.start()

        # Wait for the loop to start with timeout
        max_wait = 100  # 10 seconds
        wait_count = 0
        while (not self._loop or not self._loop.is_running()) and wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1

        if wait_count >= max_wait:
            logger.error("Background event loop failed to start within timeout")
            raise RuntimeError("Failed to start StreamManager background loop")

    async def _background_loop(self):
        """Background loop that keeps the event loop alive"""
        logger.info("StreamManager background loop started")

        # Initialize persistent COT service after loop starts
        await self._preload_configurations()
        await self._optimize_connection_health_checks()
        await self._initialize_persistent_cot_service()

        # Initialize monitoring services (Phase 2)
        await self._initialize_monitoring_services()

        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(5)  # Check every 5 seconds
        except asyncio.CancelledError:
            logger.info("Background loop cancelled")
        except (OSError, RuntimeError) as e:
            logger.error(f"System error in background loop: {e}", exc_info=True)
            raise StreamManagerError(f"Background loop system error: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error in background loop: {e}", exc_info=True)
            # Re-raise as StreamManagerError for consistency
            raise StreamManagerError(f"Background loop error: {e}") from e

    async def _periodic_health_check(self):
        """Perform periodic health checks on workers"""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(60)  # Health check every minute

                if not self.workers:
                    continue

                logger.debug(f"Performing health check on {len(self.workers)} workers")

                unhealthy_workers = []
                for stream_id, worker in self.workers.items():
                    health = worker.get_health_status()

                    # Check if worker is unhealthy
                    if (
                        not health["running"]
                        or (health["task_done"] and not health["task_cancelled"])
                        or health["consecutive_errors"] >= 3
                    ):
                        unhealthy_workers.append((stream_id, health))

                if unhealthy_workers:
                    logger.warning(f"Found {len(unhealthy_workers)} unhealthy workers")
                    for stream_id, health in unhealthy_workers:
                        logger.warning(f"Worker {stream_id} unhealthy: {health}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic health check: {e}")

    def _run_coroutine_threadsafe(self, coro, timeout=60):
        """Run a coroutine in the background event loop from another thread"""
        if not self._loop or self._loop.is_closed():
            raise RuntimeError("Background event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            logger.error(f"Error in threadsafe coroutine execution: {e}")
            raise

    async def start_stream(self, stream_id: int) -> bool:
        """Start a specific stream with enhanced checking and error handling"""
        try:
            logger.debug(f"Starting stream {stream_id}")

            # Check if already running
            if stream_id in self.workers:
                worker = self.workers[stream_id]
                health = worker.get_health_status()

                if health["running"] and health["startup_complete"]:
                    logger.info(f"Stream {stream_id} is already running")
                    return True
                elif health["running"] and not health["startup_complete"]:
                    logger.warning(f"Stream {stream_id} is currently starting up")
                    return False
                else:
                    # Clean up dead worker
                    logger.info(f"Cleaning up dead worker for stream {stream_id}")
                    try:
                        await asyncio.wait_for(worker.stop(), timeout=15)
                    except asyncio.TimeoutError:
                        logger.error(
                            f"Timeout cleaning up worker for stream {stream_id}"
                        )
                    del self.workers[stream_id]

            # Get fresh stream data from database
            logger.debug(f"Fetching stream {stream_id} from database")
            try:
                stream = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, self.db_manager.get_stream, stream_id
                    ),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                logger.error(f"Timeout fetching stream {stream_id} from database")
                return False

            if not stream:
                logger.error(f"Stream {stream_id} not found")
                return False

            # Validate stream configuration
            if not stream.is_active:
                logger.warning(f"Stream {stream_id} ({stream.name}) is not active")
                return False

            # Validation for both single and multi-server configurations
            has_tak_servers = self._has_tak_servers_configured(stream)
            logger.debug(
                f"Stream {stream_id} TAK server validation: has_servers={has_tak_servers}, tak_server={stream.tak_server}, tak_server_id={stream.tak_server_id}"
            )

            if not has_tak_servers:
                logger.error(f"Stream {stream_id} has no TAK server configured")
                return False

            # Create worker
            logger.debug(f"Creating worker for stream {stream_id} ({stream.name})")
            worker = StreamWorker(stream, self.session_manager, self.db_manager)

            # Start worker with timeout
            try:
                success = await asyncio.wait_for(worker.start(), timeout=120)
            except asyncio.TimeoutError as e:
                logger.error(f"Timeout starting worker for stream {stream_id}: {e}")
                try:
                    await asyncio.wait_for(worker.stop(), timeout=15)
                except Exception as cleanup_error:
                    logger.error(
                        f"Error stopping worker for stream {stream_id} "
                        f"after timeout: {cleanup_error}"
                    )
                return False

            if success:
                # The StreamWorker already ensures the persistent PyTAK worker is running
                # No need to call get_cot_service().start_worker() again here
                logger.debug(f"Stream {stream_id} started successfully.")

                self.workers[stream_id] = worker
                logger.debug(f"Successfully started stream {stream_id}")
            else:
                logger.error(f"Failed to start stream {stream_id}")

            return success

        except asyncio.TimeoutError as e:
            logger.error(f"Timeout in stream startup process for {stream_id}: {e}")
            return False
        except StreamNotFoundError:
            logger.error(f"Stream {stream_id} not found in database")
            return False
        except StreamConfigurationError as e:
            logger.error(f"Stream {stream_id} configuration error: {e}")
            return False
        except (OSError, RuntimeError) as e:
            logger.error(
                f"System error starting stream {stream_id}: {e}", exc_info=True
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error starting stream {stream_id}: {e}", exc_info=True
            )
            return False

    async def stop_stream(self, stream_id: int, skip_db_update=False) -> bool:
        """Stop a specific stream"""
        try:
            if stream_id not in self.workers:
                logger.info(f"Stream {stream_id} not running")
                return True

            worker = self.workers[stream_id]
            await asyncio.wait_for(
                worker.stop(skip_db_update=skip_db_update), timeout=20
            )
            del self.workers[stream_id]

            logger.info(f"Successfully stopped stream {stream_id}")
            return True

        except asyncio.TimeoutError as e:
            logger.error(f"Timeout stopping stream {stream_id}: {e}")
            return False
        except (OSError, RuntimeError) as e:
            logger.error(
                f"System error stopping stream {stream_id}: {e}", exc_info=True
            )
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error stopping stream {stream_id}: {e}", exc_info=True
            )
            return False

    async def restart_stream(self, stream_id: int) -> bool:
        """Enhanced restart with comprehensive worker cleanup"""
        logger.debug(f"Restarting stream {stream_id} with comprehensive worker cleanup")
        logger.debug(
            f"Stream restart initiated at {datetime.now(timezone.utc)} - potential configuration change trigger"
        )

        # Get stream and flush queues (existing logic)...
        try:
            stream = await asyncio.get_event_loop().run_in_executor(
                None, self.db_manager.get_stream_with_relationships, stream_id
            )
            if stream and (self._has_tak_servers_configured(stream)):
                total_flushed = 0
                # Flush queues for all associated TAK servers

                # Handle legacy single-server configuration
                if hasattr(stream, "tak_server") and stream.tak_server:
                    try:
                        flushed_count = await get_cot_service().flush_queue(
                            stream.tak_server.id
                        )
                        total_flushed += flushed_count
                        logger.info(
                            f"Flushed {flushed_count} events from TAK server '{stream.tak_server.name}' queue"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to flush queue for TAK server {stream.tak_server.id}: {e}"
                        )

                # Handle multi-server configuration
                if hasattr(stream, "tak_servers"):
                    try:
                        for tak_server in stream.tak_servers:
                            try:
                                flushed_count = await get_cot_service().flush_queue(
                                    tak_server.id
                                )
                                total_flushed += flushed_count
                                logger.info(
                                    f"Flushed {flushed_count} events from TAK server '{tak_server.name}' queue"
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to flush queue for TAK server {tak_server.id}: {e}"
                                )
                    except Exception as e:
                        logger.warning(
                            f"Error accessing multi-server relationship for stream {stream_id}: {e}"
                        )

                if total_flushed > 0:
                    logger.info(f"Stream restart: flushed {total_flushed} total events")
                else:
                    logger.info("Stream restart: no events to flush")

                # Enhanced worker cleanup before restart
                if stream and self._has_tak_servers_configured(stream):
                    logger.debug(
                        f"Stream restart triggering comprehensive worker cleanup for stream {stream_id} at {datetime.now(timezone.utc)}"
                    )
                    for tak_server in self._get_all_tak_servers(stream):
                        logger.debug(
                            f"Stream restart cleanup: stopping all workers for TAK server {tak_server.name} (ID: {tak_server.id})"
                        )
                        await get_cot_service().stop_all_workers_for_server(
                            tak_server.id
                        )
                        logger.debug(
                            f"Comprehensive worker cleanup completed for TAK server {tak_server.name}"
                        )
            else:
                logger.warning(f"Stream {stream_id} has no TAK servers configured")
        except Exception as e:
            logger.error(f"Error during queue flush for stream {stream_id}: {e}")
            # Continue with restart even if flush fails

        # Proceed with normal restart sequence
        logger.debug(
            f"Beginning stream restart sequence: stop -> sleep -> start for stream {stream_id}"
        )
        await self.stop_stream(stream_id)
        logger.debug(f"Stream {stream_id} stopped, waiting 2 seconds for cleanup")
        await asyncio.sleep(2)
        logger.debug(f"Starting stream {stream_id} after restart cleanup")
        result = await self.start_stream(stream_id)
        logger.debug(
            f"Stream restart completed for {stream_id}: {'success' if result else 'failed'}"
        )
        return result

    async def stop_all(self, skip_db_update=False):
        """Stop all running streams with enhanced database operations"""
        logger.info(f"Stopping all running streams (skip_db_update={skip_db_update})")

        if not self.workers:
            logger.info("No streams to stop")
            return

        # Get list of stream IDs to stop
        stream_ids = list(self.workers.keys())
        logger.info(f"Stopping {len(stream_ids)} streams: {stream_ids}")

        # Create tasks for stopping streams
        tasks = []
        for stream_id in stream_ids:
            tasks.append(self._stop_stream_with_flag(stream_id, skip_db_update))

        # Execute all stop operations concurrently
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Log results and handle any failures
            failed_stops = []
            for i, result in enumerate(results):
                stream_id = stream_ids[i]
                if isinstance(result, Exception):
                    logger.error(f"Failed to stop stream {stream_id}: {result}")
                    failed_stops.append(stream_id)
                elif not result:
                    logger.warning(f"Stream {stream_id} stop returned False")
                    failed_stops.append(stream_id)

            # If not skipping database updates, and we have failures,
            # try to update database status for failed streams
            if not skip_db_update and failed_stops:
                logger.warning(
                    f"Attempting database cleanup for {len(failed_stops)} failed stops"
                )
                await self._cleanup_failed_stream_stops(failed_stops)

        logger.info("All streams stop operations completed")

    async def _stop_stream_with_flag(
        self, stream_id: int, skip_db_update: bool
    ) -> bool:
        """Stop a specific stream with optional database update skip and enhanced error handling"""
        try:
            if stream_id not in self.workers:
                logger.warning(f"Stream {stream_id} not in workers list")

                # Even if not in workers, try to update database status if not skipping
                if not skip_db_update:
                    await self._ensure_stream_stopped_in_db(stream_id)
                return True

            worker = self.workers[stream_id]
            stream_name = getattr(worker.stream, "name", f"Stream-{stream_id}")

            logger.info(f"Stopping worker for stream {stream_id} ({stream_name})")

            # Stop the worker with timeout and error handling
            try:
                await asyncio.wait_for(
                    worker.stop(skip_db_update=skip_db_update), timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout stopping worker for stream {stream_id}, forcing cleanup"
                )
                # Force cleanup even on timeout
                if not skip_db_update:
                    await self._force_stream_cleanup_in_db(
                        stream_id, "Forced stop due to timeout"
                    )
            except Exception as e:
                logger.error(f"Error stopping worker for stream {stream_id}: {e}")
                # Still try to update database even if worker stop failed
                if not skip_db_update:
                    await self._force_stream_cleanup_in_db(
                        stream_id, f"Worker stop error: {str(e)}"
                    )
                raise

            # Remove from workers dictionary
            del self.workers[stream_id]

            logger.info(f"Successfully stopped stream {stream_id} ({stream_name})")
            return True

        except Exception as e:
            logger.error(
                f"Error in _stop_stream_with_flag for stream {stream_id}: {e}",
                exc_info=True,
            )

            # Attempt cleanup even on exception if not skipping database updates
            if not skip_db_update:
                try:
                    await self._force_stream_cleanup_in_db(
                        stream_id, f"Exception during stop: {str(e)}"
                    )
                except Exception as cleanup_error:
                    logger.error(
                        f"Failed to cleanup stream {stream_id} in database: {cleanup_error}"
                    )

            return False

    async def _ensure_stream_stopped_in_db(self, stream_id: int):
        """Ensure stream is marked as stopped in database with robust error handling"""
        # Skip database update if in container shutdown to preserve active state
        if self._is_container_shutdown():
            logger.debug(
                f"Skipping database update for stream {stream_id} (container shutdown)"
            )
            return

        try:
            success = await asyncio.get_event_loop().run_in_executor(
                None,
                self.db_manager.update_stream_status,
                stream_id,
                False,  # is_active = False
                None,  # last_error = None (clear any previous error)
                None,  # messages_sent = None
                datetime.now(timezone.utc),  # last_poll_time
            )

            if success:
                logger.info(
                    f"Successfully updated database status for stream {stream_id} to stopped"
                )
            else:
                logger.warning(
                    f"Failed to update database status for stream {stream_id}"
                )

        except Exception as e:
            logger.error(f"Error ensuring stream {stream_id} stopped in database: {e}")

    async def _force_stream_cleanup_in_db(self, stream_id: int, error_message: str):
        """Force cleanup of stream status in database with error message"""
        # Skip database update if in container shutdown to preserve active state
        if self._is_container_shutdown():
            logger.debug(
                f"Skipping force cleanup for stream {stream_id} (container shutdown)"
            )
            return

        try:
            success = await asyncio.get_event_loop().run_in_executor(
                None,
                self.db_manager.update_stream_status,
                stream_id,
                False,  # is_active = False
                error_message,  # last_error
                None,  # messages_sent = None
                datetime.now(timezone.utc),  # last_poll_time
            )

            if success:
                logger.info(
                    f"Successfully force-cleaned database status for stream {stream_id}"
                )
            else:
                logger.error(
                    f"Failed to force-clean database status for stream {stream_id}"
                )

        except Exception as e:
            logger.error(f"Error in force cleanup for stream {stream_id}: {e}")

    async def _cleanup_failed_stream_stops(self, failed_stream_ids: List[int]):
        """Cleanup database status for streams that failed to stop properly"""
        logger.info(
            f"Cleaning up database status for {len(failed_stream_ids)} failed stream stops"
        )

        cleanup_tasks = []
        for stream_id in failed_stream_ids:
            cleanup_tasks.append(
                self._force_stream_cleanup_in_db(
                    stream_id, "Stream stop operation failed, marked inactive"
                )
            )

        if cleanup_tasks:
            results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)

            # Log cleanup results
            for i, result in enumerate(results):
                stream_id = failed_stream_ids[i]
                if isinstance(result, Exception):
                    logger.error(
                        f"Failed to cleanup stream {stream_id} in database: {result}"
                    )

    def _cleanup_persistent_cot_service(self):
        """Clean up persistent COT service during shutdown"""
        try:
            if hasattr(self, "cot_service") and self.cot_service:
                # Get running workers directly from the service
                running_workers = get_cot_service().workers
                if running_workers:
                    logger.info(
                        f"Stopping {len(running_workers)} persistent COT workers"
                    )
                    for worker in running_workers:
                        if hasattr(worker, "stop"):
                            worker.stop()
                else:
                    # Fallback: just log that we're cleaning up
                    logger.info(
                        "Cleaning up persistent COT service (no running workers method)"
                    )

        except Exception as e:
            logger.error(f"Error cleaning up persistent COT service: {e}")
        finally:
            logger.info("Persistent COT service cleaned up during shutdown")

    def get_stream_status(self, stream_id: int) -> Dict:
        """Get status of a specific stream with enhanced database integration"""
        # Check if stream is in active workers
        if stream_id in self.workers:
            worker = self.workers[stream_id]
            health_status = worker.get_health_status()

            return {
                "running": worker.running,
                "startup_complete": worker.startup_complete,
                "stream_name": worker.stream.name,
                "plugin_type": worker.stream.plugin_type,
                "last_poll": (
                    worker.stream.last_poll.isoformat()
                    if worker.stream.last_poll
                    else None
                ),
                "last_error": worker.stream.last_error,
                "tak_server": self._get_tak_server_display(worker.stream),
                "consecutive_errors": health_status.get("consecutive_errors", 0),
                "last_successful_poll": health_status.get("last_successful_poll"),
                "has_tak_connection": health_status.get("has_tak_connection", False),
                "worker_health": health_status,
            }
        else:
            # Stream not in workers, check database for last known status
            try:
                # Use the new method that handles relationships properly
                stream = self.db_manager.get_stream_with_relationships(stream_id)
                if stream:
                    return {
                        "running": False,
                        "startup_complete": False,
                        "stream_name": stream.name,
                        "plugin_type": stream.plugin_type,
                        "last_poll": (
                            stream.last_poll.isoformat() if stream.last_poll else None
                        ),
                        "last_error": stream.last_error,
                        "tak_server": self._get_tak_server_display(stream),
                        "is_active_in_db": stream.is_active,
                        "consecutive_errors": 0,
                        "last_successful_poll": None,
                        "has_tak_connection": False,
                        "worker_health": None,
                    }
                else:
                    return {
                        "running": False,
                        "startup_complete": False,
                        "error": "Stream not found in database",
                    }
            except Exception as e:
                logger.error(
                    f"Error getting stream {stream_id} status from database: {e}"
                )
                return {
                    "running": False,
                    "startup_complete": False,
                    "error": f"Database error: {str(e)}",
                }

    def get_all_stream_status(self) -> Dict[int, Dict]:
        """Get status of all streams with enhanced database integration"""
        status = {}

        # Get status of active workers
        for stream_id, worker in self.workers.items():
            status[stream_id] = self.get_stream_status(stream_id)

        # Also check for streams in database that might not be running
        try:
            active_streams = self.db_manager.get_active_streams()
            for stream in active_streams:
                if stream.id not in status:
                    # Stream is marked active in DB but not running
                    status[stream.id] = {
                        "running": False,
                        "startup_complete": False,
                        "stream_name": stream.name,
                        "plugin_type": stream.plugin_type,
                        "last_poll": (
                            stream.last_poll.isoformat() if stream.last_poll else None
                        ),
                        "last_error": stream.last_error,
                        "tak_server": self._get_tak_server_display(stream),
                        "is_active_in_db": True,
                        "discrepancy": "Marked active in DB but not running",
                        "consecutive_errors": 0,
                        "last_successful_poll": None,
                        "has_tak_connection": False,
                        "worker_health": None,
                    }
        except Exception as e:
            logger.error(f"Error getting active streams from database: {e}")
            # Add error info to status
            status["_database_error"] = str(e)

        return status

    def ensure_tak_workers_running(self):
        """
        Ensure persistent workers are running for all active TAK servers.
        ulti-server support with proper deduplication.
        """
        try:
            logger.debug("Ensuring TAK workers are running for all active streams")

            # Get currently active streams
            active_streams = self.db_manager.get_active_streams()

            # Deduplication for both legacy and multi-server relationships
            required_tak_servers = {}

            for stream in active_streams:
                # Legacy single-server relationship
                if hasattr(stream, "tak_server") and stream.tak_server:
                    key = getattr(stream.tak_server, "id", None) or getattr(
                        stream.tak_server, "name", None
                    )
                    if key:
                        required_tak_servers[key] = stream.tak_server

                # Multi-server relationship
                if hasattr(stream, "tak_servers"):
                    try:
                        # Get all servers for this stream via many-to-many relationship
                        multi_servers = stream.tak_servers
                        for server in multi_servers:
                            key = getattr(server, "id", None) or getattr(
                                server, "name", None
                            )
                            if key:
                                required_tak_servers[key] = server
                    except Exception as e:
                        logger.debug(
                            f"Error accessing multi-server relationship for stream {stream.id}: {e}"
                        )

            # Get currently running workers
            running_workers = get_cot_service().workers

            # Convert to set of keys for comparison
            running_tak_server_keys = set()
            if running_workers:
                for tak_server in running_workers.keys():
                    key = getattr(tak_server, "id", None) or getattr(
                        tak_server, "name", None
                    )
                    if key:
                        running_tak_server_keys.add(key)

            # Start workers for TAK servers that need them
            required_keys = set(required_tak_servers.keys())
            missing_keys = required_keys - running_tak_server_keys

            # Log detailed worker status
            if required_keys:
                logger.info(
                    f"TAK worker analysis: {len(required_keys)} required, {len(running_tak_server_keys)} running, {len(missing_keys)} missing"
                )
                if missing_keys:
                    missing_servers = [
                        required_tak_servers[key].name for key in missing_keys
                    ]
                    logger.info(
                        f"Missing workers for servers: {', '.join(missing_servers)}"
                    )

            workers_started = 0
            workers_failed = 0
            for key in missing_keys:
                tak_server = required_tak_servers[key]
                try:
                    logger.info(
                        f"Starting missing persistent worker for TAK server: {tak_server.name}"
                    )
                    success = get_cot_service().start_worker(tak_server)
                    if success:
                        workers_started += 1
                        logger.info(
                            f"Successfully started worker for TAK server: {tak_server.name}"
                        )
                    else:
                        workers_failed += 1
                        logger.warning(
                            f"Failed to start worker for TAK server: {tak_server.name}"
                        )
                except Exception as e:
                    workers_failed += 1
                    logger.error(
                        f"Error starting worker for TAK server {tak_server.name}: {e}"
                    )

            if missing_keys:
                logger.info(
                    f"Worker startup completed: {workers_started} started, {workers_failed} failed out of {len(missing_keys)} missing workers"
                )
            else:
                logger.debug("All required TAK workers are already running")

        except Exception as e:
            logger.error(f"Error ensuring TAK workers are running: {e}", exc_info=True)

    async def health_check(self):
        """Perform comprehensive health check on all running streams with database validation"""
        logger.info("Performing comprehensive health check on all streams")

        # Check worker health
        unhealthy_streams = []
        database_sync_issues = []

        for stream_id, worker in self.workers.items():
            health_status = worker.get_health_status()

            # Check if worker is unhealthy
            if (
                not health_status["running"]
                or (health_status["task_done"] and not health_status["task_cancelled"])
                or health_status["consecutive_errors"] >= 3
            ):
                unhealthy_streams.append(stream_id)
                logger.warning(f"Stream {stream_id} appears unhealthy: {health_status}")

        # Check database synchronization
        try:
            active_streams_in_db = await asyncio.get_event_loop().run_in_executor(
                None, self.db_manager.get_active_streams
            )

            db_active_ids = {stream.id for stream in active_streams_in_db}
            worker_ids = set(self.workers.keys())

            # Find discrepancies
            db_only = db_active_ids - worker_ids  # Active in DB but not running
            worker_only = worker_ids - db_active_ids  # Running but not active in DB

            if db_only:
                logger.warning(f"Streams active in DB but not running: {db_only}")
                database_sync_issues.extend(db_only)

            if worker_only:
                logger.warning(f"Streams running but not active in DB: {worker_only}")
                # Update database for running streams not marked active
                for stream_id in worker_only:
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            self.db_manager.update_stream_status,
                            stream_id,
                            True,  # is_active = True
                            None,  # clear any error
                            None,  # messages_sent
                            datetime.now(timezone.utc),  # last_poll_time
                        )
                        logger.info(
                            f"Updated database to mark stream {stream_id} as active"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to update database for stream {stream_id}: {e}"
                        )

        except Exception as e:
            logger.error(f"Error checking database synchronization: {e}")

        # Restart unhealthy streams
        restart_tasks = []
        for stream_id in unhealthy_streams:
            logger.info(f"Attempting to restart unhealthy stream {stream_id}")
            restart_tasks.append(self.restart_stream(stream_id))

        if restart_tasks:
            restart_results = await asyncio.gather(
                *restart_tasks, return_exceptions=True
            )
            for i, result in enumerate(restart_results):
                stream_id = unhealthy_streams[i]
                if isinstance(result, Exception):
                    logger.error(f"Failed to restart stream {stream_id}: {result}")
                elif not result:
                    logger.error(
                        f"Failed to restart stream {stream_id} (returned False)"
                    )
                else:
                    logger.info(f"Successfully restarted stream {stream_id}")

        # Handle database synchronization issues
        for stream_id in database_sync_issues:
            logger.info(
                f"Attempting to start stream {stream_id} (active in DB but not running)"
            )
            try:
                success = await self.start_stream(stream_id)
                if not success:
                    logger.warning(
                        f"Failed to start stream {stream_id}, marking inactive in DB"
                    )
                    # Only mark inactive if not container shutdown
                    if not self._is_container_shutdown():
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            self.db_manager.update_stream_status,
                            stream_id,
                            False,  # is_active = False
                            "Failed to start during health check",  # last_error
                            None,  # messages_sent
                            datetime.now(timezone.utc),  # last_poll_time
                        )
            except Exception as e:
                logger.error(
                    f"Error handling database sync issue for stream {stream_id}: {e}"
                )
        try:
            logger.info("Checking persistent COT service health and worker status")

            # Get initial worker count for comparison
            running_workers_before = get_cot_service().workers
            workers_before_count = (
                len(running_workers_before) if running_workers_before else 0
            )
            logger.info(f"TAK workers before health check: {workers_before_count}")

            # Ensure required workers are running
            self.ensure_tak_workers_running()

            # Check worker health status after ensuring workers are running
            running_workers_after = get_cot_service().workers
            workers_after_count = (
                len(running_workers_after) if running_workers_after else 0
            )

            if workers_after_count != workers_before_count:
                logger.info(
                    f"TAK worker count changed: {workers_before_count} → {workers_after_count}"
                )

            if running_workers_after:
                logger.info(
                    f"Persistent COT service health check: {workers_after_count} workers running"
                )

                # Check individual worker health with detailed logging
                healthy_workers = 0
                unhealthy_workers = 0

                for tak_server, worker_info in running_workers_after.items():
                    server_name = getattr(tak_server, "name", "Unknown")

                    if hasattr(worker_info, "is_healthy"):
                        if worker_info.is_healthy():
                            healthy_workers += 1
                            logger.debug(f"TAK worker for {server_name}: healthy")
                        else:
                            unhealthy_workers += 1
                            logger.warning(
                                f"TAK worker for {server_name}: unhealthy, attempting restart"
                            )
                            try:
                                # Restart the unhealthy worker
                                restart_success = get_cot_service().restart_worker(
                                    tak_server
                                )
                                if restart_success:
                                    logger.info(
                                        f"Successfully restarted TAK worker for {server_name}"
                                    )
                                else:
                                    logger.error(
                                        f"Failed to restart TAK worker for {server_name}"
                                    )
                            except Exception as restart_error:
                                logger.error(
                                    f"Error restarting TAK worker for {server_name}: {restart_error}"
                                )
                    else:
                        logger.debug(
                            f"TAK worker for {server_name}: health check not available"
                        )

                if unhealthy_workers > 0:
                    logger.warning(
                        f"TAK worker health summary: {healthy_workers} healthy, {unhealthy_workers} unhealthy"
                    )
                else:
                    logger.info(f"All {healthy_workers} TAK workers are healthy")
            else:
                logger.warning("No TAK workers are currently running")

        except Exception as e:
            logger.error(
                f"Error checking persistent COT service health: {e}", exc_info=True
            )

        logger.info("Health check completed")

    def shutdown(self):
        """Shutdown the stream manager with enhanced database cleanup"""
        logger.info("Shutting down StreamManager")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop all streams without database updates (since app is shutting down)
        if self._loop and not self._loop.is_closed():
            try:
                # Use shorter timeout for shutdown to prevent hanging
                future = asyncio.run_coroutine_threadsafe(
                    self.stop_all(skip_db_update=True), self._loop
                )
                future.result(timeout=15)  # Reduced timeout for shutdown
                logger.info("All streams stopped during shutdown")
            except asyncio.TimeoutError:
                logger.warning("Timeout stopping streams during shutdown, forcing exit")
            except Exception as e:
                logger.error(f"Error stopping streams during shutdown: {e}")

        # Clean up monitoring services
        if self._monitoring_initialized and self._loop and not self._loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._cleanup_monitoring_services(), self._loop
                )
                future.result(timeout=10)
                logger.info("Monitoring services cleaned up during shutdown")
            except Exception as e:
                logger.error(
                    f"Error cleaning up monitoring services during shutdown: {e}"
                )

        # Clean up persistent COT service - This is NOT a coroutine
        try:
            self._cleanup_persistent_cot_service()
            logger.info("Persistent COT service cleaned up during shutdown")
        except Exception as e:
            logger.error(
                f"Error cleaning up persistent COT service during shutdown: {e}"
            )

        # Cancel health check task
        if self._health_check_task and not self._health_check_task.done():
            try:
                self._health_check_task.cancel()
                logger.info("Health check task cancelled")
            except Exception as e:
                logger.error(f"Error cancelling health check task: {e}")

        # Coordination thread cleanup removed for single worker deployment

        # Wait for thread to finish with timeout
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=15)  # Reduced timeout
            if self._loop_thread.is_alive():
                logger.warning("Background thread did not terminate within timeout")
            else:
                logger.info("Background thread terminated successfully")

        # Worker coordination service close removed for single worker deployment

        # Clear references to avoid memory leaks
        self.workers.clear()
        self.db_manager = None
        self.session_manager = None

    # Thread-safe public methods for Flask routes with enhanced database operations
    def start_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for starting a stream from Flask routes with database validation"""
        with self._manager_lock:
            try:
                # Check if already running before attempting to start
                if stream_id in self.workers:
                    worker = self.workers[stream_id]
                    if worker.running and worker.startup_complete:
                        logger.info(
                            f"Stream {stream_id} is already running (sync check)"
                        )
                        return True

                # Validate stream exists in database before attempting to start
                try:
                    stream = self.db_manager.get_stream(stream_id)
                    if not stream:
                        logger.error(f"Stream {stream_id} not found in database")
                        return False

                    if not stream.is_active:
                        logger.warning(
                            f"Stream {stream_id} is not marked as active in database"
                        )
                        # Could optionally activate it here or return False

                except Exception as e:
                    logger.error(f"Database error checking stream {stream_id}: {e}")
                    return False

                return self._run_coroutine_threadsafe(
                    self.start_stream(stream_id), timeout=120
                )

            except Exception as e:
                logger.error(f"Error in start_stream_sync for stream {stream_id}: {e}")
                return False

    def stop_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for stopping a stream from Flask routes"""
        with self._manager_lock:
            try:
                return self._run_coroutine_threadsafe(
                    self.stop_stream(stream_id), timeout=60
                )
            except Exception as e:
                logger.error(f"Error in stop_stream_sync for stream {stream_id}: {e}")
                return False

    def restart_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for restarting a stream from Flask routes with database validation"""
        with self._manager_lock:
            try:
                # Validate stream exists before restarting
                try:
                    stream = self.db_manager.get_stream(stream_id)
                    if not stream:
                        logger.error(
                            f"Cannot restart stream {stream_id}: not found in database"
                        )
                        return False
                except Exception as e:
                    logger.error(
                        f"Database error checking stream {stream_id} for restart: {e}"
                    )
                    return False

                return self._run_coroutine_threadsafe(
                    self.restart_stream(stream_id), timeout=180
                )
            except Exception as e:
                logger.error(
                    f"Error in restart_stream_sync for stream {stream_id}: {e}"
                )
                return False

    def hot_reload_stream_configuration_sync(self, stream_id: int) -> bool:
        """
        Thread-safe wrapper for hot-reloading stream configuration from Flask routes.

        Implements zero-downtime configuration changes where possible, falling back
        to restart only when necessary (e.g., authentication credential changes).
        """
        with self._manager_lock:
            try:
                # Validate stream exists before hot-reload
                try:
                    stream = self.db_manager.get_stream(stream_id)
                    if not stream:
                        logger.error(
                            f"Cannot hot-reload stream {stream_id}: not found in database"
                        )
                        return False
                except Exception as e:
                    logger.error(
                        f"Database error checking stream {stream_id} for hot-reload: {e}"
                    )
                    return False

                return self._run_coroutine_threadsafe(
                    self.hot_reload_stream_configuration(stream_id), timeout=60
                )
            except Exception as e:
                logger.error(
                    f"Error in hot_reload_stream_configuration_sync for stream {stream_id}: {e}"
                )
                return False

    def refresh_stream_tak_workers(self, stream_id: int) -> bool:
        """
        Refresh TAK workers for a specific stream after configuration changes.
        This ensures persistent workers match the current stream configuration.
        """
        with self._manager_lock:
            try:
                return self._run_coroutine_threadsafe(
                    self._refresh_stream_tak_workers_async(stream_id), timeout=60
                )
            except Exception as e:
                logger.error(
                    f"Error refreshing TAK workers for stream {stream_id}: {e}"
                )
                return False

    async def _refresh_stream_tak_workers_async(self, stream_id: int) -> bool:
        """
        Async implementation of TAK worker refresh for a specific stream.
        Compares current workers with required workers and makes necessary changes.
        """
        try:
            logger.info(f"Refreshing TAK workers for stream {stream_id}")

            # Get fresh stream data from database with relationships
            try:
                stream = await asyncio.get_event_loop().run_in_executor(
                    None, self.db_manager.get_stream_with_relationships, stream_id
                )
                if not stream:
                    logger.error(f"Stream {stream_id} not found for worker refresh")
                    return False
            except Exception as e:
                logger.error(
                    f"Error fetching stream {stream_id} for worker refresh: {e}"
                )
                return False

            # Determine required TAK servers for this stream
            required_servers = {}

            # Check legacy single-server relationship
            if hasattr(stream, "tak_server") and stream.tak_server:
                key = getattr(stream.tak_server, "id", None) or getattr(
                    stream.tak_server, "name", None
                )
                if key:
                    required_servers[key] = stream.tak_server
                    logger.debug(
                        f"Stream {stream_id} requires single TAK server: {stream.tak_server.name}"
                    )

            # Check multi-server relationship
            if hasattr(stream, "tak_servers"):
                try:
                    multi_servers = stream.tak_servers
                    for server in multi_servers:
                        key = getattr(server, "id", None) or getattr(
                            server, "name", None
                        )
                        if key:
                            required_servers[key] = server
                    if required_servers:
                        logger.debug(
                            f"Stream {stream_id} requires {len(required_servers)} TAK servers"
                        )
                except Exception as e:
                    logger.debug(
                        f"Error accessing multi-server relationship for stream {stream_id}: {e}"
                    )

            if not required_servers:
                logger.warning(f"Stream {stream_id} has no TAK servers configured")
                return True  # Not an error if no servers are configured

            # Get currently running workers
            running_workers = get_cot_service().workers
            running_server_keys = set()
            if running_workers:
                for tak_server in running_workers.keys():
                    key = getattr(tak_server, "id", None) or getattr(
                        tak_server, "name", None
                    )
                    if key:
                        running_server_keys.add(key)

            # Determine which workers need to be started
            required_keys = set(required_servers.keys())
            missing_keys = required_keys - running_server_keys

            # Start missing workers
            workers_started = 0
            workers_failed = 0

            for key in missing_keys:
                tak_server = required_servers[key]
                try:
                    logger.info(
                        f"Starting missing persistent worker for TAK server: {tak_server.name}"
                    )
                    success = await get_cot_service().start_worker(tak_server)
                    if success:
                        workers_started += 1
                        logger.info(
                            f"Successfully started worker for TAK server: {tak_server.name}"
                        )
                    else:
                        workers_failed += 1
                        logger.warning(
                            f"Failed to start worker for TAK server: {tak_server.name}"
                        )
                except Exception as e:
                    workers_failed += 1
                    logger.error(
                        f"Error starting worker for TAK server {tak_server.name}: {e}"
                    )

            if missing_keys:
                logger.info(
                    f"TAK worker refresh for stream {stream_id} completed: "
                    f"{workers_started} workers started, {workers_failed} failed"
                )
            else:
                logger.debug(
                    f"All required TAK workers already running for stream {stream_id}"
                )

            # Note: We don't stop workers here because other streams might be using them.
            # The ensure_tak_workers_running() method handles cleanup during periodic checks.

            return workers_failed == 0

        except Exception as e:
            logger.error(
                f"Error in async TAK worker refresh for stream {stream_id}: {e}",
                exc_info=True,
            )
            return False

    @property
    def loop(self):
        return self._loop


def get_stream_manager(app_context_factory=None):
    """Get the stream manager instance - check Flask app context first, then fall back to global"""
    try:
        from flask import current_app, has_app_context

        if has_app_context() and hasattr(current_app, "stream_manager"):
            return current_app.stream_manager
    except (ImportError, RuntimeError):
        # Flask not available or no app context
        pass

    # Fallback to global instance for CLI/standalone use
    global _stream_manager_instance

    with _stream_manager_lock:
        if _stream_manager_instance is None:
            _stream_manager_instance = StreamManager(
                app_context_factory=app_context_factory
            )
        return _stream_manager_instance


# For backward compatibility
# stream_manager = get_stream_manager()
