# =============================================================================
# services/stream_manager.py - Enhanced Stream Management Service
# Fixed Database Operations, Session Management, and Thread Safety
# =============================================================================

import asyncio
import aiohttp
import ssl
from typing import Dict, Optional, List
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import threading
import weakref
import time
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError
from sqlalchemy.orm import scoped_session
import traceback

from models.stream import Stream
from models.tak_server import TakServer
from plugins.plugin_manager import plugin_manager

from database import db


class DatabaseManager:
    """Thread-safe database manager for async operations"""

    def __init__(self):
        self.logger = logging.getLogger('DatabaseManager')
        self._app_context = None

    def get_app_context(self):
        """Get Flask app context for database operations"""
        if not self._app_context:
            try:
                from app import app
                self._app_context = app
            except Exception as e:
                self.logger.error(f"Failed to get app context: {e}")
                return None
        return self._app_context

    def execute_db_operation(self, operation_func, *args, **kwargs):
        """Execute database operation with proper error handling and retry logic"""
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                app = self.get_app_context()
                if not app:
                    self.logger.error("No app context available for database operation")
                    return None

                with app.app_context():
                    # Create a new session for this operation
                    try:
                        result = operation_func(*args, **kwargs)
                        db.session.commit()
                        return result
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        self.logger.error(f"Database error (attempt {attempt + 1}/{max_retries}): {e}")
                        if attempt == max_retries - 1:
                            raise
                        time.sleep(retry_delay * (attempt + 1))
                    except Exception as e:
                        db.session.rollback()
                        self.logger.error(f"Unexpected error in database operation: {e}")
                        raise

            except Exception as e:
                if attempt == max_retries - 1:
                    self.logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                    return None
                time.sleep(retry_delay * (attempt + 1))

        return None

    def get_stream(self, stream_id: int) -> Optional[Stream]:
        """Get stream by ID with error handling and proper session management"""

        def _get_stream():
            stream = Stream.query.get(stream_id)
            if stream:
                # Eagerly load relationships to avoid lazy loading issues
                # This ensures all data is loaded while session is active
                _ = stream.tak_server  # Access tak_server to load it
                if stream.tak_server:
                    _ = stream.tak_server.name  # Access name to ensure it's loaded
                    _ = stream.tak_server.host  # Access other commonly used fields
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                # Create a detached copy with all necessary data
                return self._create_detached_stream_copy(stream)
            return None

        return self.execute_db_operation(_get_stream)

    def _create_detached_stream_copy(self, stream):
        """Create a detached copy of stream with all necessary data"""
        # Create a simple object to hold stream data
        from types import SimpleNamespace

        # Copy basic stream attributes
        stream_copy = SimpleNamespace()
        stream_copy.id = stream.id
        stream_copy.name = stream.name
        stream_copy.plugin_type = stream.plugin_type
        stream_copy.is_active = stream.is_active
        stream_copy.last_poll = stream.last_poll
        stream_copy.last_error = stream.last_error
        stream_copy.poll_interval = stream.poll_interval
        stream_copy.cot_type = stream.cot_type
        stream_copy.cot_stale_time = stream.cot_stale_time
        stream_copy.plugin_config = stream.plugin_config
        stream_copy.total_messages_sent = getattr(stream, 'total_messages_sent', 0)

        # Copy TAK server data if it exists
        if stream.tak_server:
            tak_copy = SimpleNamespace()
            tak_copy.id = stream.tak_server.id
            tak_copy.name = stream.tak_server.name
            tak_copy.host = stream.tak_server.host
            tak_copy.port = stream.tak_server.port
            tak_copy.protocol = stream.tak_server.protocol
            tak_copy.verify_ssl = stream.tak_server.verify_ssl
            tak_copy.cert_p12 = stream.tak_server.cert_p12
            tak_copy.cert_password = stream.tak_server.cert_password
            stream_copy.tak_server = tak_copy
        else:
            stream_copy.tak_server = None

        # Add method to get plugin config
        def get_plugin_config():
            return stream_copy.plugin_config or {}

        stream_copy.get_plugin_config = get_plugin_config

        return stream_copy

    def update_stream_status(self, stream_id: int, is_active=None, last_error=None,
                             messages_sent=None, last_poll_time=None):
        """Update stream status with proper error handling"""

        def _update_stream():
            stream = Stream.query.get(stream_id)
            if not stream:
                self.logger.warning(f"Stream {stream_id} not found for status update")
                return False

            if is_active is not None:
                stream.is_active = is_active

            if last_error is not None:
                stream.last_error = last_error

            if last_poll_time is not None:
                stream.last_poll = last_poll_time
            elif is_active:  # Update last_poll when marking active
                stream.last_poll = datetime.utcnow()

            if messages_sent is not None:
                if not hasattr(stream, 'total_messages_sent') or stream.total_messages_sent is None:
                    stream.total_messages_sent = 0
                stream.total_messages_sent += messages_sent

            return True

        return self.execute_db_operation(_update_stream)

    def get_active_streams(self) -> List[Stream]:
        """Get all active streams with proper session management"""

        def _get_active_streams():
            streams = Stream.query.filter_by(is_active=True).all()
            # Create detached copies of all streams
            detached_streams = []
            for stream in streams:
                # Eagerly load relationships
                _ = stream.tak_server
                if stream.tak_server:
                    _ = stream.tak_server.name
                    _ = stream.tak_server.host
                    _ = stream.tak_server.port
                    _ = stream.tak_server.protocol

                detached_streams.append(self._create_detached_stream_copy(stream))

            return detached_streams

        result = self.execute_db_operation(_get_active_streams)
        return result if result is not None else []

    def get_stream_with_relationships(self, stream_id: int):
        """Get stream with all relationships loaded - for use in Flask routes"""

        def _get_stream_with_relationships():
            from sqlalchemy.orm import joinedload

            # Use joinedload to eagerly load the tak_server relationship
            stream = Stream.query.options(
                joinedload(Stream.tak_server)
            ).filter_by(id=stream_id).first()

            if stream:
                return self._create_detached_stream_copy(stream)
            return None

        return self.execute_db_operation(_get_stream_with_relationships)

    def get_all_streams_with_relationships(self):
        """Get all streams with relationships loaded - for use in Flask routes"""

        def _get_all_streams_with_relationships():
            from sqlalchemy.orm import joinedload

            streams = Stream.query.options(
                joinedload(Stream.tak_server)
            ).all()

            detached_streams = []
            for stream in streams:
                detached_streams.append(self._create_detached_stream_copy(stream))

            return detached_streams

        result = self.execute_db_operation(_get_all_streams_with_relationships)
        return result if result is not None else []

