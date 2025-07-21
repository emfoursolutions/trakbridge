"""
File: services/stream_worker.py

Description:
Individual stream worker service that manages single feed
processing with persistent COT integration.Handles plugin
lifecycle, TAK server connections, location fetching,
and event distribution through the persistent COT service architecture.

Key features:
- Asynchronous stream processing with configurable polling intervals
- Persistent PyTAK server integration with automatic worker management
- Plugin-based location fetching with timeout handling
- Progressive backoff retry logic with consecutive error tracking
- Health status monitoring and connection testing
- Event queuing through persistent COT service
- Graceful startup/shutdown with database synchronization

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List

# Local application imports
from plugins.plugin_manager import get_plugin_manager
from services.cot_service import cot_service


class StreamWorker:
    """Individual stream worker that handles a single feed"""

    def __init__(self, stream, session_manager, db_manager):
        self.stream = stream
        self.plugin = None
        self.running = False
        self.task = None
        self.session_manager = session_manager
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"stream_worker.{stream.name}")
        self.reader = None
        self.writer = None
        self._stop_event = None
        self._start_lock = asyncio.Lock()
        self._startup_complete = False
        self._consecutive_errors = 0
        self._last_successful_poll = None
        self._tak_worker_ensured = (
            False  # Track if we've ensured the persistent worker exists
        )

    @property
    def startup_complete(self):
        return self._startup_complete

    async def start(self):
        """Start the stream worker with persistent PyTAK integration"""
        async with self._start_lock:
            if self.running and self._startup_complete:
                self.logger.warning(
                    f"Stream {self.stream.name} is already running and startup complete"
                )
                return True

            if self.running and not self._startup_complete:
                self.logger.warning(
                    f"Stream {self.stream.name} is starting up, waiting for completion"
                )
                return False

            try:
                self.logger.info(
                    f"Starting stream '{self.stream.name}' (ID: {self.stream.id})"
                )
                self.running = True
                self._startup_complete = False
                self._consecutive_errors = 0

                # Initialize plugin
                self.plugin = get_plugin_manager().get_plugin(
                    self.stream.plugin_type, self.stream.get_plugin_config()
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

                # Initialize persistent TAK server connection if configured
                if self.stream.tak_server:
                    success = await self._ensure_persistent_tak_worker()
                    if not success:
                        self.logger.error(
                            "Failed to ensure persistent TAK server worker"
                        )
                        self.running = False
                        return False

                # Create stop event for this loop
                self._stop_event = asyncio.Event()

                # Update stream status in database
                success = await self._update_stream_status_async(
                    is_active=True, last_error=None
                )
                if not success:
                    self.logger.warning(
                        "Failed to update stream status in database during startup"
                    )

                # Create task in the current event loop
                self.task = asyncio.create_task(self._run_loop())

                # Mark startup as complete
                self._startup_complete = True
                self.logger.info(f"Stream '{self.stream.name}' started successfully")
                return True

            except Exception as e:
                self.logger.error(
                    f"Failed to start stream '{self.stream.name}': {e}", exc_info=True
                )
                self.running = False
                self._startup_complete = False
                # Update database with error
                await self._update_stream_status_async(
                    is_active=False, last_error=str(e)
                )
                return False

    async def stop(self, skip_db_update=False):
        """Stop the stream worker"""
        async with self._start_lock:
            if not self.running:
                self.logger.info(
                    f"Stream '{self.stream.name}' is not running, nothing to stop"
                )
                return

            self.logger.info(
                f"Stopping stream '{self.stream.name}' (skip_db_update={skip_db_update})"
            )
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
                    self.logger.info(
                        f"Task for stream '{self.stream.name}' was cancelled or timed out"
                    )

            # Note: We don't stop the persistent worker here as other streams might be using it
            # The PersistentCOTService manages worker lifecycle automatically
            self._tak_worker_ensured = False

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
                kwargs.get("is_active"),
                kwargs.get("last_error"),
                kwargs.get("messages_sent"),
                kwargs.get("last_poll_time"),
            )
            return success
        except Exception as e:
            self.logger.error(f"Failed to update stream status asynchronously: {e}")
            return False

    async def _ensure_persistent_tak_worker(self) -> bool:
        """Ensure persistent PyTAK worker exists for TAK server connection"""
        try:
            if not cot_service:
                self.logger.error("Persistent COT service not available")
                return False

            tak_server = self.stream.tak_server
            self.logger.debug(
                f"Ensuring persistent worker for TAK server {tak_server.name}"
            )

            # Check if worker is already running
            worker_status = cot_service.get_worker_status(tak_server.id)
            if worker_status and worker_status.get("worker_running", False):
                self.logger.info(
                    f"Persistent worker already running for TAK server {tak_server.name}"
                )
                self._tak_worker_ensured = True
                return True

            # Start the worker
            success = await cot_service.start_worker(tak_server)
            if not success:
                self.logger.error(
                    f"Failed to start persistent worker for TAK server {tak_server.name}"
                )
                return False

            # Verify worker started successfully
            worker_status = cot_service.get_worker_status(tak_server.id)
            if not worker_status or not worker_status.get("worker_running", False):
                self.logger.error(
                    f"Worker failed to start for TAK server {tak_server.name}"
                )
                return False

            # Test the connection with a simple location
            await self._test_persistent_connection()

            self._tak_worker_ensured = True
            self.logger.info(
                f"Persistent worker ensured for TAK server {tak_server.name}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to ensure persistent TAK worker: {e}", exc_info=True
            )
            return False

    async def _test_persistent_connection(self):
        """Test the persistent connection with a simple location"""
        try:
            test_locations = [
                {
                    "uid": f"test-{self.stream.tak_server.name}-{self.stream.name}",
                    "lat": 0.0,
                    "lon": 0.0,
                    "name": f"Connection Test - {self.stream.name}",
                    "timestamp": datetime.now(timezone.utc),
                }
            ]

            # Use the existing method for sending locations
            success = await self._send_locations_to_persistent_tak(test_locations)

            if success:
                self.logger.info(
                    f"Connection test successful for TAK server {self.stream.tak_server.name}"
                )
            else:
                self.logger.warning(
                    f"Connection test failed for TAK server {self.stream.tak_server.name}"
                )

        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")

    async def _run_loop(self):
        """Main processing loop for the stream with persistent PyTAK integration"""
        max_consecutive_errors = 5
        backoff_multiplier = 2
        max_backoff = 300  # 5 minutes

        self.logger.debug(
            f"Starting main loop for stream '{self.stream.name}' (ID: {self.stream.id})"
        )

        while self.running:
            try:
                self.logger.debug(
                    f"Poll cycle starting for stream '{self.stream.name}'"
                )

                # Fetch locations from GPS service
                locations = []
                try:
                    async with asyncio.timeout(90):  # 90 second timeout
                        locations = await self.plugin.fetch_locations(
                            self.session_manager.session
                        )
                except asyncio.TimeoutError:
                    self.logger.error(
                        "Plugin fetch_locations timed out after 90 seconds"
                    )
                    raise Exception("Plugin fetch timeout")
                except Exception as e:
                    self.logger.error(f"Error fetching locations from plugin: {e}")
                    raise

                if locations:
                    self.logger.info(
                        f"Retrieved {len(locations)} locations "
                        f"from {self.stream.plugin_type} plugin"
                    )

                    # Send to persistent TAK server if configured
                    if self.stream.tak_server and self._tak_worker_ensured:
                        success = await self._send_locations_to_persistent_tak(
                            locations
                        )
                        if success:
                            self.logger.info(
                                f"Successfully sent {len(locations)} locations to TAK server"
                            )
                        else:
                            self.logger.error("Failed to send locations to TAK server")
                            # Try to restart the worker
                            self.logger.info(
                                "Attempting to restart persistent TAK worker"
                            )
                            await cot_service.stop_worker(self.stream.tak_server.id)
                            await asyncio.sleep(2)  # Brief delay
                            restart_success = await self._ensure_persistent_tak_worker()
                            if restart_success:
                                # Retry sending
                                success = await self._send_locations_to_persistent_tak(
                                    locations
                                )
                                if not success:
                                    raise Exception(
                                        "Failed to send locations after worker restart"
                                    )
                            else:
                                raise Exception(
                                    "Failed to restart persistent TAK worker"
                                )
                    else:
                        if not self.stream.tak_server:
                            self.logger.warning("No TAK server configured")
                        else:
                            self.logger.warning("Persistent TAK worker not ensured")

                    # Update stream status with success
                    await self._update_stream_status_async(
                        last_error=None, last_poll_time=datetime.now(timezone.utc)
                    )

                    self._consecutive_errors = 0
                    self._last_successful_poll = datetime.now(timezone.utc)
                    self.logger.debug("Poll cycle completed successfully")

                else:
                    self.logger.warning(
                        f"No locations retrieved from {self.stream.plugin_type} plugin"
                    )
                    # Still update last poll time even if no data
                    await self._update_stream_status_async(
                        last_poll_time=datetime.now(timezone.utc)
                    )

                # Wait for next poll or stop signal
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.stream.poll_interval
                    )
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
                error_msg = (
                    f"Error in stream loop (attempt {self._consecutive_errors}): {e}"
                )
                self.logger.error(error_msg, exc_info=True)

                # Update error in database
                await self._update_stream_status_async(last_error=str(e))

                # If too many consecutive errors, stop the stream
                if self._consecutive_errors >= max_consecutive_errors:
                    self.logger.error(
                        f"Too many consecutive errors ({self._consecutive_errors}), stopping stream"
                    )
                    await self._update_stream_status_async(
                        is_active=False,
                        last_error=f"Stopped due to {self._consecutive_errors} consecutive errors",
                    )
                    self.running = False
                    break

                # Progressive backoff for retries
                retry_delay = min(
                    self.stream.poll_interval
                    * (backoff_multiplier ** (self._consecutive_errors - 1)),
                    max_backoff,
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

    async def _send_locations_to_persistent_tak(self, locations: List[Dict]) -> bool:
        """Send locations to persistent TAK server using the persistent service"""

        try:
            if not self._tak_worker_ensured:
                self.logger.error("Persistent TAK worker not ensured")
                return False

            if not cot_service:
                self.logger.error("Persistent COT service not available")
                return False

            # Log the locations being processed
            self.logger.debug(
                f"Processing {len(locations)} locations "
                f"for TAK server {self.stream.tak_server.name}"
            )

            # Check for error responses in locations
            error_locations = [
                loc for loc in locations if isinstance(loc, dict) and "_error" in loc
            ]
            if error_locations:
                self.logger.warning(
                    f"Found {len(error_locations)} error responses in locations, "
                    f"these will be skipped"
                )
                for error_loc in error_locations:
                    self.logger.debug(f"Error location: {error_loc}")

            # If all locations are error responses, treat this as success (no data to send)
            if error_locations and len(error_locations) == len(locations):
                self.logger.info(
                    "All locations were error responses, this is expected behavior"
                )
                return True  # Don't treat this as a failure

            # Get COT type mode from stream configuration
            # Parse the plugin config to get the actual cot_type_mode
            plugin_config = json.loads(self.stream.plugin_config)
            cot_type_mode = plugin_config.get("cot_type_mode", "stream")

            # Create COT events directly
            from services.cot_service import EnhancedCOTService

            try:
                cot_events = await EnhancedCOTService().create_cot_events(
                    locations,
                    self.stream.cot_type or "a-f-G-U-C",
                    self.stream.cot_stale_time or 300,
                    cot_type_mode,  # Pass the COT type mode
                )
                self.logger.info(
                    f"Created {len(cot_events) if cot_events else 0} COT events"
                )
            except Exception as e:
                self.logger.error(f"Error creating COT events: {e}", exc_info=True)
                return False

            if not cot_events:
                self.logger.warning("No COT events created from locations")
                return False

            # Enqueue each event directly
            events_sent = 0
            for event in cot_events:
                await cot_service.enqueue_event(event, self.stream.tak_server.id)
                events_sent += 1

            # Update total_messages_sent in database
            await self._update_stream_status_async(messages_sent=events_sent)
            self.logger.info(
                f"Successfully enqueued {events_sent} COT events via persistent service"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to send locations to persistent TAK server: {e}", exc_info=True
            )
            return False

    def get_health_status(self) -> Dict:
        """Get detailed health status of this worker"""
        # Get persistent worker status if available
        persistent_worker_status = None
        if self.stream.tak_server and cot_service:
            persistent_worker_status = cot_service.get_worker_status(
                self.stream.tak_server.id
            )

        return {
            "running": self.running,
            "startup_complete": self._startup_complete,
            "consecutive_errors": self._consecutive_errors,
            "last_successful_poll": (
                self._last_successful_poll.isoformat()
                if self._last_successful_poll
                else None
            ),
            "tak_worker_ensured": self._tak_worker_ensured,
            "task_done": self.task.done() if self.task else None,
            "task_cancelled": self.task.cancelled() if self.task else None,
            "persistent_worker_status": persistent_worker_status,
            "total_persistent_workers": len(cot_service.workers) if cot_service else 0,
            "total_persistent_queues": len(cot_service.queues) if cot_service else 0,
        }
