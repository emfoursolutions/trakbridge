# ABOUTME: Request-path API-key resolver: header -> UserApiKey lookup.
# ABOUTME: Also handles the throttled last_used_at write.
"""
File: services/auth/api_key_service.py

Description:
    Bearer-token → UserApiKey resolution on the request path.

    The model file (models/user.py) owns "what is a key row and how do
    I hash/verify one plaintext against it". This service owns "how do
    I find the right row given an incoming Authorization header, and
    how do I record that it was used, without a DB write per request".

    Called from services/auth/decorators.py::get_current_user() before
    the session-cookie lookup runs, so any request carrying a valid
    bearer token authenticates via the API-key path first.

Author: Emfour Solutions
Created: 2026-08-24
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from database import db
from models.user import (
    API_KEY_PREFIX_LEN,
    API_KEY_TOKEN_PREFIX,
    UserApiKey,
)
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

# Throttle interval for last_used_at writes. Mirrors the throttling
# used for UserSession.last_activity (5 minutes) but tuned tighter
# since API keys are machine-driven and 60s gives near-real-time
# visibility on the user's key management page without a write per
# request.
LAST_USED_THROTTLE = timedelta(seconds=60)


def extract_bearer(authorization_header: Optional[str]) -> Optional[str]:
    """Return the bearer token if the header names our prefix.

    Fast-reject path so a wrong scheme, missing header, or foreign
    bearer format never touches the database. Returns None when the
    caller should fall through to session auth.
    """
    if not authorization_header:
        return None
    parts = authorization_header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    if not token.startswith(API_KEY_TOKEN_PREFIX):
        return None
    return token


def resolve_api_key(authorization_header: Optional[str]) -> Optional[UserApiKey]:
    """Look up an active, valid API key for the given Authorization header.

    Steps:
    1. Fast-reject headers that aren't ``Bearer tb_pat_...`` (no DB).
    2. Look up candidates by ``token_prefix`` (indexed).
    3. Constant-time verify each candidate. Prefix collision on 12
       random base64url chars is astronomically unlikely — in practice
       one candidate per lookup.
    4. Enforce ``is_valid()``: not revoked, not expired, owner ACTIVE.

    Returns the key row on success or None otherwise. Never raises.
    Any auth failure is silent from the caller's perspective — the
    decorator layer decides how to respond (401, anti-enumeration).
    """
    token = extract_bearer(authorization_header)
    if token is None:
        return None

    prefix = token[:API_KEY_PREFIX_LEN]
    candidates = (
        UserApiKey.query.filter_by(token_prefix=prefix, is_active=True).all()
    )
    if not candidates:
        return None

    for key in candidates:
        if not key.verify(token):
            continue
        if key.is_valid():
            return key
        # Matched but not valid — log the reason once so operators can
        # spot expired keys that clients are still hitting.
        if key.expires_at is not None:
            logger.info(
                "AUDIT: api_key expiry_hit prefix=%s",
                key.token_prefix,
            )
        return None
    return None


def touch_last_used(key: UserApiKey) -> None:
    """Update ``last_used_at`` at most once per LAST_USED_THROTTLE window.

    Naive per-request writes would create a write per authenticated
    call. The 60-second throttle keeps the profile page's "last used"
    column near-real-time while keeping DB pressure trivial.
    """
    now = datetime.now(timezone.utc)
    last = key.last_used_at
    if last is not None and last.tzinfo is None:
        # SQLite strips tz on read; normalise to survive comparison.
        last = last.replace(tzinfo=timezone.utc)
    if last is None or (now - last) > LAST_USED_THROTTLE:
        key.last_used_at = now
        try:
            db.session.commit()
        except Exception:
            # A commit failure here must not deny the request — the
            # user is authenticated, we just missed a metric write.
            db.session.rollback()
            logger.warning(
                "Failed to update last_used_at for key %s",
                key.token_prefix,
            )
