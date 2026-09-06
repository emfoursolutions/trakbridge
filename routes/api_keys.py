# ABOUTME: User-facing API key management routes at /auth/api-keys.
# ABOUTME: List, create-shown-once, and revoke; enforces cap + rate limit.
"""
File: routes/api_keys.py

Description:
    Self-service API key management for authenticated users. Users
    can list their own active keys, create new keys (plaintext token
    shown once, then hashed and discarded), and revoke keys they own.

    All endpoints are session-only — a leaked API key must never be
    able to mint further keys or revoke rival keys, so the routes
    themselves refuse bearer authentication regardless of scope.

    Enforces two anti-abuse limits at create time:
    - Hard cap of 10 active (non-revoked, non-expired) keys per user
    - Per-user rate limit of 5 creates per hour (independent of the
      IP-based Flask-Limiter default so shared-NAT users aren't
      punished for each other's keygen activity)

Author: Emfour Solutions
Created: 2026-08-25
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from database import db
from models.user import UserApiKey
from services.auth import (
    get_current_user,
    get_user_permissions,
    require_permission,
    session_only,
)
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

bp = Blueprint("api_keys", __name__)

# Hard cap: the maximum number of active (non-revoked, non-expired)
# keys a single user may hold. Prevents a compromised session from
# silently generating dozens of persistent backdoors.
MAX_ACTIVE_KEYS_PER_USER = 10

# Curated list of scopes offered to users in the create UI. The set
# is deliberately narrower than the full permission matrix — some
# resources (admin, api_keys) are session-only and not useful as
# API-key scopes. Ordered to reflect UI grouping.
OFFERABLE_SCOPES = [
    # Streams
    ("streams:read", "View streams and their status"),
    ("streams:write", "Create and modify streams"),
    ("streams:delete", "Delete streams"),
    # TAK servers
    ("tak_servers:read", "View TAK server configuration"),
    ("tak_servers:write", "Create and modify TAK servers"),
    ("tak_servers:delete", "Delete TAK servers"),
    # Generic API
    ("api:read", "Read-only access to API metadata endpoints"),
    ("api:write", "Write access to API-side operations"),
    # Profile
    ("profile:read", "Read the owning user's profile"),
]


# ---------------------------------------------------------------------------
# Per-user rate-limit key
# ---------------------------------------------------------------------------


def _apikey_create_ratelimit_key() -> str:
    """Custom Flask-Limiter key: bucket creation attempts per user.

    Falls back to IP if the user cannot be resolved — that means the
    limit is triggered before the request has authenticated, which is
    a benign edge case (unauthenticated calls to /auth/api-keys are
    rejected anyway).
    """
    user = get_current_user()
    if user is not None and getattr(user, "id", None) is not None:
        return f"apikey_create:user:{user.id}"
    from flask_limiter.util import get_remote_address

    return f"apikey_create:ip:{get_remote_address()}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_active_key_count(user_id: int) -> int:
    """How many non-revoked, non-expired keys the user currently holds."""
    now = datetime.now(timezone.utc)
    query = UserApiKey.query.filter_by(user_id=user_id, is_active=True)
    # SQLAlchemy handles NULL vs value in a portable way; expired
    # keys are filtered out client-side because DB-side date math
    # differs across SQLite/Postgres/MySQL.
    count = 0
    for key in query.all():
        if key.expires_at is not None:
            expires = key.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now >= expires:
                continue
        count += 1
    return count


def _user_permits_scope(
    user_permissions: Dict[str, List[str]], scope: str
) -> bool:
    """True when the user has the underlying permission for a scope.

    Enforces "key can never exceed owner" at CREATE time in addition
    to the request-time check in require_permission. Belt + braces.
    """
    if ":" not in scope:
        return False
    resource, action = scope.split(":", 1)
    return action in user_permissions.get(resource, [])


def _parse_expires_at(raw: Optional[str]) -> Optional[datetime]:
    """Parse a YYYY-MM-DD or ISO-8601 string into an aware datetime.

    Returns None for empty/missing input. Raises ValueError on
    malformed input; caller translates to 400.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    # Accept YYYY-MM-DD as end-of-day UTC.
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            date = datetime.strptime(text, "%Y-%m-%d")
            return date.replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        # Fall back to full ISO-8601.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError as exc:
        raise ValueError(f"Invalid expires_at value: {exc}") from exc


