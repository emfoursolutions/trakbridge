"""
ABOUTME: Central authentication manager orchestrating multiple auth providers
ABOUTME: Handles provider fallback chain and session management for TrakBridge

File: services/auth/auth_manager.py

Description:
    Central authentication manager that orchestrates multiple authentication providers
    (Local, LDAP, OIDC) with intelligent fallback capabilities. Manages the authentication
    flow, provider priority ordering, session handling, and provides unified authentication
    interface for the entire application. Includes comprehensive logging, health monitoring,
    and configuration management.

Key features:
    - Multi-provider authentication with configurable fallback chain
    - Intelligent provider selection based on priority and health status
    - Comprehensive session management across all providers
    - Real-time provider health monitoring and automatic failover
    - User management with cross-provider user tracking
    - Audit logging for all authentication events
    - Configuration validation and hot-reloading support
    - Security controls including rate limiting and brute force protection
    - Administrative functions for user and session management

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Standard library imports
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from threading import Lock
import time

# Third-party imports
from flask import current_app, request

# Local application imports
from models.user import User, UserSession, AuthProvider, UserRole, AccountStatus
from .base_provider import (
    BaseAuthenticationProvider,
    AuthenticationResult,
    AuthenticationResponse,
    AuthenticationException,
)


# Module-level logger
logger = logging.getLogger(__name__)


class AuthenticationManager:
    """
    Central authentication manager handling multiple providers
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.providers: Dict[AuthProvider, BaseAuthenticationProvider] = {}
        self.provider_order: List[AuthProvider] = []
        self._lock = Lock()
        self._health_cache = {}
        self._health_cache_ttl = 300  # 5 minutes
        self._last_health_check = {}

        # Load security settings from config (handle both old and new format)
        if "authentication" in self.config:
            # Old format: authentication.session.*
            auth_config = self.config.get("authentication", {})
            session_config = auth_config.get("session", {})
            self.max_login_attempts = session_config.get("max_login_attempts", 5)
            self.lockout_duration = session_config.get("lockout_duration_minutes", 30)
            self.session_timeout = session_config.get("lifetime_hours", 8)
            self.cleanup_interval = (
                session_config.get("cleanup_interval_minutes", 60) / 60
            )  # Convert to hours
        else:
            # New format: default.security.*
            security_config = self.config.get("default", {}).get("security", {})
            self.max_login_attempts = security_config.get("max_login_attempts", 5)
            self.lockout_duration = security_config.get("lockout_duration_minutes", 30)
            self.session_timeout = security_config.get("session_timeout_hours", 8)
            self.cleanup_interval = security_config.get("cleanup_interval_hours", 24)

        # Rate limiting
        self._login_attempts = {}
        self._attempt_cleanup_interval = 3600  # 1 hour
        self._last_attempt_cleanup = time.time()

        # Initialize providers based on configuration
        self._initialize_providers()

        logger.info("Authentication manager initialized with configuration")

    def _initialize_providers(self) -> None:
        """Initialize authentication providers based on configuration"""
        try:
            from .local_provider import LocalAuthProvider
            from .ldap_provider import LDAPAuthProvider
            from .oidc_provider import OIDCAuthProvider

            # Handle both old nested and new flat configuration formats
            logger.debug(f"Config keys: {list(self.config.keys())}")

            if "authentication" in self.config:
                # Old nested format: authentication.providers.*
                auth_config = self.config.get("authentication", {})
                providers_config = auth_config.get("providers", {})
                provider_priority = auth_config.get(
                    "provider_priority", ["local", "ldap", "oidc"]
                )
            elif "providers" in self.config:
                # New flat format: providers.*, provider_priority.*
                providers_config = self.config.get("providers", {})
                provider_priority = self.config.get(
                    "provider_priority", ["local", "ldap", "oidc"]
                )
            else:
                # Legacy format: default.providers.*
                providers_config = self.config.get("default", {}).get("providers", {})
                provider_priority = ["local", "ldap", "oidc"]

            logger.debug(f"Providers config: {providers_config}")
            logger.debug(f"Provider priority: {provider_priority}")

            # Convert provider config to list format for processing
            provider_list = []

            for i, provider_type in enumerate(provider_priority):
                if provider_type in providers_config:
                    provider_data = providers_config[provider_type]
                    enabled = provider_data.get("enabled", False)

                    # Create a copy of provider_data for the config, excluding 'enabled'
                    config_data = {
                        k: v for k, v in provider_data.items() if k != "enabled"
                    }

                    provider_list.append(
                        {
                            "type": provider_type,
                            "priority": i + 1,
                            "enabled": enabled,
                            "config": config_data,
                        }
                    )

            # Sort providers by priority
            provider_list.sort(key=lambda p: p.get("priority", 999))
            logger.info(f"Provider list to process: {provider_list}")

            for provider_config in provider_list:
                provider_type = provider_config.get("type", "").lower()
                enabled = provider_config.get("enabled", False)

                if not enabled:
                    logger.debug(f"Skipping disabled provider: {provider_type}")
                    continue

                try:
                    # Initialize provider based on type
                    logger.info(
                        f"Initializing {provider_type} provider with config: {provider_config.get('config', {})}"
                    )
                    if provider_type == "local":
                        provider = LocalAuthProvider(provider_config.get("config", {}))
                        self.register_provider(provider)
                        logger.info(f"Successfully registered LocalAuthProvider")
                    elif provider_type == "ldap":
                        provider = LDAPAuthProvider(provider_config.get("config", {}))
                        self.register_provider(provider)
                        logger.info(f"Successfully registered LDAPAuthProvider")
                    elif provider_type == "oidc":
                        provider = OIDCAuthProvider(provider_config.get("config", {}))
                        self.register_provider(provider)
                        logger.info(f"Successfully registered OIDCAuthProvider")
                    else:
                        logger.warning(f"Unknown provider type: {provider_type}")

                except Exception as e:
                    logger.error(f"Failed to initialize {provider_type} provider: {e}")
                    import traceback

                    logger.error(traceback.format_exc())

            # If no providers were configured, enable local provider as fallback
            if not self.providers:
                logger.warning(
                    "No authentication providers configured, enabling local provider as fallback"
                )
                fallback_provider = LocalAuthProvider({"enabled": True})
                self.register_provider(fallback_provider)

        except Exception as e:
            logger.error(f"Failed to initialize authentication providers: {e}")
            # Create minimal local provider for emergency access
            try:
                from .local_provider import LocalAuthProvider

                emergency_provider = LocalAuthProvider({"enabled": True})
                self.register_provider(emergency_provider)
                logger.info("Emergency local authentication provider created")
            except Exception as emergency_error:
                logger.critical(
                    f"Failed to create emergency authentication provider: {emergency_error}"
                )

    def register_provider(self, provider: BaseAuthenticationProvider) -> None:
        """
        Register an authentication provider

        Args:
            provider: Authentication provider to register
        """
        with self._lock:
            self.providers[provider.provider_type] = provider
            self._update_provider_order()

        logger.info(
            f"Registered authentication provider: {provider.provider_type.value}"
        )

    def unregister_provider(self, provider_type: AuthProvider) -> None:
        """
        Unregister an authentication provider

        Args:
            provider_type: Provider type to unregister
        """
        with self._lock:
            if provider_type in self.providers:
                del self.providers[provider_type]
                self._update_provider_order()

        logger.info(f"Unregistered authentication provider: {provider_type.value}")

    def _update_provider_order(self) -> None:
        """Update provider order based on priority"""
        # Sort providers by priority (lower number = higher priority)
        sorted_providers = sorted(
            self.providers.items(), key=lambda x: (x[1].priority, x[0].value)
        )

        self.provider_order = [provider_type for provider_type, _ in sorted_providers]

        logger.debug(
            f"Updated provider order: {[p.value for p in self.provider_order]}"
        )

    def authenticate(
        self,
        username: str,
        password: str = None,
        provider_hint: AuthProvider = None,
        **kwargs,
    ) -> AuthenticationResponse:
        """
        Authenticate a user using the provider chain

        Args:
            username: Username to authenticate
            password: Password (may be None for external providers)
            provider_hint: Preferred provider to try first
            **kwargs: Additional authentication parameters

        Returns:
            AuthenticationResponse with result and user information
        """
        # Clean up old login attempts
        self._cleanup_login_attempts()

        # Check rate limiting
        client_ip = self._get_client_ip()
        if self._is_rate_limited(username, client_ip):
            return AuthenticationResponse(
                result=AuthenticationResult.USER_LOCKED,
                message="Too many failed login attempts. Please try again later.",
                details={"lockout_duration": self.lockout_duration},
            )

        # Determine provider order
        providers_to_try = self._get_provider_order(provider_hint)

        last_error = None
        attempted_providers = []

        for provider_type in providers_to_try:
            provider = self.providers.get(provider_type)

            if not provider or not provider.enabled:
                continue

            # Check provider health
            if not self._is_provider_healthy(provider_type):
                # Get detailed health information for logging
                try:
                    health_details = provider.health_check()
                    error_info = health_details.get(
                        "error", "No error details available"
                    )
                    logger.warning(
                        f"Skipping unhealthy provider: {provider_type.value}"
                    )
                    logger.warning(f"Provider health check failed: {error_info}")
                except Exception as health_error:
                    logger.warning(
                        f"Skipping unhealthy provider: {provider_type.value}"
                    )
                    logger.error(f"Failed to get health details: {health_error}")
                continue

            attempted_providers.append(provider_type.value)

            try:
                logger.info(
                    f"Attempting authentication with {provider_type.value} for user: {username}"
                )

                response = provider.authenticate(username, password, **kwargs)

                if response.success:
                    # Reset login attempts on successful authentication
                    self._reset_login_attempts(username, client_ip)

                    # Update user's last login
                    if response.user:
                        response.user.reset_failed_login()

                    # Log successful authentication
                    self._log_authentication_event(
                        username,
                        provider_type,
                        True,
                        f"Successful authentication with {provider_type.value}",
                    )

                    logger.info(
                        f"Successful authentication for {username} using {provider_type.value}"
                    )
                    return response

                # Handle specific authentication failures
                if response.result in [
                    AuthenticationResult.INVALID_CREDENTIALS,
                    AuthenticationResult.USER_NOT_FOUND,
                ]:
                    last_error = response
                    continue  # Try next provider

                # For other errors (locked, disabled, etc.), return immediately
                logger.warning(
                    f"Authentication failed for {username} with {provider_type.value}: {response.message}"
                )
                return response

            except AuthenticationException as e:
                logger.error(
                    f"Authentication error with {provider_type.value} for {username}: {e}"
                )
                last_error = AuthenticationResponse(
                    result=e.result, message=str(e), details=e.details
                )
                continue

            except Exception as e:
                logger.error(
                    f"Unexpected error with {provider_type.value} for {username}: {e}",
                    exc_info=True,
                )
                last_error = AuthenticationResponse(
                    result=AuthenticationResult.PROVIDER_ERROR,
                    message=f"Provider error: {str(e)}",
                    details={"provider": provider_type.value, "error": str(e)},
                )
                continue

        # All providers failed
        self._record_failed_attempt(username, client_ip)

        # Update user's failed login count if user exists
        user = User.query.filter_by(username=username).first()
        if user:
            user.increment_failed_login(self.max_login_attempts)
            try:
                from database import db

                db.session.commit()
            except Exception as e:
                logger.error(f"Failed to update user failed login count: {e}")

        # Log failed authentication
        self._log_authentication_event(
            username,
            None,
            False,
            f"Authentication failed after trying providers: {attempted_providers}",
        )

        failure_response = last_error or AuthenticationResponse(
            result=AuthenticationResult.INVALID_CREDENTIALS,
            message="Authentication failed",
            details={"attempted_providers": attempted_providers},
        )

        logger.warning(
            f"Authentication failed for {username} after trying providers: {attempted_providers}"
        )
        return failure_response

    def get_user_by_session(self, session_id: str) -> Optional[User]:
        """
        Get user by session ID

        Args:
            session_id: Session ID to look up

        Returns:
            User if session is valid, None otherwise
        """
        session = UserSession.query.filter_by(session_id=session_id).first()

        if session and session.is_valid():
            session.update_activity()
            try:
                from database import db

                db.session.commit()
            except Exception as e:
                logger.warning(f"Failed to update session activity: {e}")

            return session.user

        return None

    def create_session(
        self,
        user: User,
        provider_type: AuthProvider = None,
        request_info: Dict[str, Any] = None,
    ) -> UserSession:
        """
        Create a new user session

        Args:
            user: User to create session for
            provider_type: Provider that authenticated the user
            request_info: Request information

        Returns:
            UserSession instance
        """
        provider = self.providers.get(provider_type or user.auth_provider)

        if provider:
            return provider.create_session(user, request_info)
        else:
            # Fallback session creation
            from database import db

            session = UserSession.create_session(
                user=user,
                provider=provider_type or user.auth_provider,
                expires_in_hours=self.session_timeout,
                ip_address=request_info.get("ip_address") if request_info else None,
                user_agent=request_info.get("user_agent") if request_info else None,
            )

            db.session.add(session)
            db.session.commit()

            return session

    def invalidate_session(self, session_id: str) -> bool:
        """
        Invalidate a user session

        Args:
            session_id: Session ID to invalidate

        Returns:
            True if session was invalidated
        """
        from database import db

        session = UserSession.query.filter_by(session_id=session_id).first()

        if session:
            # Try provider-specific invalidation first
            provider = self.providers.get(session.user.auth_provider)
            if provider:
                return provider.invalidate_session(session_id)
            else:
                # Fallback invalidation
                session.invalidate()
                try:
                    db.session.commit()
                    return True
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Failed to invalidate session: {e}")

        return False

    def invalidate_all_user_sessions(self, user_id: int) -> int:
        """
        Invalidate all sessions for a user

        Args:
            user_id: User ID

        Returns:
            Number of sessions invalidated
        """
        from database import db

        sessions = UserSession.query.filter_by(user_id=user_id, is_active=True).all()

        count = 0
        for session in sessions:
            session.invalidate()
            count += 1

        try:
            db.session.commit()
            logger.info(f"Invalidated {count} sessions for user {user_id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to invalidate user sessions: {e}")
            count = 0

        return count

    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions across all providers

        Returns:
            Total number of sessions cleaned up
        """
        total_cleaned = 0

        for provider in self.providers.values():
            try:
                cleaned = provider.cleanup_expired_sessions()
                total_cleaned += cleaned
            except Exception as e:
                logger.error(
                    f"Failed to cleanup sessions for {provider.provider_type.value}: {e}"
                )

        logger.info(f"Cleaned up {total_cleaned} expired sessions")
        return total_cleaned

    def get_provider_health(self, provider_type: AuthProvider = None) -> Dict[str, Any]:
        """
        Get health status for providers

        Args:
            provider_type: Specific provider to check (None for all)

        Returns:
            Dictionary with health information
        """
        if provider_type:
            provider = self.providers.get(provider_type)
            if provider:
                return {provider_type.value: self._check_provider_health(provider)}
            else:
                return {provider_type.value: {"status": "not_registered"}}
        else:
            health_status = {}
            for ptype, provider in self.providers.items():
                health_status[ptype.value] = self._check_provider_health(provider)
            return health_status

    def get_authentication_stats(self) -> Dict[str, Any]:
        """
        Get authentication statistics

        Returns:
            Dictionary with authentication statistics
        """
        from database import db

        stats = {
            "total_users": User.query.count(),
            "active_sessions": UserSession.query.filter_by(is_active=True).count(),
            "users_by_provider": {},
            "sessions_by_provider": {},
            "registered_providers": len(self.providers),
            "enabled_providers": len([p for p in self.providers.values() if p.enabled]),
        }

        # Users by provider
        for provider_type in AuthProvider:
            count = User.query.filter_by(auth_provider=provider_type).count()
            stats["users_by_provider"][provider_type.value] = count

        # Active sessions by provider
        for provider_type in AuthProvider:
            count = (
                db.session.query(UserSession)
                .join(User)
                .filter(
                    User.auth_provider == provider_type, UserSession.is_active == True
                )
                .count()
            )
            stats["sessions_by_provider"][provider_type.value] = count

        return stats

    def _get_provider_order(
        self, provider_hint: AuthProvider = None
    ) -> List[AuthProvider]:
        """Get ordered list of providers to try"""
        if provider_hint and provider_hint in self.providers:
            # Try hinted provider first, then others
            providers = [provider_hint]
            providers.extend([p for p in self.provider_order if p != provider_hint])
            return providers
        else:
            return self.provider_order.copy()

    def _is_provider_healthy(self, provider_type: AuthProvider) -> bool:
        """Check if provider is healthy (with caching)"""
        now = time.time()

        # Check cache
        if (
            provider_type in self._health_cache
            and provider_type in self._last_health_check
            and now - self._last_health_check[provider_type] < self._health_cache_ttl
        ):
            return self._health_cache[provider_type]

        # Perform health check
        provider = self.providers.get(provider_type)
        if not provider:
            return False

        try:
            health = provider.health_check()
            healthy = health.get("status") == "healthy"
        except Exception as e:
            logger.warning(f"Health check failed for {provider_type.value}: {e}")
            healthy = False

        # Update cache
        self._health_cache[provider_type] = healthy
        self._last_health_check[provider_type] = now

        return healthy

    def _check_provider_health(
        self, provider: BaseAuthenticationProvider
    ) -> Dict[str, Any]:
        """Perform detailed health check for a provider"""
        try:
            return provider.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def _get_client_ip(self) -> str:
        """Get client IP address from request"""
        try:
            if request:
                return request.environ.get("HTTP_X_FORWARDED_FOR", request.remote_addr)
        except RuntimeError:
            pass
        return "unknown"

    def _is_rate_limited(self, username: str, ip_address: str) -> bool:
        """Check if user/IP is rate limited"""
        now = time.time()

        # Check username-based limiting
        user_key = f"user:{username}"
        if user_key in self._login_attempts:
            attempts, last_attempt = self._login_attempts[user_key]
            if attempts >= self.max_login_attempts:
                if now - last_attempt < (self.lockout_duration * 60):
                    return True

        # Check IP-based limiting (more lenient)
        ip_key = f"ip:{ip_address}"
        if ip_key in self._login_attempts:
            attempts, last_attempt = self._login_attempts[ip_key]
            if attempts >= (self.max_login_attempts * 3):  # 3x more lenient for IPs
                if now - last_attempt < (self.lockout_duration * 60):
                    return True

        return False

    def _record_failed_attempt(self, username: str, ip_address: str) -> None:
        """Record a failed login attempt"""
        now = time.time()

        # Record for username
        user_key = f"user:{username}"
        if user_key in self._login_attempts:
            attempts, _ = self._login_attempts[user_key]
            self._login_attempts[user_key] = (attempts + 1, now)
        else:
            self._login_attempts[user_key] = (1, now)

        # Record for IP
        ip_key = f"ip:{ip_address}"
        if ip_key in self._login_attempts:
            attempts, _ = self._login_attempts[ip_key]
            self._login_attempts[ip_key] = (attempts + 1, now)
        else:
            self._login_attempts[ip_key] = (1, now)

    def _reset_login_attempts(self, username: str, ip_address: str) -> None:
        """Reset login attempts after successful authentication"""
        user_key = f"user:{username}"
        ip_key = f"ip:{ip_address}"

        self._login_attempts.pop(user_key, None)
        self._login_attempts.pop(ip_key, None)

    def _cleanup_login_attempts(self) -> None:
        """Clean up old login attempt records"""
        now = time.time()

        if now - self._last_attempt_cleanup < self._attempt_cleanup_interval:
            return

        cutoff = now - (self.lockout_duration * 60 * 2)  # 2x lockout duration

        keys_to_remove = []
        for key, (attempts, last_attempt) in self._login_attempts.items():
            if last_attempt < cutoff:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._login_attempts[key]

        self._last_attempt_cleanup = now

        if keys_to_remove:
            logger.debug(f"Cleaned up {len(keys_to_remove)} old login attempt records")

    def _log_authentication_event(
        self,
        username: str,
        provider_type: AuthProvider = None,
        success: bool = False,
        message: str = None,
    ) -> None:
        """Log authentication events for audit purposes"""
        level = logging.INFO if success else logging.WARNING

        event_data = {
            "event": "authentication",
            "username": username,
            "provider": provider_type.value if provider_type else None,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
            "ip_address": self._get_client_ip(),
        }

        if message:
            event_data["message"] = message

        # Log with structured data
        logger.log(level, f"Authentication event: {event_data}")

    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about all registered providers"""
        info = {}

        for provider_type, provider in self.providers.items():
            info[provider_type.value] = provider.get_provider_info()

        return info

    def reload_configuration(self, new_config: Dict[str, Any]) -> None:
        """
        Reload authentication manager configuration

        Args:
            new_config: New configuration dictionary
        """
        self.config.update(new_config)

        # Update security settings
        self.max_login_attempts = self.config.get("max_login_attempts", 5)
        self.lockout_duration = self.config.get("lockout_duration_minutes", 30)
        self.session_timeout = self.config.get("session_timeout_hours", 24)

        # Clear health cache to force refresh
        self._health_cache.clear()
        self._last_health_check.clear()

        logger.info("Authentication manager configuration reloaded")

    def __str__(self) -> str:
        return f"AuthenticationManager(providers={len(self.providers)})"

    def __repr__(self) -> str:
        provider_types = [p.value for p in self.providers.keys()]
        return f"AuthenticationManager(providers={provider_types})"
