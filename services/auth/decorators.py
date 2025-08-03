"""
ABOUTME: Authentication decorators for protecting Flask routes with role-based access
ABOUTME: Provides @require_auth and @require_role decorators for TrakBridge routes

File: services/auth/decorators.py

Description:
    Authentication and authorization decorators for protecting Flask routes in TrakBridge.
    Provides flexible decorators for requiring authentication, specific roles, and custom
    permission checks. Integrates with the authentication manager to validate sessions
    and enforce access controls across the entire application.

Key features:
    - @require_auth decorator for basic authentication requirement
    - @require_role decorator for role-based access control
    - @require_permission decorator for fine-grained permission checking
    - @admin_required decorator for administrative functions
    - Session validation and automatic renewal
    - Comprehensive error handling with proper HTTP status codes
    - JSON API and HTML request support
    - Audit logging for access attempts
    - Integration with Flask session management

Author: Emfour Solutions
Created: 2025-07-26
Last Modified: 2025-07-26
Version: 1.0.0
"""

# Standard library imports
import logging
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

# Third-party imports
from flask import current_app, g, jsonify, redirect, request, session, url_for

# Local application imports
from models.user import User, UserRole

from .auth_manager import AuthenticationManager

# Module-level logger
logger = logging.getLogger(__name__)


def get_auth_manager() -> AuthenticationManager:
    """Get the authentication manager instance"""
    if hasattr(current_app, "auth_manager"):
        return current_app.auth_manager
    else:
        # Fallback - this should not happen in normal operation
        logger.warning("Authentication manager not found in app context")
        return None


def get_current_user() -> Optional[User]:
    """
    Get the currently authenticated user

    Returns:
        User instance if authenticated, None otherwise
    """
    # Check if user is already cached in request context
    if hasattr(g, "current_user"):
        return g.current_user

    # Check session for authentication
    session_id = session.get("session_id")
    if not session_id:
        g.current_user = None
        return None

    # Get authentication manager
    auth_manager = get_auth_manager()
    if not auth_manager:
        g.current_user = None
        return None

    # Validate session and get user
    user = auth_manager.get_user_by_session(session_id)

    # Cache user in request context
    g.current_user = user

    return user


def is_authenticated() -> bool:
    """
    Check if current request is authenticated

    Returns:
        True if user is authenticated
    """
    return get_current_user() is not None


def require_auth(f: Callable) -> Callable:
    """
    Decorator to require authentication for a route

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()

        if not user:
            # Log unauthenticated access attempt
            logger.warning(
                f"Unauthenticated access attempt to {request.endpoint} from {request.remote_addr}"
            )

            if request.is_json or request.content_type == "application/json":
                return (
                    jsonify(
                        {
                            "error": "Authentication required",
                            "message": "You must be logged in to access this resource",
                            "status": 401,
                        }
                    ),
                    401,
                )
            else:
                # Redirect to login page for HTML requests
                session["next_url"] = request.url
                return redirect(url_for("auth.login"))

        # User is authenticated, proceed with request
        return f(*args, **kwargs)

    return decorated_function


def require_role(
    required_role: Union[UserRole, str, List[Union[UserRole, str]]]
) -> Callable:
    """
    Decorator to require specific role(s) for a route

    Args:
        required_role: Required role(s) - can be single role or list of roles

    Returns:
        Decorator function
    """

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()

            if not user:
                logger.warning(
                    f"Unauthenticated access attempt to {request.endpoint} from {request.remote_addr}"
                )

                if request.is_json or request.content_type == "application/json":
                    return (
                        jsonify(
                            {
                                "error": "Authentication required",
                                "message": "You must be logged in to access this resource",
                                "status": 401,
                            }
                        ),
                        401,
                    )
                else:
                    session["next_url"] = request.url
                    return redirect(url_for("auth.login"))

            # Normalize required roles to list
            if isinstance(required_role, (str, UserRole)):
                required_roles = [required_role]
            else:
                required_roles = required_role

            # Convert string roles to UserRole enum
            normalized_roles = []
            for role in required_roles:
                if isinstance(role, str):
                    try:
                        normalized_roles.append(UserRole(role))
                    except ValueError:
                        logger.error(f"Invalid role specified in decorator: {role}")
                        if (
                            request.is_json
                            or request.content_type == "application/json"
                        ):
                            return (
                                jsonify(
                                    {
                                        "error": "Configuration error",
                                        "message": "Invalid role configuration",
                                        "status": 500,
                                    }
                                ),
                                500,
                            )
                        else:
                            return "Configuration error", 500
                else:
                    normalized_roles.append(role)

            # Check if user has any of the required roles
            has_permission = any(user.has_role(role) for role in normalized_roles)

            if not has_permission:
                logger.warning(
                    f"Insufficient permissions for user {user.username} to access {request.endpoint}"
                )

                if request.is_json or request.content_type == "application/json":
                    return (
                        jsonify(
                            {
                                "error": "Insufficient permissions",
                                "message": f"You need one of the following roles: {[r.value for r in normalized_roles]}",
                                "user_role": user.role.value,
                                "required_roles": [r.value for r in normalized_roles],
                                "status": 403,
                            }
                        ),
                        403,
                    )
                else:
                    return "Insufficient permissions", 403

            # User has required role, proceed with request
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def require_permission(resource: str, action: str = "read") -> Callable:
    """
    Decorator to require specific permission for a route

    Args:
        resource: Resource name (e.g., 'streams', 'admin', 'tak_servers')
        action: Action type ('read', 'write', 'delete', 'admin')

    Returns:
        Decorator function
    """

    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()

            if not user:
                logger.warning(
                    f"Unauthenticated access attempt to {request.endpoint} from {request.remote_addr}"
                )

                if request.is_json or request.content_type == "application/json":
                    return (
                        jsonify(
                            {
                                "error": "Authentication required",
                                "message": "You must be logged in to access this resource",
                                "status": 401,
                            }
                        ),
                        401,
                    )
                else:
                    session["next_url"] = request.url
                    return redirect(url_for("auth.login"))

            # Check permission
            if not user.can_access(resource, action):
                logger.warning(
                    f"Permission denied for user {user.username} to {action} {resource}"
                )

                if request.is_json or request.content_type == "application/json":
                    return (
                        jsonify(
                            {
                                "error": "Permission denied",
                                "message": f"You do not have permission to {action} {resource}",
                                "user_role": user.role.value,
                                "required_permission": f"{action} {resource}",
                                "status": 403,
                            }
                        ),
                        403,
                    )
                else:
                    return "Permission denied", 403

            # User has required permission, proceed with request
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f: Callable) -> Callable:
    """
    Decorator to require admin role for a route

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """
    return require_role(UserRole.ADMIN)(f)


def operator_required(f: Callable) -> Callable:
    """
    Decorator to require operator role or higher for a route

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """
    return require_role([UserRole.ADMIN, UserRole.OPERATOR])(f)


def api_key_or_auth_required(f: Callable) -> Callable:
    """
    Decorator to allow either API key or session authentication

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for API key first (future implementation)
        api_key = request.headers.get("X-API-Key")
        if api_key:
            # TODO: Implement API key validation
            # For now, fall back to session auth
            pass

        # Check session authentication
        user = get_current_user()

        if not user:
            logger.warning(
                f"Unauthenticated API access attempt to {request.endpoint} from {request.remote_addr}"
            )

            return (
                jsonify(
                    {
                        "error": "Authentication required",
                        "message": "You must provide valid authentication (session or API key)",
                        "status": 401,
                    }
                ),
                401,
            )

        # User is authenticated, proceed with request
        return f(*args, **kwargs)

    return decorated_function


