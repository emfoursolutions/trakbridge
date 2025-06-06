# =============================================================================
# services/stream_manager.py - Stream Management Service
# =============================================================================

import asyncio
import aiohttp
import pytak
from configparser import ConfigParser
from typing import Dict, Optional
import logging
from datetime import datetime

from models.stream import Stream
from models.tak_server import TakServer
from plugins.plugin_manager import plugin_manager
from services.cot_service import COTService


class StreamWorker:
    """Individual stream worker that handles one GPS feed"""

    def __init__(self, stream: Stream):
        self.stream = stream
        self.plugin = None
        self.pytak_client = None
        self.running = False
        self.task = None
        self.logger = logging.getLogger(f'StreamWorker-{stream.name}')

    async def start(self):
        """Start the stream worker"""
        if self.running:
            return False

        # Initialize plugin
        self.plugin = plugin_manager.get_plugin(
            self.stream.plugin_type,
            self.stream.get_plugin_config()
        )

        if not self.plugin:
            self.logger.error("Failed to initialize plugin")
            return False

        # Initialize PyTAK client
        try:
            pytak_config = ConfigParser()
            pytak_config['stream'] = self.stream.tak_server.get_pytak_config()

            self.pytak_client = pytak.CLITool(pytak_config['stream'])
            await self.pytak_client.setup()

            self.running = True
            self.task = asyncio.create_task(self._run_loop())
            self.logger.info(f"Stream {self.stream.name} started")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start stream: {e}")
            return False

    async def stop(self):
        """Stop the stream worker"""
        if not self.running:
            return

        self.running = False

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        if self.pytak_client:
            # Clean up PyTAK client
            try:
                await self.pytak_client.cleanup()
            except:
                pass

        self.logger.info(f"Stream {self.stream.name} stopped")

    async def _run_loop(self):
        """Main processing loop for the stream"""
        while self.running:
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    # Fetch locations from GPS service
                    locations = await self.plugin.fetch_locations(session)

                    if locations:
                        # Convert to COT events
                        cot_events = COTService.create_cot_events(
                            locations,
                            self.stream.cot_type,
                            self.stream.cot_stale_time
                        )

                        # Send COT events to TAK server
                        for event in cot_events:
                            await self.pytak_client.tx_queue.put(event)
                            self.logger.debug(f"Sent COT event for {locations[0]['name']}")

                        # Update last poll time
                        self.stream.last_poll = datetime.utcnow()
                        self.stream.last_error = None

                    await asyncio.sleep(self.stream.poll_interval)

            except Exception as e:
                self.logger.error(f"Error in stream loop: {e}")
                self.stream.last_error = str(e)
                await asyncio.sleep(60)  # Wait before retry


class StreamManager:
    """Manages multiple GPS streams"""

    def __init__(self):
        self.workers: Dict[int, StreamWorker] = {}
        self.logger = logging.getLogger('StreamManager')

    async def start_stream(self, stream_id: int) -> bool:
        """Start a specific stream"""
        from app import db

        stream = Stream.query.get(stream_id)
        if not stream:
            self.logger.error(f"Stream {stream_id} not found")
            return False

        if stream_id in self.workers:
            self.logger.warning(f"Stream {stream_id} already running")
            return True

        worker = StreamWorker(stream)
        success = await worker.start()

        if success:
            self.workers[stream_id] = worker
            stream.is_active = True
            db.session.commit()

        return success

    async def stop_stream(self, stream_id: int) -> bool:
        """Stop a specific stream"""
        from app import db

        if stream_id not in self.workers:
            self.logger.warning(f"Stream {stream_id} not running")
            return True

        worker = self.workers[stream_id]
        await worker.stop()
        del self.workers[stream_id]

        stream = Stream.query.get(stream_id)
        if stream:
            stream.is_active = False
            db.session.commit()

        return True

    async def restart_stream(self, stream_id: int) -> bool:
        """Restart a specific stream"""
        await self.stop_stream(stream_id)
        return await self.start_stream(stream_id)

    async def stop_all(self):
        """Stop all running streams"""
        for stream_id in list(self.workers.keys()):
            await self.stop_stream(stream_id)


# Global stream manager instance
stream_manager = StreamManager()