# =============================================================================
# services/session_manager.py - Session Manager Service
# Manages the HTTP sessions for all Stream Workers
# =============================================================================

import asyncio
import aiohttp
import logging
from typing import Optional


class SessionManager:
    """Manages HTTP sessions for all stream workers with better error handling"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
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
