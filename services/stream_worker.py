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
        self._tak_worker_ensured = False  # Track if we've ensured the persistent worker exists

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
                self.logger.info(f"Starting stream '{self.stream.name}' (ID: {self.stream.id})")
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
                    # Mark plugin as being in production context for better logging
                    self.plugin._in_production_context = True

                if not self.plugin:
                    self.logger.error("Failed to initialize plugin")
                    self.running = False
                    return False

                # Validate plugin configuration
                if not self.plugin.validate_config():
                    self.logger.error("Plugin configuration validation failed")
                    self.running = False
                    return False

                # Phase 2B: Initialize persistent TAK server connections for all configured servers
                target_servers = await self._get_target_tak_servers()
                if target_servers:
                    self.logger.info(f"Initializing persistent workers for {len(target_servers)} TAK servers")
                    workers_initialized = 0
                    for server in target_servers:
                        if await self._ensure_persistent_tak_worker_for_server(server):
                            workers_initialized += 1
                        else:
                            self.logger.warning(f"Failed to initialize worker for server {server.name}")
                    
                    if workers_initialized == 0:
                        self.logger.error("Failed to initialize any persistent TAK server workers")
                        self.running = False
                        return False
                    elif workers_initialized < len(target_servers):
                        self.logger.warning(f"Only {workers_initialized}/{len(target_servers)} TAK server workers initialized")
                    else:
                        self.logger.info(f"All {workers_initialized} TAK server workers initialized successfully")
                    
                    # Mark that at least some workers are ensured
                    self._tak_worker_ensured = True
                else:
                    self.logger.error("No TAK servers configured for stream")
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
                self.logger.error(
                    f"Failed to start stream '{self.stream.name}': {e}", exc_info=True
                )
                self.running = False
                self._startup_complete = False
                # Update database with error
                await self._update_stream_status_async(is_active=False, last_error=str(e))
                return False

    async def stop(self, skip_db_update=False):
        """Stop the stream worker"""
        async with self._start_lock:
            if not self.running:
                self.logger.info(f"Stream '{self.stream.name}' is not running, nothing to stop")
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
            self.logger.debug(f"Ensuring persistent worker for TAK server {tak_server.name}")

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
                self.logger.error(f"Worker failed to start for TAK server {tak_server.name}")
                return False

            # Test the connection with a simple location
            await self._test_persistent_connection()

            self._tak_worker_ensured = True
            self.logger.debug(f"Persistent worker ensured for TAK server {tak_server.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to ensure persistent TAK worker: {e}", exc_info=True)
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
                self.logger.debug(f"Poll cycle starting for stream '{self.stream.name}'")

                # Fetch locations from GPS service
                locations = []
                try:
                    async with asyncio.timeout(90):  # 90 second timeout
                        locations = await self.plugin.fetch_locations(self.session_manager.session)
                except asyncio.TimeoutError:
                    self.logger.error("Plugin fetch_locations timed out after 90 seconds")
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

                    # Phase 2B: Send to persistent TAK server(s) if configured
                    if self._tak_worker_ensured:
                        success = await self._send_locations_to_persistent_tak(locations)
                        if success:
                            self.logger.info(
                                f"Successfully sent {len(locations)} locations to TAK server(s)"
                            )
                        else:
                            self.logger.error("Failed to send locations to TAK server(s)")
                            # Phase 2B: Try to restart workers for all target servers
                            self.logger.info("Attempting to restart persistent TAK workers")
                            target_servers = await self._get_target_tak_servers()
                            
                            # Stop all workers
                            for server in target_servers:
                                try:
                                    await cot_service.stop_worker(server.id)
                                except Exception as e:
                                    self.logger.warning(f"Error stopping worker for {server.name}: {e}")
                            
                            await asyncio.sleep(2)  # Brief delay
                            
                            # Restart workers
                            workers_restarted = 0
                            for server in target_servers:
                                if await self._ensure_persistent_tak_worker_for_server(server):
                                    workers_restarted += 1
                            
                            if workers_restarted > 0:
                                self.logger.info(f"Restarted {workers_restarted}/{len(target_servers)} workers")
                                # Retry sending
                                success = await self._send_locations_to_persistent_tak(locations)
                                if not success:
                                    raise Exception("Failed to send locations after worker restart")
                            else:
                                raise Exception("Failed to restart any persistent TAK workers")
                    else:
                        self.logger.warning("No persistent TAK workers ensured")

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
                error_msg = f"Error in stream loop (attempt {self._consecutive_errors}): {e}"
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
        """
        Send locations to persistent TAK server(s) using the persistent service.
        
        Phase 2B: Multi-Server Distribution Logic
        - Supports both legacy single-server and new multi-server approaches
        - Single API fetch distributed to multiple servers (major performance improvement)
        - Server failure isolation - if one server fails, others continue
        - Backward compatibility maintained for existing streams
        """
        try:
            if not cot_service:
                self.logger.error("Persistent COT service not available")
                return False

            # Phase 2B: Determine target servers (multi-server or legacy single-server)
            target_servers = await self._get_target_tak_servers()
            if not target_servers:
                self.logger.error("No target TAK servers found for stream")
                return False

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
                self.logger.info("All locations were error responses, this is expected behavior")
                return True  # Don't treat this as a failure

            # Phase 2B: Single API fetch → Multiple server distribution
            self.logger.info(
                f"Processing {len(locations)} locations for distribution to "
                f"{len(target_servers)} TAK server(s): {[s.name for s in target_servers]}"
            )

            # Get COT configuration
            fresh_stream_config = await self._get_fresh_stream_config()
            cot_type_mode = fresh_stream_config.get("cot_type_mode", "stream")
            enable_per_cot_types = fresh_stream_config.get("enable_per_callsign_cot_types", False)

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

            # Create COT events once (shared across all servers)
            from services.cot_service import EnhancedCOTService

            try:
                stream_default_cot_type = self.stream.cot_type or "a-f-G-U-C"
                self.logger.debug(
                    f"Creating COT events: mode='{cot_type_mode}', "
                    f"stream_default_cot_type='{stream_default_cot_type}', "
                    f"locations_count={len(locations)}"
                )
                if locations:
                    first_location_cot_type = locations[0].get("cot_type", "NOT_SET")
                    self.logger.debug(f"First location cot_type: {first_location_cot_type}")

                cot_events = await EnhancedCOTService().create_cot_events(
                    locations,
                    stream_default_cot_type,
                    self.stream.cot_stale_time or 300,
                    cot_type_mode,
                )
                self.logger.info(f"Created {len(cot_events) if cot_events else 0} COT events")
            except Exception as e:
                self.logger.error(f"Error creating COT events: {e}", exc_info=True)
                return False

            if not cot_events:
                self.logger.warning("No COT events created from locations")
                return False

            # Phase 2B: Distribute to multiple servers with failure isolation
            distribution_results = await self._distribute_to_multiple_servers(cot_events, target_servers)
            
            # Analyze results
            successful_servers = [result['server'] for result in distribution_results if result['success']]
            failed_servers = [result['server'] for result in distribution_results if not result['success']]
            
            total_events_sent = sum(result.get('events_sent', 0) for result in distribution_results if result['success'])

            # Log distribution results
            if successful_servers:
                self.logger.info(
                    f"Successfully distributed {len(cot_events)} COT events to "
                    f"{len(successful_servers)}/{len(target_servers)} servers: "
                    f"{[s.name for s in successful_servers]}"
                )
            
            if failed_servers:
                self.logger.error(
                    f"Failed to distribute to {len(failed_servers)} servers: "
                    f"{[s.name for s in failed_servers]}"
                )

            # Update total_messages_sent in database (total across all successful servers)
            await self._update_stream_status_async(messages_sent=total_events_sent)

            # Phase 2B: Partial success is acceptable (server failure isolation)
            # As long as at least one server received the data, consider it successful
            return len(successful_servers) > 0

        except Exception as e:
            self.logger.error(
                f"Failed to send locations to persistent TAK server(s): {e}", exc_info=True
            )
            return False

    def get_health_status(self) -> Dict:
        """Get detailed health status of this worker"""
        # Get persistent worker status if available
        persistent_worker_status = None
        if self.stream.tak_server and cot_service:
            persistent_worker_status = cot_service.get_worker_status(self.stream.tak_server.id)

        return {
            "running": self.running,
            "startup_complete": self._startup_complete,
            "consecutive_errors": self._consecutive_errors,
            "last_successful_poll": (
                self._last_successful_poll.isoformat() if self._last_successful_poll else None
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

        # Load enabled mappings from database table
        callsign_mappings = await self._load_callsign_mappings()
        
        # Also load disabled mappings for filtering purposes
        disabled_mappings = await self._load_disabled_callsign_mappings()
        
        if not callsign_mappings:
            self.logger.info(
                f"No enabled callsign mappings found for stream {self.stream.id} - callsign mapping will not be applied"
            )
            # If skip mode is enabled and we have no mappings, we need to process locations
            # to potentially skip them all
            if fresh_stream_config.get("callsign_error_handling") != "skip":
                # Still need to filter out disabled trackers even if no enabled mappings
                await self._filter_disabled_trackers(locations, disabled_mappings, fresh_stream_config)
                return

        self.logger.info(
            f"Applying {len(callsign_mappings)} callsign mappings for {len(locations)} locations "
            f"using identifier field '{fresh_stream_config.get('callsign_identifier_field')}' "
            f"(error handling: {fresh_stream_config.get('callsign_error_handling', 'fallback')})"
        )

        # First, filter out disabled trackers before applying mappings
        await self._filter_disabled_trackers(locations, disabled_mappings, fresh_stream_config)

        # Apply mappings with fallback behavior
        locations_to_skip = []
        identifier_field = fresh_stream_config.get("callsign_identifier_field")
        error_handling = fresh_stream_config.get("callsign_error_handling", "fallback")
        enable_per_cot_types = fresh_stream_config.get("enable_per_callsign_cot_types", False)

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
                    if self.plugin and hasattr(self.plugin, "supports_callsign_mapping"):
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
        """Load enabled callsign mappings from database for this stream"""
        try:
            # Import here to avoid circular imports
            from database import db
            from models.callsign_mapping import CallsignMapping

            # Load only enabled callsign mappings
            mappings = db.session.query(CallsignMapping).filter_by(
                stream_id=self.stream.id, enabled=True
            ).all()

            # Convert to dictionary for efficient lookup
            mappings_dict = {mapping.identifier_value: mapping for mapping in mappings}

            self.logger.debug(
                f"Loaded {len(mappings_dict)} enabled callsign mappings for stream {self.stream.id}"
            )
            return mappings_dict

        except Exception as e:
            self.logger.error(f"Failed to load callsign mappings: {e}")
            return {}

    async def _load_disabled_callsign_mappings(self) -> Dict[str, any]:
        """Load disabled callsign mappings from database for filtering"""
        try:
            # Import here to avoid circular imports
            from database import db
            from models.callsign_mapping import CallsignMapping

            # Load only disabled callsign mappings for filtering
            disabled_mappings = db.session.query(CallsignMapping).filter_by(
                stream_id=self.stream.id, enabled=False
            ).all()

            # Convert to dictionary for efficient lookup
            disabled_dict = {mapping.identifier_value: mapping for mapping in disabled_mappings}

            self.logger.debug(
                f"Loaded {len(disabled_dict)} disabled callsign mappings for stream {self.stream.id}"
            )
            return disabled_dict

        except Exception as e:
            self.logger.error(f"Failed to load disabled callsign mappings: {e}")
            return {}

    async def _filter_disabled_trackers(self, locations: List[Dict], disabled_mappings: Dict, fresh_stream_config: Dict) -> None:
        """Filter out locations from disabled trackers"""
        if not disabled_mappings:
            return

        identifier_field = fresh_stream_config.get("callsign_identifier_field")
        if not identifier_field:
            return

        locations_to_remove = []
        
        for i, location in enumerate(locations):
            try:
                identifier = self._extract_identifier(location, identifier_field)
                if identifier and identifier in disabled_mappings:
                    locations_to_remove.append(i)
                    self.logger.debug(
                        f"Filtering out disabled tracker: '{identifier}' (name: {location.get('name', 'Unknown')})"
                    )
            except Exception as e:
                self.logger.error(f"Error checking if tracker is disabled: {e}")

        # Remove disabled tracker locations (in reverse order to maintain indices)
        for i in reversed(locations_to_remove):
            removed_location = locations.pop(i)
            self.logger.info(
                f"Removed location from disabled tracker: {removed_location.get('name', 'Unknown')}"
            )

        if locations_to_remove:
            self.logger.info(f"Filtered out {len(locations_to_remove)} locations from disabled trackers")

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
                    location.get("additional_data", {}).get("raw_message", {}).get("messengerName")
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
            self.logger.debug(f"Failed to extract identifier '{field_name}' from location: {e}")
            return None

    async def _get_target_tak_servers(self) -> List:
        """
        Phase 2B: Get target TAK servers for this stream.
        Supports both legacy single-server and new multi-server approaches.
        
        Returns:
            List of TakServer objects to send data to
        """
        try:
            target_servers = []
            
            # Phase 2B: Check multi-server relationship first
            if hasattr(self.stream, 'tak_servers'):
                try:
                    # Use dynamic loading to get all associated servers
                    multi_servers = self.stream.tak_servers
                    if multi_servers:
                        target_servers = list(multi_servers)
                        server_names = [s.name for s in target_servers]
                        server_ids = [s.id for s in target_servers]
                        self.logger.info(
                            f"Using multi-server configuration: {len(target_servers)} servers found - Names: {server_names}, IDs: {server_ids}"
                        )
                except Exception as e:
                    self.logger.error(f"Error accessing multi-server relationship: {e}")
            
            # Backward compatibility: Fall back to legacy single-server relationship
            if not target_servers and hasattr(self.stream, 'tak_server') and self.stream.tak_server:
                target_servers = [self.stream.tak_server]
                self.logger.debug("Using legacy single-server configuration")
            
            # Ensure all target servers have workers
            for server in target_servers:
                if not await self._ensure_persistent_tak_worker_for_server(server):
                    self.logger.warning(f"Failed to ensure worker for server {server.name}")
            
            return target_servers
            
        except Exception as e:
            self.logger.error(f"Error getting target TAK servers: {e}", exc_info=True)
            return []

    async def _ensure_persistent_tak_worker_for_server(self, tak_server) -> bool:
        """
        Ensure persistent PyTAK worker exists for a specific TAK server.
        Phase 2B: Supports multiple servers with worker deduplication.
        """
        try:
            if not cot_service:
                self.logger.error("Persistent COT service not available")
                return False

            self.logger.debug(f"Ensuring persistent worker for TAK server {tak_server.name}")

            # Check if worker is already running
            worker_status = cot_service.get_worker_status(tak_server.id)
            if worker_status and worker_status.get("worker_running", False):
                self.logger.debug(
                    f"Persistent worker already running for TAK server {tak_server.name}"
                )
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
                self.logger.error(f"Worker failed to start for TAK server {tak_server.name}")
                return False

            self.logger.debug(f"Persistent worker ensured for TAK server {tak_server.name}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to ensure persistent TAK worker for {tak_server.name}: {e}", exc_info=True)
            return False

    async def _distribute_to_multiple_servers(self, cot_events: List, target_servers: List) -> List[Dict]:
        """
        Phase 2B: Distribute COT events to multiple TAK servers with failure isolation.
        
        Args:
            cot_events: List of COT events to distribute
            target_servers: List of TakServer objects to send to
            
        Returns:
            List of distribution results with success status for each server
        """
        distribution_results = []
        
        try:
            # Phase 2B: Concurrent distribution to multiple servers
            distribution_tasks = []
            server_names = [server.name for server in target_servers]
            
            self.logger.info(f"Starting distribution of {len(cot_events)} events to {len(target_servers)} servers: {server_names}")
            
            for server in target_servers:
                self.logger.debug(f"Creating distribution task for server: {server.name} (ID: {server.id})")
                task = self._send_to_single_server(cot_events, server)
                distribution_tasks.append(task)
            
            # Execute all distributions concurrently with failure isolation
            self.logger.debug(f"Executing {len(distribution_tasks)} distribution tasks concurrently")
            results = await asyncio.gather(*distribution_tasks, return_exceptions=True)
            
            # Process results
            for i, result in enumerate(results):
                server = target_servers[i]
                
                if isinstance(result, Exception):
                    # Server failed, but others can continue (failure isolation)
                    self.logger.error(f"Distribution to {server.name} (ID: {server.id}) failed with exception: {result}")
                    distribution_results.append({
                        'server': server,
                        'success': False,
                        'error': str(result),
                        'events_sent': 0
                    })
                else:
                    # Server succeeded
                    events_sent = result.get('events_sent', 0)
                    success = result.get('success', False)
                    self.logger.info(f"Distribution to {server.name} (ID: {server.id}): success={success}, events_sent={events_sent}")
                    
                    distribution_results.append({
                        'server': server,
                        'success': success,
                        'events_sent': events_sent,
                        'error': result.get('error')
                    })
            
            return distribution_results
            
        except Exception as e:
            self.logger.error(f"Error in multi-server distribution: {e}", exc_info=True)
            
            # Return failure results for all servers
            return [
                {
                    'server': server,
                    'success': False,
                    'error': f"Distribution error: {str(e)}",
                    'events_sent': 0
                }
                for server in target_servers
            ]

    async def _send_to_single_server(self, cot_events: List, server) -> Dict:
        """
        Send COT events to a single TAK server.
        Phase 2B: Individual server distribution with error handling.
        """
        try:
            self.logger.info(f"Sending {len(cot_events)} events to server {server.name} (ID: {server.id})")
            
            # Use smart queue replacement for large batches to prevent accumulation
            if len(cot_events) >= 10:  # Use replacement logic for large batches
                self.logger.info(f"Using queue replacement for large batch of {len(cot_events)} events to {server.name}")
                success = await cot_service.enqueue_with_replacement(cot_events, server.id)
                events_sent = len(cot_events) if success else 0
                self.logger.info(f"Queue replacement result for {server.name}: success={success}, events_sent={events_sent}")
            else:
                # Use individual enqueueing for small batches
                events_sent = 0
                for event in cot_events:
                    success = await cot_service.enqueue_event(event, server.id)
                    if success:
                        events_sent += 1
                    else:
                        self.logger.warning(f"Failed to enqueue event to server {server.name}")
                self.logger.debug(f"Individually enqueued {events_sent}/{len(cot_events)} events to {server.name}")
            
            return {
                'success': True,
                'events_sent': events_sent,
                'server_name': server.name
            }
            
        except Exception as e:
            self.logger.error(f"Failed to send events to server {server.name}: {e}", exc_info=True)
            return {
                'success': False,
                'events_sent': 0,
                'error': str(e),
                'server_name': server.name
            }