def optional_auth(f: Callable) -> Callable:
    """
    Decorator that checks for authentication but doesn't require it
    Makes user available in request context if authenticated

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for authentication but don't require it
        user = get_current_user()

        # User is available in g.current_user regardless of authentication status
        return f(*args, **kwargs)

    return decorated_function


def login_required_json(f: Callable) -> Callable:
    """
    Decorator specifically for JSON API endpoints that require authentication
    Always returns JSON responses

    Args:
        f: Function to decorate

    Returns:
        Decorated function
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()

        if not user:
            logger.warning(
                f"Unauthenticated API access attempt to {request.endpoint} from {request.remote_addr}"
            )

            return (
                jsonify(
                    {
                        "error": "Authentication required",
                        "message": "You must be logged in to access this API endpoint",
                        "status": 401,
                    }
                ),
                401,
            )

        # User is authenticated, proceed with request
        return f(*args, **kwargs)

    return decorated_function


def check_session_validity():
    """
    Function to check session validity and refresh if needed
    Can be called manually or used in before_request handlers
    """
    session_id = session.get("session_id")
    if not session_id:
        return False

    auth_manager = get_auth_manager()
    if not auth_manager:
        return False

    user = auth_manager.get_user_by_session(session_id)

    if user:
        # Session is valid, cache user
        g.current_user = user
        return True
    else:
        # Session is invalid, clear it
        session.clear()
        g.current_user = None
        return False


def logout_user():
    """
    Log out the current user by invalidating their session

    Returns:
        True if logout was successful
    """
    session_id = session.get("session_id")
    if session_id:
        auth_manager = get_auth_manager()
        if auth_manager:
            auth_manager.invalidate_session(session_id)

    # Clear Flask session
    session.clear()

    # Clear request context
    if hasattr(g, "current_user"):
        g.current_user = None

    logger.info("User logged out successfully")
    return True


def get_user_permissions(user: User = None) -> Dict[str, List[str]]:
    """
    Get user permissions for template/UI use

    Args:
        user: User to check permissions for (defaults to current user)

    Returns:
        Dictionary of resource permissions
    """
    if not user:
        user = get_current_user()

    if not user:
        return {}

    permissions = {}
    resources = ["streams", "tak_servers", "admin", "api", "profile"]
    actions = ["read", "write", "delete", "admin"]

    for resource in resources:
        permissions[resource] = []
        for action in actions:
            if user.can_access(resource, action):
                permissions[resource].append(action)

    return permissions


def create_auth_context_processor():
    """
    Create context processor function for templates

    Returns:
        Context processor function
    """

    def auth_context():
        """Add authentication context to all templates"""
        user = get_current_user()

        return {
            "current_user": user,
            "is_authenticated": user is not None,
            "user_permissions": get_user_permissions(user) if user else {},
            "is_admin": user.role == UserRole.ADMIN if user else False,
            "is_operator": user.has_role(UserRole.OPERATOR) if user else False,
        }

    return auth_context
