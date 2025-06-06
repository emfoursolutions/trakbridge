# =============================================================================
# standalone_runner.py - Standalone Stream Runner Script
# =============================================================================

# !/usr/bin/env python3
"""
Standalone script to run GPS streams outside of Flask application.
Useful for production deployments where you want streams running
independently of the web interface.
"""

import asyncio
import logging
import signal
import sys
import os
from datetime import datetime

# Add the application directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from models.stream import Stream
from services.stream_manager import StreamManager
from config import Config


class StandaloneRunner:
    """Standalone runner for GPS streams"""

    def __init__(self):
        self.app = create_app()
        self.stream_manager = StreamManager()
        self.running = False
        self.setup_logging()

    def setup_logging(self):
        """Setup logging configuration"""
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        logging.basicConfig(
            level=getattr(logging, Config.LOG_LEVEL.upper()),
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(log_dir, 'standalone_runner.log')),
                logging.StreamHandler()
            ]
        )

        self.logger = logging.getLogger('StandaloneRunner')

    async def start_all_active_streams(self):
        """Start all streams marked as active in the database"""
        with self.app.app_context():
            streams = Stream.query.filter_by(is_active=True).all()

            self.logger.info(f"Found {len(streams)} active streams to start")

            for stream in streams:
                try:
                    success = await self.stream_manager.start_stream(stream.id)
                    if success:
                        self.logger.info(f"Started stream: {stream.name}")
                    else:
                        self.logger.error(f"Failed to start stream: {stream.name}")
                except Exception as e:
                    self.logger.error(f"Error starting stream {stream.name}: {e}")

    async def run(self):
        """Main run loop"""
        self.running = True
        self.logger.info("Starting standalone GPS stream runner")

        # Start all active streams
        await self.start_all_active_streams()

        # Keep running until shutdown
        try:
            while self.running:
                await asyncio.sleep(60)  # Check every minute

                # Optionally implement health checks here
                with self.app.app_context():
                    active_count = len(self.stream_manager.workers)
                    self.logger.debug(f"Running {active_count} streams")

        except asyncio.CancelledError:
            self.logger.info("Received shutdown signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """Shutdown all streams gracefully"""
        self.logger.info("Shutting down all streams...")
        self.running = False
        await self.stream_manager.stop_all()
        self.logger.info("Shutdown complete")

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}")
        self.running = False


def main():
    """Main entry point"""
    runner = StandaloneRunner()

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, runner.signal_handler)
    signal.signal(signal.SIGTERM, runner.signal_handler)

    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        runner.logger.info("Received keyboard interrupt")
    except Exception as e:
        runner.logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()