class StreamWorker:
    """Individual stream worker that handles one GPS feed"""

    def __init__(self, stream: Stream, session_manager, db_manager):
        self.stream = stream
        self.plugin = None
        self.running = False
        self.task = None
        self.session_manager = session_manager
        self.db_manager = db_manager
        self.logger = logging.getLogger(f'StreamWorker-{stream.name}')
        self.tak_connection = None
        self.reader = None
        self.writer = None
        self._stop_event = None
        self._start_lock = asyncio.Lock()
        self._startup_complete = False
        self._last_successful_poll = None
        self._consecutive_errors = 0

    async def start(self):
        """Start the stream worker with proper locking and duplicate prevention + PyTAK integration"""
        async with self._start_lock:
            if self.running and self._startup_complete:
                self.logger.warning(f"Stream {self.stream.name} is already running and startup complete")
                return True

            if self.running and not self._startup_complete:
                self.logger.warning(f"Stream {self.stream.name} is starting up, waiting for completion")
                return False

            try:
                self.logger.info(f"Starting stream '{self.stream.name}' (ID: {self.stream.id})")
                self.running = True
                self._startup_complete = False
                self._consecutive_errors = 0

                # Initialize plugin
                self.plugin = plugin_manager.get_plugin(
                    self.stream.plugin_type,
                    self.stream.get_plugin_config()
                )

                if not self.plugin:
                    self.logger.error("Failed to initialize plugin")
                    self.running = False
                    return False

                # Validate plugin configuration
                if not self.plugin.validate_config():
                    self.logger.error("Plugin configuration validation failed")
                    self.running = False
                    return False

                # Initialize TAK server connection with PyTAK if configured
                if self.stream.tak_server:
                    success = await self._initialize_tak_connection()
                    if not success:
                        self.logger.error("Failed to initialize PyTAK TAK server connection")
                        self.running = False
                        return False

                # Create stop event for this loop
                self._stop_event = asyncio.Event()

                # Update stream status in database
                success = await self._update_stream_status_async(is_active=True, last_error=None)
                if not success:
                    self.logger.warning("Failed to update stream status in database during startup")

                # Create task in the current event loop
                self.task = asyncio.create_task(self._run_loop())

                # Mark startup as complete
                self._startup_complete = True
                self.logger.info(f"Stream '{self.stream.name}' started successfully")
                return True

            except Exception as e:
                self.logger.error(f"Failed to start stream '{self.stream.name}': {e}", exc_info=True)
                self.running = False
                self._startup_complete = False
                # Update database with error
                await self._update_stream_status_async(is_active=False, last_error=str(e))
                return False

    async def stop(self, skip_db_update=False):
        """Stop the stream worker and cleanup PyTAK resources"""
        async with self._start_lock:
            if not self.running:
                self.logger.info(f"Stream '{self.stream.name}' is not running, nothing to stop")
                return

            self.logger.info(f"Stopping stream '{self.stream.name}' (skip_db_update={skip_db_update})")
            self.running = False
            self._startup_complete = False

            # Signal stop event
            if self._stop_event:
                self._stop_event.set()

            # Cancel the main task with timeout
            if self.task and not self.task.done():
                self.task.cancel()
                try:
                    await asyncio.wait_for(self.task, timeout=10.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    self.logger.info(f"Task for stream '{self.stream.name}' was cancelled or timed out")

            # Clean up PyTAK resources
            await self._cleanup_tak_connection()

            # Update database only if not during shutdown
            if not skip_db_update:
                await self._update_stream_status_async(is_active=False)

            self.logger.info(f"Stream '{self.stream.name}' stopped successfully")

    async def _update_stream_status_async(self, **kwargs):
        """Update stream status asynchronously"""
        try:
            # Run database operation in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                self.db_manager.update_stream_status,
                self.stream.id,
                kwargs.get('is_active'),
                kwargs.get('last_error'),
                kwargs.get('messages_sent'),
                kwargs.get('last_poll_time')
            )
            return success
        except Exception as e:
            self.logger.error(f"Failed to update stream status asynchronously: {e}")
            return False

    async def _initialize_tak_connection(self) -> bool:
        """Initialize PyTAK client for TAK server connection"""
        try:
            tak_server = self.stream.tak_server
            self.logger.debug(f"Initializing connection to TAK server {tak_server.name}")

            # Initialize the COT service with PyTAK enabled
            if not hasattr(self, 'cot_service'):
                from services.cot_service import EnhancedCOTService
                self.cot_service = EnhancedCOTService(use_pytak=True)

            # Test connection by creating a simple test event
            test_locations = [{
                'uid': f'test-{tak_server.name}',
                'lat': 0.0,
                'lon': 0.0,
                'name': 'Connection Test',
                'timestamp': datetime.utcnow()
            }]

            # Try to create events to validate PyTAK availability
            test_events = await self.cot_service.create_cot_events(
                test_locations,
                self.stream.cot_type or "a-f-G-U-C",
                30  # Short stale time for test
            )

            if not test_events:
                self.logger.error("Failed to create test COT events")
                return False

            self.logger.info(f"Connection initialized for TAK server {tak_server.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize TAK Server connection: {e}", exc_info=True)
            return False

    async def _cleanup_tak_connection(self):
        """Clean up PyTAK connection resources"""
        if hasattr(self, 'cot_service'):
            try:
                await self.cot_service.cleanup()
                self.logger.info("TAK Server connection resources cleaned up")
            except Exception as e:
                self.logger.error(f"Error cleaning up TAK Server connection: {e}")

    async def _run_loop(self):
        """Main processing loop for the stream with PyTAK integration"""
        max_consecutive_errors = 5
        backoff_multiplier = 2
        max_backoff = 300  # 5 minutes

        self.logger.debug(f"Starting main loop for stream '{self.stream.name}' (ID: {self.stream.id})")

        while self.running:
            try:
                self.logger.debug(f"Poll cycle starting for stream '{self.stream.name}'")

                # Fetch locations from GPS service
                locations = []
                try:
                    async with asyncio.timeout(90):  # 90 second timeout
                        locations = await self.plugin.fetch_locations(self.session_manager.session)
                except asyncio.TimeoutError:
                    self.logger.error(f"Plugin fetch_locations timed out after 90 seconds")
                    raise Exception("Plugin fetch timeout")
                except Exception as e:
                    self.logger.error(f"Error fetching locations from plugin: {e}")
                    raise

                if locations:
                    self.logger.info(f"Retrieved {len(locations)} locations from {self.stream.plugin_type} plugin")

                    # Send to TAK server if configured
                    if self.stream.tak_server and hasattr(self, 'cot_service'):
                        success = await self._send_locations_to_tak_pytak(locations)
                        if success:
                            self.logger.info(f"Successfully sent {len(locations)} locations to TAK server via PyTAK")
                        else:
                            self.logger.error("Failed to send locations to TAK server via PyTAK")
                            # Try to reinitialize connection
                            await self._cleanup_tak_connection()
                            reconnect_success = await self._initialize_tak_connection()
                            if not reconnect_success:
                                raise Exception("Failed to reinitialize PyTAK connection")
                    else:
                        self.logger.warning("No TAK server configured or COT service not initialized")

                    # Update stream status with success
                    await self._update_stream_status_async(
                        last_error=None,
                        last_poll_time=datetime.utcnow()
                    )

                    self._consecutive_errors = 0
                    self._last_successful_poll = datetime.utcnow()
                    self.logger.debug("Poll cycle completed successfully")

                else:
                    self.logger.warning(f"No locations retrieved from {self.stream.plugin_type} plugin")
                    # Still update last poll time even if no data
                    await self._update_stream_status_async(last_poll_time=datetime.utcnow())

                # Wait for next poll or stop signal
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.stream.poll_interval)
                    # If we get here, stop was requested
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next poll
                    pass

            except asyncio.CancelledError:
                self.logger.info("Stream loop cancelled")
                break

            except Exception as e:
                self._consecutive_errors += 1
                error_msg = f"Error in stream loop (attempt {self._consecutive_errors}): {e}"
                self.logger.error(error_msg, exc_info=True)

                # Update error in database
                await self._update_stream_status_async(last_error=str(e))

                # If too many consecutive errors, stop the stream
                if self._consecutive_errors >= max_consecutive_errors:
                    self.logger.error(f"Too many consecutive errors ({self._consecutive_errors}), stopping stream")
                    await self._update_stream_status_async(
                        is_active=False,
                        last_error=f"Stopped due to {self._consecutive_errors} consecutive errors"
                    )
                    self.running = False
                    break

                # Progressive backoff for retries
                retry_delay = min(
                    self.stream.poll_interval * (backoff_multiplier ** (self._consecutive_errors - 1)),
                    max_backoff
                )
                self.logger.info(f"Waiting {retry_delay} seconds before retry")

                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=retry_delay)
                    # If we get here, stop was requested
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue
                    pass

        self.logger.info(f"Main loop for stream '{self.stream.name}' has ended")

    async def _send_locations_to_tak_pytak(self, locations: List[Dict]) -> bool:
        """Send locations to TAK server using PyTAK with improved error handling"""
        try:
            if not hasattr(self, 'cot_service'):
                self.logger.error("COT service not initialized")
                return False

            # Use the enhanced COT service to process and send locations
            success = await self.cot_service.process_and_send_locations(
                locations=locations,
                tak_server=self.stream.tak_server,
                cot_type=self.stream.cot_type or "a-f-G-U-C",
                stale_time=self.stream.cot_stale_time or 300
            )

            if success:
                # Update total_messages_sent in database
                await self._update_stream_status_async(messages_sent=len(locations))
                self.logger.info(f"Successfully processed and sent {len(locations)} locations via PyTAK")
            else:
                self.logger.error("Failed to process and send locations via PyTAK")

            return success

        except Exception as e:
            self.logger.error(f"Failed to send locations to TAK server via PyTAK: {e}", exc_info=True)
            return False

    async def _send_locations_to_tak_fallback(self, locations: List[Dict]) -> bool:
        """Fallback method using direct connection (for compatibility)"""
        try:
            # This is your original implementation as fallback
            from services.cot_service import COTService

            # Convert locations to COT events using the original method
            cot_events = COTService.create_cot_events(
                locations,
                self.stream.cot_type,
                self.stream.cot_stale_time
            )

            if not cot_events:
                self.logger.warning("No COT events generated from locations")
                return False

            # Send each COT event with timeout
            messages_sent = 0
            failed_sends = 0

            for i, cot_event in enumerate(cot_events):
                try:
                    # Send with timeout
                    async with asyncio.timeout(30):
                        self.writer.write(cot_event)
                        await self.writer.drain()
                        messages_sent += 1

                    self.logger.debug(f"Sent COT event {i + 1}/{len(cot_events)}")

                except asyncio.TimeoutError:
                    failed_sends += 1
                    self.logger.error(f"Timeout sending COT event {i + 1}")
                    if failed_sends > 3:  # Stop if too many timeouts
                        break

                except Exception as e:
                    failed_sends += 1
                    self.logger.error(f"Failed to send COT event {i + 1}: {e}")
                    if failed_sends > 3:  # Stop if too many failures
                        break

            # Update total_messages_sent in database
            if messages_sent > 0:
                await self._update_stream_status_async(messages_sent=messages_sent)
                self.logger.info(f"Successfully sent {messages_sent}/{len(cot_events)} COT events")

            return messages_sent > 0

        except Exception as e:
            self.logger.error(f"Failed to send locations to TAK server (fallback): {e}", exc_info=True)
            return False


    def get_health_status(self) -> Dict:
        """Get detailed health status of this worker"""
        now = datetime.utcnow()
        return {
            'running': self.running,
            'startup_complete': self._startup_complete,
            'consecutive_errors': self._consecutive_errors,
            'last_successful_poll': self._last_successful_poll.isoformat() if self._last_successful_poll else None,
            'has_tak_connection': self.writer is not None,
            'task_done': self.task.done() if self.task else None,
            'task_cancelled': self.task.cancelled() if self.task else None,
        }


