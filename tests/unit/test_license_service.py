# ABOUTME: Tests for services/license_service.py — Ed25519 licence verification and tiering.
# ABOUTME: Covers valid/missing/tampered/expired/garbage licences and fail-secure Community fallback.

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.license_service import (
    TIERS,
    LicenseService,
    canonical_license_bytes,
    get_license_service,
    install_license,
    reset_license_service,
)


@pytest.fixture(autouse=True)
def clean_singleton():
    reset_license_service()
    yield
    reset_license_service()


@pytest.fixture
def signing_key():
    return Ed25519PrivateKey.generate()


@pytest.fixture
def public_key_b64(signing_key):
    raw = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def write_license(
    path,
    signing_key,
    tier="pro",
    customer_id="acme",
    expires_delta=timedelta(days=30),
    tamper=None,
):
    issued = datetime.now(timezone.utc)
    license_data = {
        "customer_id": customer_id,
        "tier": tier,
        "issued_at": issued.isoformat(),
        "expires_at": (issued + expires_delta).isoformat(),
        "licence_id": "11111111-2222-3333-4444-555555555555",
    }
    signature = signing_key.sign(canonical_license_bytes(license_data))
    if tamper:
        license_data.update(tamper)
    path.write_text(
        json.dumps(
            {
                "license": license_data,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        )
    )
    return path


class TestValidLicense:
    def test_valid_pro_license(self, tmp_path, signing_key, public_key_b64):
        lic = write_license(tmp_path / "l.json", signing_key, tier="pro")
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.get_tier() == "pro"
        info = service.get_license_info()
        assert info["status"] == "valid"
        assert info["customer_id"] == "acme"
        assert info["tier"] == "pro"
        assert info["licence_id"] == "11111111-2222-3333-4444-555555555555"

    def test_valid_enterprise_license(self, tmp_path, signing_key, public_key_b64):
        lic = write_license(tmp_path / "l.json", signing_key, tier="enterprise")
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.get_tier() == "enterprise"


class TestFailSecure:
    def test_missing_file_falls_back_to_community(
        self, tmp_path, public_key_b64, caplog
    ):
        service = LicenseService(
            license_path=tmp_path / "nope.json", public_key_b64=public_key_b64
        )
        assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "missing"

    def test_tampered_license_falls_back_with_warning(
        self, tmp_path, signing_key, public_key_b64, caplog
    ):
        lic = write_license(
            tmp_path / "l.json",
            signing_key,
            tier="pro",
            tamper={"tier": "enterprise"},
        )
        with caplog.at_level("WARNING"):
            service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
            assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "invalid"
        assert "signature" in caplog.text.lower()

    def test_expired_license_falls_back_with_warning(
        self, tmp_path, signing_key, public_key_b64, caplog
    ):
        lic = write_license(
            tmp_path / "l.json",
            signing_key,
            tier="pro",
            expires_delta=timedelta(days=-1),
        )
        with caplog.at_level("WARNING"):
            service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
            assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "expired"

    def test_garbage_json_falls_back(self, tmp_path, public_key_b64):
        bad = tmp_path / "l.json"
        bad.write_text("{not json")
        service = LicenseService(license_path=bad, public_key_b64=public_key_b64)
        assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "invalid"

    def test_wrong_key_signature_falls_back(self, tmp_path, signing_key):
        other_key = Ed25519PrivateKey.generate()
        other_pub = base64.b64encode(
            other_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        lic = write_license(tmp_path / "l.json", signing_key, tier="pro")
        service = LicenseService(license_path=lic, public_key_b64=other_pub)
        assert service.get_tier() == "community"

    def test_no_embedded_public_key_falls_back(self, tmp_path, signing_key, caplog):
        lic = write_license(tmp_path / "l.json", signing_key, tier="pro")
        with caplog.at_level("WARNING"):
            service = LicenseService(license_path=lic, public_key_b64=None)
            assert service.get_tier() == "community"

    def test_valid_signature_unknown_tier_falls_back(
        self, tmp_path, signing_key, public_key_b64
    ):
        lic = write_license(tmp_path / "l.json", signing_key, tier="platinum")
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "invalid"

    def test_service_never_raises_on_unreadable_path(self, public_key_b64):
        service = LicenseService(
            license_path="/dev/null/impossible", public_key_b64=public_key_b64
        )
        assert service.get_tier() == "community"


class TestPathResolution:
    def test_env_var_overrides_default(
        self, tmp_path, signing_key, public_key_b64, monkeypatch
    ):
        lic = write_license(tmp_path / "env.json", signing_key, tier="pro")
        monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(lic))
        service = LicenseService(public_key_b64=public_key_b64)
        assert service.get_tier() == "pro"

    def test_default_path_is_secrets_tb_license(self, monkeypatch):
        monkeypatch.delenv("TRAKBRIDGE_LICENSE_FILE", raising=False)
        service = LicenseService(public_key_b64=None)
        assert str(service.license_path).endswith("secrets/tb_license.json")


class TestTierOrdering:
    def test_tier_vocabulary(self):
        assert TIERS == ("community", "pro", "enterprise")

    def test_is_tier_allowed_matrix(self, tmp_path, signing_key, public_key_b64):
        lic = write_license(tmp_path / "l.json", signing_key, tier="pro")
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.is_tier_allowed("community") is True
        assert service.is_tier_allowed("pro") is True
        assert service.is_tier_allowed("enterprise") is False

    def test_community_fallback_only_allows_community(self, tmp_path, public_key_b64):
        service = LicenseService(
            license_path=tmp_path / "nope.json", public_key_b64=public_key_b64
        )
        assert service.is_tier_allowed("community") is True
        assert service.is_tier_allowed("pro") is False

    def test_unknown_required_tier_is_never_allowed(
        self, tmp_path, signing_key, public_key_b64
    ):
        lic = write_license(tmp_path / "l.json", signing_key, tier="enterprise")
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.is_tier_allowed("platinum") is False


class TestExpiryRecheck:
    def test_expiry_is_rechecked_on_get_tier(
        self, tmp_path, signing_key, public_key_b64
    ):
        lic = write_license(
            tmp_path / "l.json",
            signing_key,
            tier="pro",
            expires_delta=timedelta(milliseconds=200),
        )
        service = LicenseService(license_path=lic, public_key_b64=public_key_b64)
        assert service.get_tier() == "pro"
        import time

        time.sleep(0.3)
        assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "expired"


class TestInstallLicense:
    def test_valid_license_installed_and_live(
        self, tmp_path, signing_key, public_key_b64
    ):
        source = write_license(tmp_path / "incoming.json", signing_key, tier="pro")
        target = tmp_path / "installed" / "tb_license.json"

        info = install_license(
            source.read_text(), license_path=target, public_key_b64=public_key_b64
        )

        assert info["tier"] == "pro"
        assert target.is_file()
        assert oct(target.stat().st_mode)[-3:] == "600"
        service = LicenseService(license_path=target, public_key_b64=public_key_b64)
        assert service.get_tier() == "pro"

    def test_install_resets_singleton(self, tmp_path, signing_key, public_key_b64):
        stale = get_license_service()
        source = write_license(tmp_path / "incoming.json", signing_key, tier="pro")
        install_license(
            source.read_text(),
            license_path=tmp_path / "l.json",
            public_key_b64=public_key_b64,
        )
        assert get_license_service() is not stale

    def test_garbage_json_rejected(self, tmp_path, public_key_b64):
        with pytest.raises(ValueError, match="JSON"):
            install_license(
                "{nope", license_path=tmp_path / "l.json", public_key_b64=public_key_b64
            )
        assert not (tmp_path / "l.json").exists()

    def test_missing_fields_rejected(self, tmp_path, public_key_b64):
        with pytest.raises(ValueError):
            install_license(
                json.dumps({"license": {}}),
                license_path=tmp_path / "l.json",
                public_key_b64=public_key_b64,
            )

    def test_tampered_signature_rejected(self, tmp_path, signing_key, public_key_b64):
        source = write_license(
            tmp_path / "incoming.json",
            signing_key,
            tier="pro",
            tamper={"tier": "enterprise"},
        )
        with pytest.raises(ValueError, match="signature"):
            install_license(
                source.read_text(),
                license_path=tmp_path / "l.json",
                public_key_b64=public_key_b64,
            )
        assert not (tmp_path / "l.json").exists()

    def test_expired_license_rejected_at_install(
        self, tmp_path, signing_key, public_key_b64
    ):
        source = write_license(
            tmp_path / "incoming.json",
            signing_key,
            tier="pro",
            expires_delta=timedelta(days=-1),
        )
        with pytest.raises(ValueError, match="expired"):
            install_license(
                source.read_text(),
                license_path=tmp_path / "l.json",
                public_key_b64=public_key_b64,
            )

    def test_unknown_tier_rejected(self, tmp_path, signing_key, public_key_b64):
        source = write_license(tmp_path / "incoming.json", signing_key, tier="platinum")
        with pytest.raises(ValueError, match="tier"):
            install_license(
                source.read_text(),
                license_path=tmp_path / "l.json",
                public_key_b64=public_key_b64,
            )

    def test_rejected_install_preserves_existing_license(
        self, tmp_path, signing_key, public_key_b64
    ):
        target = tmp_path / "l.json"
        good = write_license(tmp_path / "good.json", signing_key, tier="pro")
        install_license(
            good.read_text(), license_path=target, public_key_b64=public_key_b64
        )
        with pytest.raises(ValueError):
            install_license("{nope", license_path=target, public_key_b64=public_key_b64)
        service = LicenseService(license_path=target, public_key_b64=public_key_b64)
        assert service.get_tier() == "pro"


class TestSingleton:
    def test_get_license_service_returns_same_instance(self):
        assert get_license_service() is get_license_service()

    def test_reset_creates_fresh_instance(self):
        first = get_license_service()
        reset_license_service()
        assert get_license_service() is not first
