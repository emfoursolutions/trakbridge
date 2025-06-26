# =============================================================================
# services/stream_worker.py - Stream Worker Service
# Manages the individual streams and is called by Stream Manager Service
# =============================================================================

import asyncio
import logging
from datetime import timezone, datetime
from typing import Dict, List
from plugins.plugin_manager import plugin_manager


class StreamWorker:
    """Individual stream worker that handles a single feed"""

    def __init__(self, stream, session_manager, db_manager):
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
        self._consecutive_errors = 0  # Add this line
        self._last_successful_poll = None  # This one too, since it's also used

    @property
    def startup_complete(self):
        return self._startup_complete

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
                        self.logger.error("Failed to initialize TAK server connection")
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
                'timestamp': datetime.now(timezone.utc)
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
                            self.logger.info(f"Successfully sent {len(locations)} locations to TAK server")
                        else:
                            self.logger.error("Failed to send locations to TAK server")
                            # Try to reinitialize connection
                            await self._cleanup_tak_connection()
                            reconnect_success = await self._initialize_tak_connection()
                            if not reconnect_success:
                                self.logger.warning("Failed to reinitialize TAK connection, trying direct method")
                                success = await self._send_locations_to_tak_fallback(locations)
                                if not success:
                                    raise Exception("Both PyTAK and direct methods failed")
                    else:
                        self.logger.warning("No TAK server configured or COT service not initialized")

                    # Update stream status with success
                    await self._update_stream_status_async(
                        last_error=None,
                        last_poll_time=datetime.now(timezone.utc)
                    )

                    self._consecutive_errors = 0
                    self._last_successful_poll = datetime.now(timezone.utc)
                    self.logger.debug("Poll cycle completed successfully")

                else:
                    self.logger.warning(f"No locations retrieved from {self.stream.plugin_type} plugin")
                    # Still update last poll time even if no data
                    await self._update_stream_status_async(last_poll_time=datetime.now(timezone.utc))

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
                self.logger.info(f"Successfully processed and sent {len(locations)} locations to TAK Server")
            else:
                self.logger.error("Failed to process and send locations to TAK Server")

            return success

        except Exception as e:
            self.logger.error(f"Failed to send locations to TAK server: {e}", exc_info=True)
            return False

    async def _send_locations_to_tak_fallback(self, locations: List[Dict]) -> bool:
        """Initialize client for Direct TAK server connection"""
        try:
            tak_server = self.stream.tak_server
            self.logger.debug(f"Initializing connection to TAK server {tak_server.name}")

            # Initialize the COT service with PyTAK enabled
            if not hasattr(self, 'cot_service'):
                from services.cot_service import EnhancedCOTService
                self.cot_service = EnhancedCOTService(use_pytak=False)

            # Test connection by creating a simple test event
            test_locations = [{
                'uid': f'test-{tak_server.name}',
                'lat': 0.0,
                'lon': 0.0,
                'name': 'Connection Test',
                'timestamp': datetime.now(timezone.utc)
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

            self.logger.info(f"Direct Connection initialized for TAK server {tak_server.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize Direct TAK Server connection: {e}", exc_info=True)
            return False

    def get_health_status(self) -> Dict:
        """Get detailed health status of this worker"""
        # now = datetime.now(timezone.utc)
        return {
            'running': self.running,
            'startup_complete': self._startup_complete,
            'consecutive_errors': self._consecutive_errors,
            'last_successful_poll': self._last_successful_poll.isoformat() if self._last_successful_poll else None,
            'has_tak_connection': self.writer is not None,
            'task_done': self.task.done() if self.task else None,
            'task_cancelled': self.task.cancelled() if self.task else None,
        }
