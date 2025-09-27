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

Author: Emfour Solutions
Created: 18-Jul-2025
"""

# Standard library imports
import asyncio
from typing import Optional
from datetime import datetime

# Third-party imports
import aiohttp
import aiocache

# Local imports
from services.logging_service import get_module_logger

# Module-level logger
logger = get_module_logger(__name__)


class SessionManager:
    """Manages HTTP sessions with enhanced connection pooling and caching"""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._response_cache = aiocache.Cache(aiocache.SimpleMemoryCache)
        self._last_activity = datetime.now()
        self._connection_stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "active_connections": 0,
        }

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
                    sock_read=30,  # Increased read timeout
                )

                connector = aiohttp.TCPConnector(
                    limit=100,  # Increased total connection pool size
                    ttl_dns_cache=600,  # Longer DNS cache TTL (10 min)
                    use_dns_cache=True,
                    keepalive_timeout=120,  # Longer keepalive connections
                    enable_cleanup_closed=True,
                    limit_per_host=20,  # Increased per-host limit
                )

                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    trust_env=True,  # Use environment proxy settings
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

    async def cached_get(self, url: str, ttl: int = 300, **kwargs):
        """Perform a GET request with intelligent caching"""
        cache_key = f"http_get:{url}:{hash(str(sorted(kwargs.items())))}"

        # Try to get from cache first
        cached_response = await self._response_cache.get(cache_key)
        if cached_response is not None:
            self._connection_stats["cache_hits"] += 1
            logger.debug(f"Cache hit for {url}")
            return cached_response

        # Cache miss - make the actual request
        self._connection_stats["cache_misses"] += 1
        self._connection_stats["total_requests"] += 1

        session = await self.get_session()
        try:
            async with session.get(url, **kwargs) as response:
                response_data = {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "text": await response.text(),
                    "url": str(response.url),
                }

                # Cache successful responses
                if response.status == 200:
                    await self._response_cache.set(cache_key, response_data, ttl=ttl)
                    logger.debug(f"Cached response for {url} (TTL: {ttl}s)")

                self._last_activity = datetime.now()
                return response_data

        except Exception as e:
            logger.error(f"HTTP GET request failed for {url}: {e}")
            raise

    async def cached_post(self, url: str, ttl: int = 60, **kwargs):
        """Perform a POST request with short-term caching"""
        # Only cache POST for a short time and only for identical payloads
        cache_key = f"http_post:{url}:{hash(str(sorted(kwargs.items())))}"

        cached_response = await self._response_cache.get(cache_key)
        if cached_response is not None:
            self._connection_stats["cache_hits"] += 1
            logger.debug(f"Cache hit for POST {url}")
            return cached_response

        self._connection_stats["cache_misses"] += 1
        self._connection_stats["total_requests"] += 1

        session = await self.get_session()
        try:
            async with session.post(url, **kwargs) as response:
                response_data = {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "text": await response.text(),
                    "url": str(response.url),
                }

                # Cache successful POST responses for a short time
                if response.status in [200, 201]:
                    await self._response_cache.set(cache_key, response_data, ttl=ttl)
                    logger.debug(f"Cached POST response for {url} (TTL: {ttl}s)")

                self._last_activity = datetime.now()
                return response_data

        except Exception as e:
            logger.error(f"HTTP POST request failed for {url}: {e}")
            raise

    def get_connection_stats(self):
        """Get connection and caching statistics"""
        cache_hit_ratio = 0
        if self._connection_stats["total_requests"] > 0:
            total_requests = (
                self._connection_stats["cache_hits"]
                + self._connection_stats["cache_misses"]
            )
            cache_hit_ratio = self._connection_stats["cache_hits"] / total_requests

        return {
            **self._connection_stats,
            "cache_hit_ratio": cache_hit_ratio,
            "last_activity": self._last_activity.isoformat(),
            "session_active": (self.session is not None and not self.session.closed),
        }

    async def clear_cache(self):
        """Clear the response cache"""
        await self._response_cache.clear()
        logger.info("HTTP response cache cleared")