class SessionManager:
    """Manages HTTP sessions for all stream workers with better error handling"""

    def __init__(self):
        self.session = None
        self.logger = logging.getLogger('SessionManager')
        self._session_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize the HTTP session with better configuration"""
        async with self._session_lock:
            if self.session:
                self.logger.info("HTTP session already initialized")
                return

            try:
                timeout = aiohttp.ClientTimeout(
                    total=120,  # Increased total timeout
                    connect=30,  # Increased connect timeout
                    sock_read=30  # Increased read timeout
                )

                connector = aiohttp.TCPConnector(
                    limit=50,  # Increased connection pool size
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                    keepalive_timeout=60,  # Increased keepalive
                    enable_cleanup_closed=True,
                    limit_per_host=10  # Limit per host
                )

                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    trust_env=True  # Use environment proxy settings if available
                )

                self.logger.info("HTTP session initialized successfully")

            except Exception as e:
                self.logger.error(f"Failed to initialize HTTP session: {e}")
                raise

    async def cleanup(self):
        """Clean up the HTTP session"""
        async with self._session_lock:
            if self.session:
                try:
                    await asyncio.wait_for(self.session.close(), timeout=10.0)
                    self.logger.info("HTTP session closed")
                except Exception as e:
                    self.logger.error(f"Error closing HTTP session: {e}")
                finally:
                    self.session = None

    async def get_session(self):
        """Get the session, initializing if necessary"""
        if not self.session or self.session.closed:
            await self.initialize()
        return self.session


# Global stream manager instance - use singleton pattern to prevent multiple instances
_stream_manager_instance = None
_stream_manager_lock = threading.Lock()


class StreamManager:
    """Enhanced stream manager with robust database operations"""

    def __init__(self):
        self.workers: Dict[int, StreamWorker] = {}
        self.logger = logging.getLogger('StreamManager')
        self._loop = None
        self._loop_thread = None
        self._shutdown_event = threading.Event()
        self._session_manager = SessionManager()
        self._db_manager = DatabaseManager()
        self._manager_lock = threading.Lock()
        self._initialization_lock = threading.Lock()
        self._initialized = False
        self._health_check_task = None
        self._start_background_loop()

    def _start_background_loop(self):
        """Start the background event loop in a separate thread"""
        with self._initialization_lock:
            if self._initialized:
                self.logger.warning("StreamManager already initialized, skipping")
                return
            self._initialized = True

        def run_loop():
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                # Initialize session manager
                self._loop.run_until_complete(self._session_manager.initialize())

                # Start health check task
                self._health_check_task = self._loop.create_task(self._periodic_health_check())

                # Run the background loop
                self._loop.run_until_complete(self._background_loop())

            except Exception as e:
                self.logger.error(f"Error in background loop: {e}", exc_info=True)
            finally:
                # Cancel health check task
                if self._health_check_task and not self._health_check_task.done():
                    self._health_check_task.cancel()

                # Clean up session manager
                try:
                    self._loop.run_until_complete(self._session_manager.cleanup())
                except Exception as e:
                    self.logger.error(f"Error cleaning up session manager: {e}")

                # Clean up remaining tasks
                pending = asyncio.all_tasks(self._loop)
                if pending:
                    self.logger.info(f"Cancelling {len(pending)} pending tasks")
                    for task in pending:
                        task.cancel()

                    try:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except Exception:
                        pass

                self._loop.close()
                self.logger.info("Background event loop closed")

        self._loop_thread = threading.Thread(
            target=run_loop,
            daemon=True,
            name="StreamManager-Loop"
        )
        self._loop_thread.start()

        # Wait for the loop to start with timeout
        max_wait = 100  # 10 seconds
        wait_count = 0
        while (not self._loop or not self._loop.is_running()) and wait_count < max_wait:
            time.sleep(0.1)
            wait_count += 1

        if wait_count >= max_wait:
            self.logger.error("Background event loop failed to start within timeout")
            raise RuntimeError("Failed to start StreamManager background loop")

    async def _background_loop(self):
        """Background loop that keeps the event loop alive"""
        self.logger.info("StreamManager background loop started")
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(5)  # Check every 5 seconds
        except asyncio.CancelledError:
            self.logger.info("Background loop cancelled")
        except Exception as e:
            self.logger.error(f"Error in background loop: {e}")

    async def _periodic_health_check(self):
        """Perform periodic health checks on workers"""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(60)  # Health check every minute

                if not self.workers:
                    continue

                self.logger.debug(f"Performing health check on {len(self.workers)} workers")

                unhealthy_workers = []
                for stream_id, worker in self.workers.items():
                    health = worker.get_health_status()

                    # Check if worker is unhealthy
                    if (not health['running'] or
                            (health['task_done'] and not health['task_cancelled']) or
                            health['consecutive_errors'] >= 3):
                        unhealthy_workers.append((stream_id, health))

                if unhealthy_workers:
                    self.logger.warning(f"Found {len(unhealthy_workers)} unhealthy workers")
                    for stream_id, health in unhealthy_workers:
                        self.logger.warning(f"Worker {stream_id} unhealthy: {health}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic health check: {e}")

    def _run_coroutine_threadsafe(self, coro, timeout=60):
        """Run a coroutine in the background event loop from another thread"""
        if not self._loop or self._loop.is_closed():
            raise RuntimeError("Background event loop is not running")

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception as e:
            self.logger.error(f"Error in threadsafe coroutine execution: {e}")
            raise

    async def start_stream(self, stream_id: int) -> bool:
        """Start a specific stream with enhanced checking and error handling"""
        try:
            self.logger.info(f"Starting stream {stream_id}")

            # Check if already running
            if stream_id in self.workers:
                worker = self.workers[stream_id]
                health = worker.get_health_status()

                if health['running'] and health['startup_complete']:
                    self.logger.info(f"Stream {stream_id} is already running")
                    return True
                elif health['running'] and not health['startup_complete']:
                    self.logger.warning(f"Stream {stream_id} is currently starting up")
                    return False
                else:
                    # Clean up dead worker
                    self.logger.info(f"Cleaning up dead worker for stream {stream_id}")
                    try:
                        await asyncio.wait_for(worker.stop(), timeout=15)
                    except asyncio.TimeoutError:
                        self.logger.error(f"Timeout cleaning up worker for stream {stream_id}")
                    del self.workers[stream_id]

            # Get fresh stream data from database
            self.logger.debug(f"Fetching stream {stream_id} from database")
            try:
                stream = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, self._db_manager.get_stream, stream_id
                    ), timeout=15
                )
            except asyncio.TimeoutError:
                self.logger.error(f"Timeout fetching stream {stream_id} from database")
                return False

            if not stream:
                self.logger.error(f"Stream {stream_id} not found")
                return False

            # Validate stream configuration
            if not stream.is_active:
                self.logger.warning(f"Stream {stream_id} ({stream.name}) is not active")
                return False

            if not stream.tak_server:
                self.logger.error(f"Stream {stream_id} has no TAK server configured")
                return False

            # Create worker
            self.logger.debug(f"Creating worker for stream {stream_id} ({stream.name})")
            worker = StreamWorker(stream, self._session_manager, self._db_manager)

            # Start worker with timeout
            try:
                success = await asyncio.wait_for(worker.start(), timeout=120)
            except asyncio.TimeoutError:
                self.logger.error(f"Timeout starting worker for stream {stream_id}")
                try:
                    await asyncio.wait_for(worker.stop(), timeout=15)
                except:
                    pass
                return False

            if success:
                self.workers[stream_id] = worker
                self.logger.debug(f"Successfully started stream {stream_id}")
            else:
                self.logger.error(f"Failed to start stream {stream_id}")

            return success

        except Exception as e:
            self.logger.error(f"Error starting stream {stream_id}: {e}", exc_info=True)
            return False

    async def stop_stream(self, stream_id: int, skip_db_update=False) -> bool:
        """Stop a specific stream"""
        try:
            if stream_id not in self.workers:
                self.logger.info(f"Stream {stream_id} not running")
                return True

            worker = self.workers[stream_id]
            await asyncio.wait_for(worker.stop(skip_db_update=skip_db_update), timeout=20)
            del self.workers[stream_id]

            self.logger.info(f"Successfully stopped stream {stream_id}")
            return True

        except Exception as e:
            self.logger.error(f"Error stopping stream {stream_id}: {e}")
            return False

    async def restart_stream(self, stream_id: int) -> bool:
        """Restart a specific stream"""
        self.logger.info(f"Restarting stream {stream_id}")
        await self.stop_stream(stream_id)
        await asyncio.sleep(2)  # Give time for cleanup
        return await self.start_stream(stream_id)

    async def stop_all(self, skip_db_update=False):
        """Stop all running streams with enhanced database operations"""
        self.logger.info(f"Stopping all running streams (skip_db_update={skip_db_update})")

        if not self.workers:
            self.logger.info("No streams to stop")
            return

        # Get list of stream IDs to stop
        stream_ids = list(self.workers.keys())
        self.logger.info(f"Stopping {len(stream_ids)} streams: {stream_ids}")

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
                    self.logger.error(f"Failed to stop stream {stream_id}: {result}")
                    failed_stops.append(stream_id)
                elif not result:
                    self.logger.warning(f"Stream {stream_id} stop returned False")
                    failed_stops.append(stream_id)

            # If not skipping database updates and we have failures,
            # try to update database status for failed streams
            if not skip_db_update and failed_stops:
                self.logger.warning(f"Attempting database cleanup for {len(failed_stops)} failed stops")
                await self._cleanup_failed_stream_stops(failed_stops)

        self.logger.info("All streams stop operations completed")

    async def _stop_stream_with_flag(self, stream_id: int, skip_db_update: bool) -> bool:
        """Stop a specific stream with optional database update skip and enhanced error handling"""
        try:
            if stream_id not in self.workers:
                self.logger.warning(f"Stream {stream_id} not in workers list")

                # Even if not in workers, try to update database status if not skipping
                if not skip_db_update:
                    await self._ensure_stream_stopped_in_db(stream_id)
                return True

            worker = self.workers[stream_id]
            stream_name = getattr(worker.stream, 'name', f'Stream-{stream_id}')

            self.logger.info(f"Stopping worker for stream {stream_id} ({stream_name})")

            # Stop the worker with timeout and error handling
            try:
                await asyncio.wait_for(
                    worker.stop(skip_db_update=skip_db_update),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                self.logger.error(f"Timeout stopping worker for stream {stream_id}, forcing cleanup")
                # Force cleanup even on timeout
                if not skip_db_update:
                    await self._force_stream_cleanup_in_db(stream_id, "Forced stop due to timeout")
            except Exception as e:
                self.logger.error(f"Error stopping worker for stream {stream_id}: {e}")
                # Still try to update database even if worker stop failed
                if not skip_db_update:
                    await self._force_stream_cleanup_in_db(stream_id, f"Worker stop error: {str(e)}")
                raise

            # Remove from workers dictionary
            del self.workers[stream_id]

            self.logger.info(f"Successfully stopped stream {stream_id} ({stream_name})")
            return True

        except Exception as e:
            self.logger.error(f"Error in _stop_stream_with_flag for stream {stream_id}: {e}", exc_info=True)

            # Attempt cleanup even on exception if not skipping database updates
            if not skip_db_update:
                try:
                    await self._force_stream_cleanup_in_db(stream_id, f"Exception during stop: {str(e)}")
                except Exception as cleanup_error:
                    self.logger.error(f"Failed to cleanup stream {stream_id} in database: {cleanup_error}")

            return False

    async def _ensure_stream_stopped_in_db(self, stream_id: int):
        """Ensure stream is marked as stopped in database with robust error handling"""
        try:
            success = await asyncio.get_event_loop().run_in_executor(
                None,
                self._db_manager.update_stream_status,
                stream_id,
                False,  # is_active = False
                None,  # last_error = None (clear any previous error)
                None,  # messages_sent = None
                datetime.utcnow()  # last_poll_time
            )

            if success:
                self.logger.info(f"Successfully updated database status for stream {stream_id} to stopped")
            else:
                self.logger.warning(f"Failed to update database status for stream {stream_id}")

        except Exception as e:
            self.logger.error(f"Error ensuring stream {stream_id} stopped in database: {e}")

    async def _force_stream_cleanup_in_db(self, stream_id: int, error_message: str):
        """Force cleanup of stream status in database with error message"""
        try:
            success = await asyncio.get_event_loop().run_in_executor(
                None,
                self._db_manager.update_stream_status,
                stream_id,
                False,  # is_active = False
                error_message,  # last_error
                None,  # messages_sent = None
                datetime.utcnow()  # last_poll_time
            )

            if success:
                self.logger.info(f"Successfully force-cleaned database status for stream {stream_id}")
            else:
                self.logger.error(f"Failed to force-clean database status for stream {stream_id}")

        except Exception as e:
            self.logger.error(f"Error in force cleanup for stream {stream_id}: {e}")

    async def _cleanup_failed_stream_stops(self, failed_stream_ids: List[int]):
        """Cleanup database status for streams that failed to stop properly"""
        self.logger.info(f"Cleaning up database status for {len(failed_stream_ids)} failed stream stops")

        cleanup_tasks = []
        for stream_id in failed_stream_ids:
            cleanup_tasks.append(
                self._force_stream_cleanup_in_db(
                    stream_id,
                    "Stream stop operation failed, marked inactive"
                )
            )

        if cleanup_tasks:
            results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)

            # Log cleanup results
            for i, result in enumerate(results):
                stream_id = failed_stream_ids[i]
                if isinstance(result, Exception):
                    self.logger.error(f"Failed to cleanup stream {stream_id} in database: {result}")

    def get_stream_status(self, stream_id: int) -> Dict:
        """Get status of a specific stream with enhanced database integration"""
        # Check if stream is in active workers
        if stream_id in self.workers:
            worker = self.workers[stream_id]
            health_status = worker.get_health_status()

            return {
                'running': worker.running,
                'startup_complete': worker._startup_complete,
                'stream_name': worker.stream.name,
                'plugin_type': worker.stream.plugin_type,
                'last_poll': worker.stream.last_poll.isoformat() if worker.stream.last_poll else None,
                'last_error': worker.stream.last_error,
                'tak_server': worker.stream.tak_server.name if worker.stream.tak_server else None,
                'consecutive_errors': health_status.get('consecutive_errors', 0),
                'last_successful_poll': health_status.get('last_successful_poll'),
                'has_tak_connection': health_status.get('has_tak_connection', False),
                'worker_health': health_status
            }
        else:
            # Stream not in workers, check database for last known status
            try:
                # Use the new method that handles relationships properly
                stream = self._db_manager.get_stream_with_relationships(stream_id)
                if stream:
                    return {
                        'running': False,
                        'startup_complete': False,
                        'stream_name': stream.name,
                        'plugin_type': stream.plugin_type,
                        'last_poll': stream.last_poll.isoformat() if stream.last_poll else None,
                        'last_error': stream.last_error,
                        'tak_server': stream.tak_server.name if stream.tak_server else None,
                        'is_active_in_db': stream.is_active,
                        'consecutive_errors': 0,
                        'last_successful_poll': None,
                        'has_tak_connection': False,
                        'worker_health': None
                    }
                else:
                    return {
                        'running': False,
                        'startup_complete': False,
                        'error': 'Stream not found in database'
                    }
            except Exception as e:
                self.logger.error(f"Error getting stream {stream_id} status from database: {e}")
                return {
                    'running': False,
                    'startup_complete': False,
                    'error': f'Database error: {str(e)}'
                }

    def get_all_stream_status(self) -> Dict[int, Dict]:
        """Get status of all streams with enhanced database integration"""
        status = {}

        # Get status of active workers
        for stream_id, worker in self.workers.items():
            status[stream_id] = self.get_stream_status(stream_id)

        # Also check for streams in database that might not be running
        try:
            active_streams = self._db_manager.get_active_streams()
            for stream in active_streams:
                if stream.id not in status:
                    # Stream is marked active in DB but not running
                    status[stream.id] = {
                        'running': False,
                        'startup_complete': False,
                        'stream_name': stream.name,
                        'plugin_type': stream.plugin_type,
                        'last_poll': stream.last_poll.isoformat() if stream.last_poll else None,
                        'last_error': stream.last_error,
                        'tak_server': stream.tak_server.name if stream.tak_server else None,
                        'is_active_in_db': True,
                        'discrepancy': 'Marked active in DB but not running',
                        'consecutive_errors': 0,
                        'last_successful_poll': None,
                        'has_tak_connection': False,
                        'worker_health': None
                    }
        except Exception as e:
            self.logger.error(f"Error getting active streams from database: {e}")
            # Add error info to status
            status['_database_error'] = str(e)

        return status

    async def health_check(self):
        """Perform comprehensive health check on all running streams with database validation"""
        self.logger.info("Performing comprehensive health check on all streams")

        # Check worker health
        unhealthy_streams = []
        database_sync_issues = []

        for stream_id, worker in self.workers.items():
            health_status = worker.get_health_status()

            # Check if worker is unhealthy
            if (not health_status['running'] or
                    (health_status['task_done'] and not health_status['task_cancelled']) or
                    health_status['consecutive_errors'] >= 3):
                unhealthy_streams.append(stream_id)
                self.logger.warning(f"Stream {stream_id} appears unhealthy: {health_status}")

        # Check database synchronization
        try:
            active_streams_in_db = await asyncio.get_event_loop().run_in_executor(
                None, self._db_manager.get_active_streams
            )

            db_active_ids = {stream.id for stream in active_streams_in_db}
            worker_ids = set(self.workers.keys())

            # Find discrepancies
            db_only = db_active_ids - worker_ids  # Active in DB but not running
            worker_only = worker_ids - db_active_ids  # Running but not active in DB

            if db_only:
                self.logger.warning(f"Streams active in DB but not running: {db_only}")
                database_sync_issues.extend(db_only)

            if worker_only:
                self.logger.warning(f"Streams running but not active in DB: {worker_only}")
                # Update database for running streams not marked active
                for stream_id in worker_only:
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            self._db_manager.update_stream_status,
                            stream_id,
                            True,  # is_active = True
                            None,  # clear any error
                            None,  # messages_sent
                            datetime.utcnow()  # last_poll_time
                        )
                        self.logger.info(f"Updated database to mark stream {stream_id} as active")
                    except Exception as e:
                        self.logger.error(f"Failed to update database for stream {stream_id}: {e}")

        except Exception as e:
            self.logger.error(f"Error checking database synchronization: {e}")

        # Restart unhealthy streams
        restart_tasks = []
        for stream_id in unhealthy_streams:
            self.logger.info(f"Attempting to restart unhealthy stream {stream_id}")
            restart_tasks.append(self.restart_stream(stream_id))

        if restart_tasks:
            restart_results = await asyncio.gather(*restart_tasks, return_exceptions=True)
            for i, result in enumerate(restart_results):
                stream_id = unhealthy_streams[i]
                if isinstance(result, Exception):
                    self.logger.error(f"Failed to restart stream {stream_id}: {result}")
                elif not result:
                    self.logger.error(f"Failed to restart stream {stream_id} (returned False)")
                else:
                    self.logger.info(f"Successfully restarted stream {stream_id}")

        # Handle database synchronization issues
        for stream_id in database_sync_issues:
            self.logger.info(f"Attempting to start stream {stream_id} (active in DB but not running)")
            try:
                success = await self.start_stream(stream_id)
                if not success:
                    self.logger.warning(f"Failed to start stream {stream_id}, marking inactive in DB")
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._db_manager.update_stream_status,
                        stream_id,
                        False,  # is_active = False
                        "Failed to start during health check",  # last_error
                        None,  # messages_sent
                        datetime.utcnow()  # last_poll_time
                    )
            except Exception as e:
                self.logger.error(f"Error handling database sync issue for stream {stream_id}: {e}")

        self.logger.info("Health check completed")

    def shutdown(self):
        """Shutdown the stream manager with enhanced database cleanup"""
        self.logger.info("Shutting down StreamManager")

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
                self.logger.info("All streams stopped during shutdown")
            except asyncio.TimeoutError:
                self.logger.warning("Timeout stopping streams during shutdown, forcing exit")
            except Exception as e:
                self.logger.error(f"Error stopping streams during shutdown: {e}")

        # Cancel health check task
        if self._health_check_task and not self._health_check_task.done():
            try:
                self._health_check_task.cancel()
                self.logger.info("Health check task cancelled")
            except Exception as e:
                self.logger.error(f"Error cancelling health check task: {e}")

        # Wait for thread to finish with timeout
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=15)  # Reduced timeout
            if self._loop_thread.is_alive():
                self.logger.warning("Background thread did not terminate within timeout")
            else:
                self.logger.info("Background thread terminated successfully")

    # Thread-safe public methods for Flask routes with enhanced database operations
    def start_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for starting a stream from Flask routes with database validation"""
        with self._manager_lock:
            try:
                # Check if already running before attempting to start
                if stream_id in self.workers:
                    worker = self.workers[stream_id]
                    if worker.running and worker._startup_complete:
                        self.logger.info(f"Stream {stream_id} is already running (sync check)")
                        return True

                # Validate stream exists in database before attempting to start
                try:
                    stream = self._db_manager.get_stream(stream_id)
                    if not stream:
                        self.logger.error(f"Stream {stream_id} not found in database")
                        return False

                    if not stream.is_active:
                        self.logger.warning(f"Stream {stream_id} is not marked as active in database")
                        # Could optionally activate it here or return False

                except Exception as e:
                    self.logger.error(f"Database error checking stream {stream_id}: {e}")
                    return False

                return self._run_coroutine_threadsafe(self.start_stream(stream_id), timeout=120)

            except Exception as e:
                self.logger.error(f"Error in start_stream_sync for stream {stream_id}: {e}")
                return False

    def stop_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for stopping a stream from Flask routes"""
        with self._manager_lock:
            try:
                return self._run_coroutine_threadsafe(self.stop_stream(stream_id), timeout=60)
            except Exception as e:
                self.logger.error(f"Error in stop_stream_sync for stream {stream_id}: {e}")
                return False

    def restart_stream_sync(self, stream_id: int) -> bool:
        """Thread-safe wrapper for restarting a stream from Flask routes with database validation"""
        with self._manager_lock:
            try:
                # Validate stream exists before restarting
                try:
                    stream = self._db_manager.get_stream(stream_id)
                    if not stream:
                        self.logger.error(f"Cannot restart stream {stream_id}: not found in database")
                        return False
                except Exception as e:
                    self.logger.error(f"Database error checking stream {stream_id} for restart: {e}")
                    return False

                return self._run_coroutine_threadsafe(self.restart_stream(stream_id), timeout=180)
            except Exception as e:
                self.logger.error(f"Error in restart_stream_sync for stream {stream_id}: {e}")
                return False

def get_stream_manager():
    """Get the global stream manager instance (singleton pattern)"""
    global _stream_manager_instance

    with _stream_manager_lock:
        if _stream_manager_instance is None:
            _stream_manager_instance = StreamManager()
        return _stream_manager_instance

    # For backward compatibility
stream_manager = get_stream_manager()