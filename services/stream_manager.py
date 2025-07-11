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

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import asyncio
import logging
import threading
import time
from typing import Dict, List
from datetime import datetime, timezone

# Local application imports
from services.cot_service import cot_service
from services.database_manager import DatabaseManager
from services.stream_worker import StreamWorker
from services.session_manager import SessionManager
from services.exceptions import (
    StreamManagerError,
    StreamNotFoundError,
    StreamConfigurationError,
)

# Global stream manager instance - use singleton pattern to prevent multiple instances
_stream_manager_instance = None
_stream_manager_lock = threading.Lock()

# Module-level logger
logger = logging.getLogger(__name__)


class StreamManager:
    """Enhanced stream manager with robust database operations"""

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

        # Initialize dependencies
        self.db_manager = DatabaseManager(app_context_factory)
        self.session_manager = SessionManager()

        # Initialize persistent COT service flag
        self._cot_service_initialized = False

        # Start background loop
        self._start_background_loop()

    async def _initialize_persistent_cot_service(self):
        """Initialize persistent COT service for all TAK servers"""
        if self._cot_service_initialized:
            return

        try:
            logger.info("Initializing persistent COT service")

            # Get all active TAK servers from database
            active_streams = self.db_manager.get_active_streams()

            # Use a dictionary to deduplicate by tak_server.id or name
            tak_servers = {}

            for stream in active_streams:
                if stream.tak_server:
                    # Use tak_server.id as key for deduplication
                    # If tak_server doesn't have an id, use name as fallback
                    key = getattr(stream.tak_server, "id", None) or getattr(
                        stream.tak_server, "name", None
                    )
                    if key:
                        tak_servers[key] = stream.tak_server

            # Start persistent workers for each unique TAK server
            for tak_server in tak_servers.values():
                logger.info(
                    f"Starting persistent worker for TAK server: {tak_server.name}"
                )
                await cot_service.start_worker(tak_server)

            logger.info(
                f"Initialized persistent COT service for {len(tak_servers)} TAK servers"
            )
            self._cot_service_initialized = True

        except Exception as e:
            logger.error(
                f"Error initializing persistent COT service: {e}", exc_info=True
            )

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
        await self._initialize_persistent_cot_service()

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
            logger.info(f"Starting stream {stream_id}")

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

            if not stream.tak_server:
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
                # No need to call cot_service.start_worker() again here
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
        """Restart a specific stream"""
        logger.info(f"Restarting stream {stream_id}")
        await self.stop_stream(stream_id)
        await asyncio.sleep(2)  # Give time for cleanup
        return await self.start_stream(stream_id)

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
                # Check if the service has the method before calling it
                if hasattr(self.cot_service, "get_running_workers"):
                    running_workers = self.cot_service.get_running_workers()
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
                "tak_server": (
                    worker.stream.tak_server.name if worker.stream.tak_server else None
                ),
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
                        "tak_server": (
                            stream.tak_server.name if stream.tak_server else None
                        ),
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
                        "tak_server": (
                            stream.tak_server.name if stream.tak_server else None
                        ),
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
        """Ensure persistent workers are running for all active TAK servers"""
        try:
            logger.debug("Ensuring TAK workers are running for all active streams")

            # Get currently active streams
            active_streams = self.db_manager.get_active_streams()

            # Use dictionary to deduplicate TAK servers
            required_tak_servers = {}

            for stream in active_streams:
                if stream.tak_server:
                    key = getattr(stream.tak_server, "id", None) or getattr(
                        stream.tak_server, "name", None
                    )
                    if key:
                        required_tak_servers[key] = stream.tak_server

            # Get currently running workers
            running_workers = cot_service.get_running_workers()

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

            for key in missing_keys:
                tak_server = required_tak_servers[key]
                logger.info(
                    f"Starting missing persistent worker for TAK server: {tak_server.name}"
                )
                cot_service.start_worker(tak_server)

            if missing_keys:
                logger.info(f"Started {len(missing_keys)} missing persistent workers")

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
            logger.debug("Checking persistent COT service health")

            # Ensure required workers are running
            self.ensure_tak_workers_running()

            # Check worker health status
            running_workers = cot_service.get_running_workers()
            if running_workers:
                logger.debug(
                    f"Persistent COT service has {len(running_workers)} running workers"
                )

                # Optional: Check individual worker health
                for tak_server, worker_info in running_workers.items():
                    if (
                        hasattr(worker_info, "is_healthy")
                        and not worker_info.is_healthy()
                    ):
                        logger.warning(
                            f"Persistent worker for {tak_server.name} appears unhealthy"
                        )
                        # Optionally restart the worker
                        cot_service.restart_worker(tak_server)

        except Exception as e:
            logger.error(f"Error checking persistent COT service health: {e}")

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

        # Wait for thread to finish with timeout
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=15)  # Reduced timeout
            if self._loop_thread.is_alive():
                logger.warning("Background thread did not terminate within timeout")
            else:
                logger.info("Background thread terminated successfully")

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
