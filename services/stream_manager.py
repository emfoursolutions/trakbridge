# =============================================================================
# services/stream_manager.py - Enhanced Stream Management Service with COT Integration
# =============================================================================

import asyncio
import aiohttp
import ssl
from typing import Dict, Optional, List
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from models.stream import Stream
from models.tak_server import TakServer
from plugins.plugin_manager import plugin_manager
from services.cot_service import COTService
from database import db


class StreamWorker:
    """Individual stream worker that handles one GPS feed"""

    def __init__(self, stream: Stream):
        self.stream = stream
        self.plugin = None
        self.running = False
        self.task = None
        self.logger = logging.getLogger(f'StreamWorker-{stream.name}')
        self.session = None
        self.tak_connection = None
        self.reader = None
        self.writer = None

    async def start(self):
        """Start the stream worker"""
        if self.running:
            self.logger.warning(f"Stream {self.stream.name} is already running")
            return False

        try:
            # Initialize plugin
            self.plugin = plugin_manager.get_plugin(
                self.stream.plugin_type,
                self.stream.get_plugin_config()
            )

            if not self.plugin:
                self.logger.error("Failed to initialize plugin")
                return False

            # Validate plugin configuration
            if not self.plugin.validate_config():
                self.logger.error("Plugin configuration validation failed")
                return False

            # Create HTTP session for GPS data fetching
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    limit=10,
                    ttl_dns_cache=300,
                    use_dns_cache=True,
                )
            )

            # Initialize TAK server connection if configured
            if self.stream.tak_server:
                success = await self._initialize_tak_connection()
                if not success:
                    self.logger.error("Failed to initialize TAK server connection")
                    await self._cleanup_session()
                    return False

            self.running = True
            self.task = asyncio.create_task(self._run_loop())

            # Update stream status in database
            self.stream.is_active = True
            self.stream.last_poll = datetime.utcnow()
            self.stream.last_error = None
            db.session.commit()

            self.logger.info(f"Stream '{self.stream.name}' started successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start stream '{self.stream.name}': {e}")
            await self._cleanup_session()
            return False

    async def stop(self):
        """Stop the stream worker"""
        if not self.running:
            return

        self.logger.info(f"Stopping stream '{self.stream.name}'")
        self.running = False

        # Cancel the main task
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        # Clean up resources
        await self._cleanup_session()
        await self._cleanup_tak_connection()

        # Update database
        try:
            self.stream.is_active = False
            db.session.commit()
        except Exception as e:
            self.logger.error(f"Failed to update stream status in database: {e}")

        self.logger.info(f"Stream '{self.stream.name}' stopped")

    async def _initialize_tak_connection(self) -> bool:
        """Initialize persistent connection to TAK server"""
        try:
            tak_server = self.stream.tak_server

            # Create SSL context if using TLS
            ssl_context = None
            if tak_server.protocol.lower() in ['tls', 'ssl']:
                ssl_context = ssl.create_default_context()

                # Configure SSL verification
                if not tak_server.verify_ssl:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                # Load client certificates if provided
                if tak_server.cert_pem and tak_server.cert_key:
                    try:
                        ssl_context.load_cert_chain(
                            certfile=tak_server.cert_pem,
                            keyfile=tak_server.cert_key,
                            password=tak_server.client_password
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to load SSL certificates: {e}")
                        return False

            # Establish connection
            if ssl_context:
                self.reader, self.writer = await asyncio.open_connection(
                    tak_server.host,
                    tak_server.port,
                    ssl=ssl_context
                )
            else:
                self.reader, self.writer = await asyncio.open_connection(
                    tak_server.host,
                    tak_server.port
                )

            self.logger.info(f"Connected to TAK server {tak_server.name} at {tak_server.host}:{tak_server.port}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to TAK server: {e}")
            return False

    async def _cleanup_session(self):
        """Clean up HTTP session"""
        if self.session:
            try:
                await self.session.close()
            except Exception as e:
                self.logger.error(f"Error closing HTTP session: {e}")
            finally:
                self.session = None

    async def _cleanup_tak_connection(self):
        """Clean up TAK server connection"""
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception as e:
                self.logger.error(f"Error closing TAK connection: {e}")
            finally:
                self.writer = None
                self.reader = None

    async def _run_loop(self):
        """Main processing loop for the stream"""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self.running:
            try:
                self.logger.info(
                    f"Starting poll cycle for stream '{self.stream.name}' (ID: {self.stream.id}) - Plugin: {self.stream.plugin_type}"
                )

                # Fetch locations from GPS service
                locations = await self.plugin.fetch_locations(self.session)

                if locations:
                    self.logger.info(f"Retrieved {len(locations)} locations from {self.stream.plugin_type} plugin")

                    # Send to TAK server if configured
                    if self.stream.tak_server and self.writer:
                        success = await self._send_locations_to_tak(locations)
                        if success:
                            self.logger.info(f"Successfully sent {len(locations)} locations to TAK server")
                        else:
                            self.logger.error("Failed to send locations to TAK server")
                            # Try to reconnect
                            await self._cleanup_tak_connection()
                            await self._initialize_tak_connection()
                    else:
                        self.logger.warning("No TAK server configured or connection lost")

                    # Update stream status
                    self.stream.last_poll = datetime.utcnow()
                    self.stream.last_error = None
                    consecutive_errors = 0
                    db.session.commit()

                    self.logger.info("Poll cycle completed successfully")
                else:
                    self.logger.warning(f"No locations retrieved from {self.stream.plugin_type} plugin")

                # Wait for next poll
                self.logger.debug(f"Next poll in {self.stream.poll_interval} seconds")
                await asyncio.sleep(self.stream.poll_interval)

            except asyncio.CancelledError:
                self.logger.info("Stream loop cancelled")
                break
            except Exception as e:
                consecutive_errors += 1
                error_msg = f"Error in stream loop (attempt {consecutive_errors}): {e}"
                self.logger.error(error_msg)

                # Update error in database
                self.stream.last_error = str(e)
                db.session.commit()

                # If too many consecutive errors, stop the stream
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.error(f"Too many consecutive errors ({consecutive_errors}), stopping stream")
                    self.running = False
                    break

                # Progressive backoff for retries
                retry_delay = min(60 * consecutive_errors, 300)  # Max 5 minutes
                self.logger.info(f"Waiting {retry_delay} seconds before retry")
                await asyncio.sleep(retry_delay)

    async def _send_locations_to_tak(self, locations: List[Dict]) -> bool:
        """Send locations to TAK server"""
        try:
            # Convert locations to COT events
            cot_events = COTService.create_cot_events(
                locations,
                self.stream.cot_type,
                self.stream.cot_stale_time
            )

            # Send each COT event and count successful sends
            messages_sent = 0
            for cot_event in cot_events:
                try:
                    self.writer.write(cot_event)
                    await self.writer.drain()
                    messages_sent += 1
                    self.logger.debug(f"Sent COT event: {cot_event.decode('utf-8')[:200]}...")
                except Exception as e:
                    self.logger.error(f"Failed to send individual COT event: {e}")
                    # Continue trying to send remaining events

            # Update total_messages_sent in database
            if messages_sent > 0:
                if not hasattr(self.stream, 'total_messages_sent') or self.stream.total_messages_sent is None:
                    self.stream.total_messages_sent = 0

                self.stream.total_messages_sent += messages_sent
                db.session.commit()

                self.logger.info(
                    f"Successfully sent {messages_sent} COT events. Total messages sent: {self.stream.total_messages_sent}")

            return messages_sent > 0

        except Exception as e:
            self.logger.error(f"Failed to send locations to TAK server: {e}")
            return False


class StreamManager:
    """Manages multiple GPS streams"""

    def __init__(self):
        self.workers: Dict[int, StreamWorker] = {}
        self.logger = logging.getLogger('StreamManager')

    async def start_stream(self, stream_id: int) -> bool:
        """Start a specific stream"""
        try:
            stream = Stream.query.get(stream_id)
            if not stream:
                self.logger.error(f"Stream {stream_id} not found")
                return False

            # Check if stream is active
            if not stream.is_active:
                self.logger.warning(f"Stream {stream_id} ({stream.name}) is not active, skipping start")
                return False

            if stream_id in self.workers:
                self.logger.warning(f"Stream {stream_id} already running")
                return True

            # Validate stream configuration
            if not stream.tak_server:
                self.logger.error(f"Stream {stream_id} has no TAK server configured")
                return False

            worker = StreamWorker(stream)
            success = await worker.start()

            if success:
                self.workers[stream_id] = worker
                self.logger.info(f"Successfully started stream {stream_id}")
            else:
                self.logger.error(f"Failed to start stream {stream_id}")

            return success

        except Exception as e:
            self.logger.error(f"Error starting stream {stream_id}: {e}")
            return False

    async def stop_stream(self, stream_id: int) -> bool:
        """Stop a specific stream"""
        try:
            if stream_id not in self.workers:
                self.logger.warning(f"Stream {stream_id} not running")
                return True

            worker = self.workers[stream_id]
            await worker.stop()
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
        return await self.start_stream(stream_id)

    async def stop_all(self):
        """Stop all running streams"""
        self.logger.info("Stopping all running streams")
        tasks = []
        for stream_id in list(self.workers.keys()):
            tasks.append(self.stop_stream(stream_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        self.logger.info("All streams stopped")

    def get_stream_status(self, stream_id: int) -> Dict:
        """Get status of a specific stream"""
        if stream_id in self.workers:
            worker = self.workers[stream_id]
            return {
                'running': worker.running,
                'stream_name': worker.stream.name,
                'plugin_type': worker.stream.plugin_type,
                'last_poll': worker.stream.last_poll,
                'last_error': worker.stream.last_error,
                'tak_server': worker.stream.tak_server.name if worker.stream.tak_server else None
            }
        else:
            return {'running': False}

    def get_all_stream_status(self) -> Dict[int, Dict]:
        """Get status of all streams"""
        status = {}
        for stream_id, worker in self.workers.items():
            status[stream_id] = self.get_stream_status(stream_id)
        return status

    async def health_check(self):
        """Perform health check on all running streams"""
        self.logger.info("Performing health check on all streams")

        unhealthy_streams = []
        for stream_id, worker in self.workers.items():
            if not worker.running or worker.task.done():
                unhealthy_streams.append(stream_id)
                self.logger.warning(f"Stream {stream_id} appears unhealthy")

        # Restart unhealthy streams
        for stream_id in unhealthy_streams:
            self.logger.info(f"Attempting to restart unhealthy stream {stream_id}")
            await self.restart_stream(stream_id)


# Global stream manager instance
stream_manager = StreamManager()