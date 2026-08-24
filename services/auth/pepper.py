# ABOUTME: Loads the server-side pepper mixed into API-key HMAC hashes.
# ABOUTME: Refuses to boot in production if API_KEY_PEPPER is unset.
"""
Server-side pepper for API-key hashing.

The pepper is a static secret mixed into every HMAC computation
alongside the per-key salt. A DB-only compromise cannot verify or
forge tokens without also stealing this value — it must be treated
like the database encryption key.

**Rotation cost**: rotating the pepper invalidates every existing
API key because the stored token_hash is bound to the pepper value
at generation time. Rotate only in response to a suspected pepper
compromise.

Loaded once per process. In production the app refuses to start
when API_KEY_PEPPER is unset. In development/testing an ephemeral
pepper is generated with a startup WARNING so local runs work
frictionlessly, but the warning is loud so it does not go
unnoticed in a staging misconfiguration.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Optional

_ENV_VAR = "API_KEY_PEPPER"
_MIN_BYTES = 32  # HMAC-SHA256 recommends a key at least as long as the block size / 2

_pepper_bytes: Optional[bytes] = None
_logger = logging.getLogger(__name__)


class PepperMissingError(RuntimeError):
    """Raised when API_KEY_PEPPER is required but not present."""


def _decode(raw: str) -> bytes:
    """Accept either base64 or raw string form; require enough entropy.

    Prefer base64 so operators can safely paste ``openssl rand -base64 48``
    output. Raw strings are accepted for convenience but must be at
    least ``_MIN_BYTES`` characters.
    """
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) >= _MIN_BYTES:
            return decoded
    except (ValueError, base64.binascii.Error):
        pass
    encoded = raw.encode("utf-8")
    if len(encoded) < _MIN_BYTES:
        raise PepperMissingError(
            f"{_ENV_VAR} must be at least {_MIN_BYTES} bytes "
            f"(base64 or raw)"
        )
    return encoded


def load_pepper(is_production: bool) -> bytes:
    """Resolve the pepper for this process.

    Called once during app startup. Result is cached module-globally
    so `get_pepper()` is cheap on the request path.
    """
    global _pepper_bytes

    raw = os.environ.get(_ENV_VAR, "").strip()
    if raw:
        _pepper_bytes = _decode(raw)
        _logger.info(
            "%s loaded (%d bytes)", _ENV_VAR, len(_pepper_bytes)
        )
        return _pepper_bytes

    if is_production:
        raise PepperMissingError(
            f"{_ENV_VAR} is required in production. Generate one with "
            f"`openssl rand -base64 48` and set it in the environment."
        )

    # Non-production: generate an ephemeral pepper so local dev works,
    # but log loudly so a mistaken staging deploy is obvious.
    _pepper_bytes = secrets.token_bytes(_MIN_BYTES)
    _logger.warning(
        "%s not set; generated an EPHEMERAL pepper for this process. "
        "All API keys created in this run will be invalidated on "
        "restart. Set %s to a persistent value for real use.",
        _ENV_VAR,
        _ENV_VAR,
    )
    return _pepper_bytes


def get_pepper() -> bytes:
    """Return the loaded pepper. Must be called after ``load_pepper``."""
    if _pepper_bytes is None:
        raise PepperMissingError(
            "get_pepper() called before load_pepper(); ensure "
            "create_app() has run."
        )
    return _pepper_bytes


def _reset_for_tests() -> None:
    """Test-only helper to clear the cached pepper between tests."""
    global _pepper_bytes
    _pepper_bytes = None