def _get_body() -> Dict[str, Any]:
    """Accept either JSON or form-encoded input."""
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict):
            return data
        return {}
    return request.form.to_dict(flat=True)


def _lazy_limit(rule: str, key_func):
    """Apply a Flask-Limiter limit that reads app.limiter at call time.

    Blueprints register before app.limiter is initialised in app.py,
    so we can't decorate at import time. Wrapping via a closure lets
    the limit lookup happen on first invocation.
    """
    def decorator(fn):
        applied = {"fn": None}

        def wrapper(*args, **kwargs):
            if applied["fn"] is None:
                limiter = current_app.limiter
                applied["fn"] = limiter.limit(rule, key_func=key_func)(fn)
            return applied["fn"](*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__wrapped__ = fn
        # Preserve OpenAPI security marker if present.
        marker = getattr(fn, "_openapi_security", None)
        if marker is not None:
            wrapper._openapi_security = marker
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.route("/", methods=["GET"])
@session_only
@require_permission("api_keys", "read")
def list_keys():
    """Render the current user's API key list."""
    user = get_current_user()
    keys = (
        UserApiKey.query.filter_by(user_id=user.id)
        .order_by(UserApiKey.created_at.desc())
        .all()
    )
    active_count = _user_active_key_count(user.id)
    user_permissions = get_user_permissions(user)
    offerable = [
        {"scope": scope, "description": desc}
        for scope, desc in OFFERABLE_SCOPES
        if _user_permits_scope(user_permissions, scope)
    ]
    return render_template(
        "auth/api_keys.html",
        user=user,
        keys=[k.to_dict() for k in keys],
        active_count=active_count,
        max_active=MAX_ACTIVE_KEYS_PER_USER,
        offerable_scopes=offerable,
    )


@bp.route("/", methods=["POST"])
@session_only
@require_permission("api_keys", "write")
@_lazy_limit("5 per hour", _apikey_create_ratelimit_key)
def create_key():
    """Create a new API key; return the plaintext token exactly once.

    Response is HTML (server-rendered reveal page) for form submits
    and JSON for API/XHR submits — content negotiation by Accept
    header and request.is_json.
    """
    user = get_current_user()

    # Enforce the active-key cap BEFORE minting anything.
    if _user_active_key_count(user.id) >= MAX_ACTIVE_KEYS_PER_USER:
        logger.warning(
            "AUDIT: api_key create_rejected reason=cap user=%s active=%d",
            user.username,
            MAX_ACTIVE_KEYS_PER_USER,
        )
        message = (
            f"You already have {MAX_ACTIVE_KEYS_PER_USER} active API "
            f"keys, the maximum allowed. Revoke an existing key before "
            f"creating a new one."
        )
        if request.is_json:
            return jsonify({"error": "cap_exceeded", "message": message}), 409
        flash(message, "error")
        return redirect(url_for("api_keys.list_keys"))

    body = _get_body()
    name = (body.get("name") or "").strip()
    scopes_raw = body.get("scopes") or []
    if isinstance(scopes_raw, str):
        # Form-encoded arrays arrive as either a comma-separated
        # string or repeated keys; handle both.
        if "," in scopes_raw:
            scopes_raw = [s.strip() for s in scopes_raw.split(",")]
        else:
            scopes_raw = request.form.getlist("scopes") or [scopes_raw]
    expires_at_raw = body.get("expires_at") or ""

    if not name:
        message = "Key name is required."
        if request.is_json:
            return jsonify({"error": "name_required", "message": message}), 400
        flash(message, "error")
        return redirect(url_for("api_keys.list_keys"))

    if not isinstance(scopes_raw, list) or not scopes_raw:
        message = "At least one scope is required."
        if request.is_json:
            return jsonify({"error": "scopes_required", "message": message}), 400
        flash(message, "error")
        return redirect(url_for("api_keys.list_keys"))

    # Normalise + validate scopes against both the offerable list and
    # the user's own permissions. Rejecting scopes the user doesn't
    # have enforces "key <= owner" at creation time.
    user_permissions = get_user_permissions(user)
    offerable_set = {scope for scope, _ in OFFERABLE_SCOPES}
    scopes: List[str] = []
    for raw in scopes_raw:
        scope = (raw or "").strip()
        if not scope:
            continue
        if scope not in offerable_set:
            message = f"Unknown scope: {scope}"
            if request.is_json:
                return (
                    jsonify({"error": "invalid_scope", "message": message}),
                    400,
                )
            flash(message, "error")
            return redirect(url_for("api_keys.list_keys"))
        if not _user_permits_scope(user_permissions, scope):
            logger.warning(
                "AUDIT: api_key create_rejected reason=scope_exceeds_owner "
                "user=%s scope=%s",
                user.username,
                scope,
            )
            message = (
                f"Your role does not permit the {scope} scope."
            )
            if request.is_json:
                return (
                    jsonify({"error": "scope_forbidden", "message": message}),
                    403,
                )
            flash(message, "error")
            return redirect(url_for("api_keys.list_keys"))
        if scope not in scopes:
            scopes.append(scope)

    try:
        expires_at = _parse_expires_at(expires_at_raw)
    except ValueError as exc:
        if request.is_json:
            return (
                jsonify({"error": "invalid_expires_at", "message": str(exc)}),
                400,
            )
        flash(str(exc), "error")
        return redirect(url_for("api_keys.list_keys"))

    key, plaintext = UserApiKey.generate(
        user=user,
        name=name,
        scopes=scopes,
        expires_at=expires_at,
    )
    logger.info(
        "AUDIT: api_key create user=%s key_prefix=%s scopes=%s "
        "expires_at=%s",
        user.username,
        key.token_prefix,
        json.dumps(scopes),
        expires_at.isoformat() if expires_at else "never",
    )

    payload = key.to_dict()
    payload["token"] = plaintext
    payload["warning"] = (
        "Save this token now — it will not be shown again."
    )

    if request.is_json:
        return jsonify(payload), 201
    return render_template(
        "auth/api_key_created.html",
        user=user,
        key=payload,
    )


@bp.route("/<int:key_id>/revoke", methods=["POST"])
@session_only
@require_permission("api_keys", "delete")
def revoke_key(key_id: int):
    """Revoke a key owned by the current user.

    Returns 404 (not 403) when the key belongs to another user — the
    caller must not be able to distinguish "not yours" from "doesn't
    exist" for enumeration reasons.
    """
    user = get_current_user()
    key = UserApiKey.query.get(key_id)
    if key is None or key.user_id != user.id:
        if request.is_json:
            return jsonify({"error": "not_found"}), 404
        abort(404)

    if key.revoked_at is not None:
        # Idempotent — revoking an already-revoked key is a no-op.
        message = "This key was already revoked."
        if request.is_json:
            return jsonify({"success": True, "message": message}), 200
        flash(message, "info")
        return redirect(url_for("api_keys.list_keys"))

    key.revoke()
    db.session.commit()
    logger.info(
        "AUDIT: api_key revoke actor=%s owner=%s key_prefix=%s",
        user.username,
        user.username,
        key.token_prefix,
    )

    message = f"API key '{key.name}' has been revoked."
    if request.is_json:
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for("api_keys.list_keys"))
