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

                # Provide stream reference to plugin for stream-level configuration access
                if self.plugin:
                    self.plugin.stream = self.stream

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
                self.logger.debug(
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
            self.logger.debug(
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

                    # Apply callsign mapping if enabled
                    await self._apply_callsign_mapping(locations)

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

            # Get COT type mode from fresh stream configuration (avoid cached values)
            fresh_stream_config = await self._get_fresh_stream_config()
            cot_type_mode = fresh_stream_config.get("cot_type_mode", "stream")

            # Get per-callsign CoT type determination (reuse fresh config)
            enable_per_cot_types = fresh_stream_config.get(
                "enable_per_callsign_cot_types", False
            )

            # If either plugin wants per-point mode OR per-callsign CoT types are enabled, use per_point mode
            # This ensures the COT service uses the cot_type field from each location instead of stream default
            if cot_type_mode == "per_point" or bool(enable_per_cot_types):
                cot_type_mode = "per_point"
                self.logger.debug(
                    f"Using per_point mode (fresh config mode: {fresh_stream_config.get('cot_type_mode', 'stream')}, "
                    f"per-callsign CoT types enabled: {bool(enable_per_cot_types)})"
                )
            else:
                self.logger.debug(
                    f"Using stream mode (fresh config mode: {fresh_stream_config.get('cot_type_mode', 'stream')}, "
                    f"per-callsign CoT types enabled: {bool(enable_per_cot_types)})"
                )

            # Create COT events directly
            from services.cot_service import EnhancedCOTService

            try:
                stream_default_cot_type = self.stream.cot_type or "a-f-G-U-C"
                self.logger.debug(
                    f"Creating COT events: mode='{cot_type_mode}', "
                    f"stream_default_cot_type='{stream_default_cot_type}', "
                    f"locations_count={len(locations)}"
                )
                # Log first location's cot_type for debugging
                if locations:
                    first_location_cot_type = locations[0].get("cot_type", "NOT_SET")
                    self.logger.debug(
                        f"First location cot_type: {first_location_cot_type}"
                    )

                cot_events = await EnhancedCOTService().create_cot_events(
                    locations,
                    stream_default_cot_type,
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

    async def _apply_callsign_mapping(self, locations: List[Dict]) -> None:
        """Apply callsign mapping to locations if configured"""
        # Refresh stream configuration from database to get latest settings
        fresh_enable_mapping = await self._get_fresh_callsign_mapping_config()

        # Early exit if callsign mapping not enabled (use fresh config)
        if not bool(fresh_enable_mapping):
            self.logger.debug("Callsign mapping disabled, skipping")
            return

        # Get fresh stream configuration from database for callsign settings
        fresh_stream_config = await self._get_fresh_stream_config()
        if not fresh_stream_config:
            self.logger.error(
                "Failed to load fresh stream configuration, skipping callsign mapping"
            )
            return

        # Load mappings from database table
        callsign_mappings = await self._load_callsign_mappings()
        if not callsign_mappings:
            self.logger.info(
                f"No callsign mappings found for stream {self.stream.id} - callsign mapping will not be applied"
            )
            # If skip mode is enabled and we have no mappings, we need to process locations
            # to potentially skip them all
            if fresh_stream_config.get("callsign_error_handling") != "skip":
                return

        self.logger.info(
            f"Applying {len(callsign_mappings)} callsign mappings for {len(locations)} locations "
            f"using identifier field '{fresh_stream_config.get('callsign_identifier_field')}' "
            f"(error handling: {fresh_stream_config.get('callsign_error_handling', 'fallback')})"
        )

        # Apply mappings with fallback behavior
        locations_to_skip = []
        identifier_field = fresh_stream_config.get("callsign_identifier_field")
        error_handling = fresh_stream_config.get("callsign_error_handling", "fallback")
        enable_per_cot_types = fresh_stream_config.get(
            "enable_per_callsign_cot_types", False
        )

        for i, location in enumerate(locations):
            try:
                identifier = self._extract_identifier(location, identifier_field)
                self.logger.debug(
                    f"Location {i+1}: extracted identifier '{identifier}' from field '{identifier_field}'"
                )

                if identifier and callsign_mappings and identifier in callsign_mappings:
                    mapping = callsign_mappings[identifier]
                    original_name = location.get("name", "Unknown")

                    # Apply callsign mapping through plugin interface if available
                    if self.plugin and hasattr(
                        self.plugin, "supports_callsign_mapping"
                    ):
                        if self.plugin.supports_callsign_mapping():
                            # Use plugin's apply_callsign_mapping method
                            self.logger.debug(
                                f"Using plugin callsign mapping method for identifier '{identifier}'"
                            )
                            self.plugin.apply_callsign_mapping(
                                [location],
                                identifier_field,
                                {identifier: mapping.custom_callsign},
                            )
                        else:
                            # Fallback: apply directly to name field
                            self.logger.debug(
                                "Plugin doesn't support callsign mapping, using direct name replacement"
                            )
                            location["name"] = mapping.custom_callsign
                    else:
                        # Fallback: apply directly to name field
                        self.logger.debug(
                            "No plugin callsign mapping support, using direct name replacement"
                        )
                        location["name"] = mapping.custom_callsign

                    # Apply per-callsign CoT type if enabled and configured
                    if bool(enable_per_cot_types) and mapping.cot_type:
                        location["cot_type"] = mapping.cot_type
                        self.logger.info(
                            f"Applied per-callsign CoT type '{mapping.cot_type}' for identifier '{identifier}'"
                        )

                    self.logger.info(
                        f"Applied callsign mapping: '{identifier}' → '{original_name}' → '{mapping.custom_callsign}'"
                    )
                elif identifier:
                    # Handle unmapped identifiers based on error handling mode
                    if error_handling == "skip":
                        locations_to_skip.append(i)
                        self.logger.warning(
                            f"Skipping location with unmapped identifier: '{identifier}'"
                        )
                    else:  # fallback mode
                        self.logger.info(
                            f"Using fallback (original name) for unmapped identifier: '{identifier}'"
                        )
                        # Keep original name (fallback behavior)
                else:
                    # No identifier extracted
                    self.logger.warning(
                        f"Could not extract identifier from location using field '{identifier_field}' - callsign mapping skipped for this location"
                    )

            except Exception as e:
                self.logger.error(f"Error applying callsign mapping to location: {e}")
                # Handle based on error handling mode
                if error_handling == "skip":
                    locations_to_skip.append(i)
                # Otherwise use fallback (keep original location unchanged)

        # Remove locations marked for skipping (in reverse order to maintain indices)
        for i in reversed(locations_to_skip):
            removed_location = locations.pop(i)
            self.logger.debug(
                f"Removed location due to callsign mapping error: {removed_location.get('name', 'Unknown')}"
            )

        # Summary logging
        applied_count = len(
            [loc for loc in locations if loc.get("name") != loc.get("original_name")]
        )
        skipped_count = len(locations_to_skip)
        processed_count = len(locations) - skipped_count

        self.logger.info(
            f"Callsign mapping summary: {processed_count} locations processed, "
            f"{applied_count} mappings applied, {skipped_count} locations skipped"
        )

    async def _get_fresh_callsign_mapping_config(self) -> bool:
        """Get fresh callsign mapping configuration from database"""
        fresh_config = await self._get_fresh_stream_config()
        if fresh_config:
            enable_mapping = fresh_config.get("enable_callsign_mapping", False)
            return bool(enable_mapping)
        else:
            # Fallback to cached value if available
            return bool(getattr(self.stream, "enable_callsign_mapping", False))

    async def _get_fresh_stream_config(self) -> dict:
        """Get fresh stream configuration from database"""
        try:
            from database import db
            from models.stream import Stream

            # Query fresh configuration from database
            fresh_stream = db.session.query(Stream).filter_by(id=self.stream.id).first()
            if fresh_stream:
                return {
                    "enable_callsign_mapping": getattr(
                        fresh_stream, "enable_callsign_mapping", False
                    ),
                    "callsign_identifier_field": getattr(
                        fresh_stream, "callsign_identifier_field", None
                    ),
                    "callsign_error_handling": getattr(
                        fresh_stream, "callsign_error_handling", "fallback"
                    ),
                    "enable_per_callsign_cot_types": getattr(
                        fresh_stream, "enable_per_callsign_cot_types", False
                    ),
                    "cot_type_mode": getattr(fresh_stream, "cot_type_mode", "stream"),
                }
            else:
                self.logger.warning(
                    f"Stream {self.stream.id} not found in database during config refresh"
                )
                return {}

        except Exception as e:
            self.logger.error(f"Failed to refresh stream config: {e}")
            return {}

    async def _load_callsign_mappings(self) -> Dict[str, any]:
        """Load callsign mappings from database for this stream"""
        try:
            # Import here to avoid circular imports
            from database import db
            from models.callsign_mapping import CallsignMapping

            # Direct database query (same pattern as other services in codebase)
            mappings = (
                db.session.query(CallsignMapping)
                .filter_by(stream_id=self.stream.id)
                .all()
            )

            # Convert to dictionary for efficient lookup
            mappings_dict = {mapping.identifier_value: mapping for mapping in mappings}

            self.logger.debug(
                f"Loaded {len(mappings_dict)} callsign mappings for stream {self.stream.id}"
            )
            return mappings_dict

        except Exception as e:
            self.logger.error(f"Failed to load callsign mappings: {e}")
            return {}

    def _extract_identifier(self, location: Dict, identifier_field: str = None) -> str:
        """Extract identifier value from location data based on configured field"""
        if not identifier_field:
            return None

        field_name = identifier_field

        try:
            # Handle different plugin data structures
            # This is a basic implementation - plugin-specific extraction should be done via the plugin interface
            if field_name == "imei":
                # Garmin-style extraction
                return (
                    location.get("additional_data", {})
                    .get("raw_placemark", {})
                    .get("extended_data", {})
                    .get("IMEI")
                )
            elif field_name == "name":
                # Direct name field
                return location.get("name")
            elif field_name == "uid":
                # UID field
                return location.get("uid")
            elif field_name == "messenger_name":
                # SPOT-style extraction
                return (
                    location.get("additional_data", {})
                    .get("raw_message", {})
                    .get("messengerName")
                )
            elif field_name == "device_id":
                # Traccar-style extraction
                return location.get("additional_data", {}).get("device_id")
            elif field_name == "feed_id":
                # SPOT feed ID
                return location.get("additional_data", {}).get("feed_id")
            else:
                # Generic field extraction - try direct access first
                if field_name in location:
                    return location[field_name]

                # Try additional_data
                return location.get("additional_data", {}).get(field_name)

        except Exception as e:
            self.logger.debug(
                f"Failed to extract identifier '{field_name}' from location: {e}"
            )
            return None
