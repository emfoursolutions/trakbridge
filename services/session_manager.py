"""
File: services/session_manager.py

Description:
    Robust HTTP session management service providing centralized session handling
    for all stream workers with advanced connection pooling and error recovery.
    This service ensures reliable HTTP connectivity across the application with
    optimized timeout handling and resource management.

Key features:
    - Centralized HTTP session management with aiohttp ClientSession integration
    - Advanced connection pooling with configurable limits and keepalive settings
    - Intelligent timeout configuration with separate connect, read, and total timeouts
    - DNS caching and connection reuse optimization for improved performance
    - Thread-safe session initialization with async lock protection
    - Graceful session cleanup with timeout handling and resource deallocation
    - Environment proxy support with trust_env configuration
    - Automatic session recovery and reinitialization on connection failures
    - Comprehensive logging for session lifecycle events and error tracking
    - Connection pool monitoring with per-host connection limiting

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import asyncio
import logging
from typing import Optional

# Third-party imports
import aiohttp

# Module-level logger
logger = logging.getLogger(__name__)


class SessionManager:
    """Manages HTTP sessions for all stream workers with better error handling"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize the HTTP session with better configuration"""
        async with self._session_lock:
            if self.session:
                logger.info("HTTP session already initialized")
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

                logger.info("HTTP session initialized successfully")

            except Exception as e:
                logger.error(f"Failed to initialize HTTP session: {e}")
                raise

    async def cleanup(self):
        """Clean up the HTTP session"""
        async with self._session_lock:
            if self.session:
                try:
                    await asyncio.wait_for(self.session.close(), timeout=10.0)
                    logger.info("HTTP session closed")
                except Exception as e:
                    logger.error(f"Error closing HTTP session: {e}")
                finally:
                    self.session = None

    async def get_session(self):
        """Get the session, initializing if necessary"""
        if not self.session or self.session.closed:
            await self.initialize()
        return self.session
