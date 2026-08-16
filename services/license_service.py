# ABOUTME: Offline licence verification service — Ed25519-signed licence files map to app tiers.
# ABOUTME: Fails securely: missing/invalid/expired licences degrade to Community with a logged warning.

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

TIERS = ("community", "pro", "enterprise")

DEFAULT_LICENSE_PATH = Path("secrets/tb_license.json")

# The Trakbridge Project licence signing public key (base64-encoded raw Ed25519 
# public key).
# Generated offline via trakbridge-plugins-premium/tools/generate_license_keys.py.
# The matching private key is held offline by The TrakBridge Project and never 
# enters any repo.
EMBEDDED_LICENSE_PUBLIC_KEY: Optional[str] = (
    "S0z+d+8fNiXj+vKf943ayxsGD8/U1/YwyofvWZrZFDE="
)


def canonical_license_bytes(license_data: Dict[str, Any]) -> bytes:
    """Deterministic byte serialisation of the licence payload for signing.

    Must stay byte-identical to trakbridge-plugins-premium/tools/license_format.py
    or signatures will not verify.
    """
    return json.dumps(
        license_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


class LicenseService:
    """Loads and verifies the deployment licence file.

    Air-gap friendly: verification is fully offline against the embedded
    public key; there is no phone-home.
    """

    def __init__(
        self,
        license_path: Optional[os.PathLike] = None,
        public_key_b64: Optional[str] = None,
    ):
        if license_path is not None:
            self.license_path = Path(license_path)
        else:
            env_path = os.environ.get("TRAKBRIDGE_LICENSE_FILE")
            self.license_path = Path(env_path) if env_path else DEFAULT_LICENSE_PATH

        self._public_key_b64 = (
            public_key_b64
            if public_key_b64 is not None
            else EMBEDDED_LICENSE_PUBLIC_KEY
        )

        # status: valid | missing | invalid | expired
        self._status = "missing"
        self._license: Optional[Dict[str, Any]] = None
        self._load_and_verify()

    def _load_and_verify(self) -> None:
        try:
            if not self.license_path.is_file():
                self._status = "missing"
                logger.warning(
                    f"No licence file at {self.license_path} — running as Community tier"
                )
                return

            document = json.loads(self.license_path.read_text())
            license_data = document["license"]
            signature = base64.b64decode(document["signature"])

            if not self._public_key_b64:
                self._status = "invalid"
                logger.warning(
                    "Licence file present but no signing public key is embedded "
                    "in this build — running as Community tier"
                )
                return

            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self._public_key_b64)
            )
            try:
                public_key.verify(signature, canonical_license_bytes(license_data))
            except InvalidSignature:
                self._status = "invalid"
                logger.warning(
                    f"Licence file {self.license_path} failed signature "
                    "verification — running as Community tier"
                )
                return

            if license_data.get("tier") not in TIERS:
                self._status = "invalid"
                logger.warning(
                    f"Licence declares unknown tier "
                    f"'{license_data.get('tier')}' — running as Community tier"
                )
                return

            # Signature is valid; expiry is (re)checked on every get_tier() call
            self._license = license_data
            self._status = "valid"
            logger.info(
                f"Licence verified: customer={license_data.get('customer_id')} "
                f"tier={license_data.get('tier')} "
                f"expires={license_data.get('expires_at')}"
            )
        except Exception as e:
            self._status = "invalid"
            self._license = None
            logger.warning(
                f"Failed to load licence from {self.license_path}: {e} — "
                "running as Community tier"
            )

    def _is_expired(self) -> bool:
        if self._license is None:
            return False
        try:
            expires_at = datetime.fromisoformat(self._license["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) >= expires_at
        except Exception as e:
            logger.warning(f"Unparseable licence expiry: {e} — treating as expired")
            return True

    def get_tier(self) -> str:
        """Return the effective tier: community | pro | enterprise."""
        if self._status != "valid" and self._status != "expired":
            return "community"
        if self._is_expired():
            if self._status != "expired":
                self._status = "expired"
                logger.warning("Licence has expired — running as Community tier")
            return "community"
        return self._license["tier"]

    def is_tier_allowed(self, required_tier: str) -> bool:
        """True when the current licence tier satisfies required_tier."""
        if required_tier not in TIERS:
            logger.warning(f"Unknown required tier '{required_tier}' — refusing")
            return False
        return TIERS.index(required_tier) <= TIERS.index(self.get_tier())

    def get_license_info(self) -> Dict[str, Any]:
        """Licence status summary for the admin UI. Never includes the signature."""
        self.get_tier()  # refresh expired status
        info: Dict[str, Any] = {
            "status": self._status,
            "tier": self.get_tier(),
            "license_path": str(self.license_path),
        }
        if self._license is not None:
            info.update(
                customer_id=self._license.get("customer_id"),
                licensed_tier=self._license.get("tier"),
                issued_at=self._license.get("issued_at"),
                expires_at=self._license.get("expires_at"),
                licence_id=self._license.get("licence_id"),
            )
        return info


def install_license(
    content: str,
    license_path: Optional[os.PathLike] = None,
    public_key_b64: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a licence document and install it as the active licence.

    Verification happens BEFORE anything is written: a rejected licence never
    touches disk and the currently installed licence is preserved. On success
    the singleton is reset so the new tier takes effect immediately.

    Returns the licence payload dict. Raises ValueError with an
    admin-presentable reason on rejection.
    """
    key_b64 = (
        public_key_b64 if public_key_b64 is not None else EMBEDDED_LICENSE_PUBLIC_KEY
    )
    if not key_b64:
        raise ValueError("No signing public key is embedded in this build")

    try:
        document = json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValueError(f"Not valid JSON: {e}") from e

    if (
        not isinstance(document, dict)
        or "license" not in document
        or "signature" not in document
    ):
        raise ValueError("Document must contain 'license' and 'signature' fields")

    license_data = document["license"]
    if not isinstance(license_data, dict):
        raise ValueError("'license' field must be an object")

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        signature = base64.b64decode(document["signature"])
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64))
        public_key.verify(signature, canonical_license_bytes(license_data))
    except InvalidSignature:
        raise ValueError("Invalid signature — this licence was not issued by Trakbridge")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Malformed signature: {e}") from e

    if license_data.get("tier") not in TIERS:
        raise ValueError(f"Unknown tier '{license_data.get('tier')}'")

    try:
        expires_at = datetime.fromisoformat(license_data["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"Missing or unparseable expires_at: {e}") from e
    if datetime.now(timezone.utc) >= expires_at:
        raise ValueError(f"Licence expired at {license_data['expires_at']}")

    if license_path is not None:
        target = Path(license_path)
    else:
        env_path = os.environ.get("TRAKBRIDGE_LICENSE_FILE")
        target = Path(env_path) if env_path else DEFAULT_LICENSE_PATH

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(document, indent=2) + "\n")
    tmp.chmod(0o600)
    os.replace(tmp, target)

    reset_license_service()
    logger.info(
        f"Licence installed: customer={license_data.get('customer_id')} "
        f"tier={license_data.get('tier')} licence_id={license_data.get('licence_id')} "
        f"path={target}"
    )
    return license_data


_license_service: Optional[LicenseService] = None


def get_license_service() -> LicenseService:
    """Return the process-wide licence service singleton."""
    global _license_service
    if _license_service is None:
        _license_service = LicenseService()
    return _license_service


def reset_license_service() -> None:
    """Discard the singleton (tests, or after installing a new licence file)."""
    global _license_service
    _license_service = None
