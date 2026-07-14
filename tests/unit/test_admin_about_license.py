# ABOUTME: Tests that the admin about page displays licence status from the license service.
# ABOUTME: Covers Community fallback (no licence) and a valid Pro licence via env override.

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.license_service import canonical_license_bytes, reset_license_service


@pytest.fixture(autouse=True)
def clean_license_singleton():
    reset_license_service()
    yield
    reset_license_service()


def make_signed_license(path, tier="pro"):
    key = Ed25519PrivateKey.generate()
    issued = datetime.now(timezone.utc)
    license_data = {
        "customer_id": "acme-corp",
        "tier": tier,
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(days=30)).isoformat(),
        "licence_id": "test-licence-id",
    }
    signature = key.sign(canonical_license_bytes(license_data))
    path.write_text(
        json.dumps(
            {
                "license": license_data,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        )
    )
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return public_b64


class TestAboutPageLicense:
    def test_community_shown_when_no_license(
        self, authenticated_client, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(tmp_path / "none.json"))
        client = authenticated_client("admin")
        response = client.get("/admin/about")
        assert response.status_code == 200
        assert b"Community" in response.data

    def test_valid_pro_license_shown(self, authenticated_client, monkeypatch, tmp_path):
        lic_path = tmp_path / "license.json"
        public_b64 = make_signed_license(lic_path, tier="pro")
        monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(lic_path))
        monkeypatch.setattr(
            "services.license_service.EMBEDDED_LICENSE_PUBLIC_KEY", public_b64
        )
        client = authenticated_client("admin")
        response = client.get("/admin/about")
        assert response.status_code == 200
        assert b"Pro" in response.data
        assert b"acme-corp" in response.data

    def test_about_requires_admin(self, client):
        response = client.get("/admin/about")
        assert response.status_code in (302, 401, 403)


class TestLicenseInstallRoute:
    @pytest.fixture
    def install_env(self, monkeypatch, tmp_path):
        target = tmp_path / "installed" / "tb_license.json"
        monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(target))
        source = tmp_path / "incoming.json"
        public_b64 = make_signed_license(source, tier="pro")
        monkeypatch.setattr(
            "services.license_service.EMBEDDED_LICENSE_PUBLIC_KEY", public_b64
        )
        return source, target

    def test_file_upload_install_activates_license(
        self, authenticated_client, install_env
    ):
        import io

        source, target = install_env
        client = authenticated_client("admin")
        response = client.post(
            "/admin/license/install",
            data={
                "license_file": (
                    io.BytesIO(source.read_bytes()),
                    "license.json",
                )
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert target.is_file()
        assert b"Pro" in response.data
        assert b"acme-corp" in response.data

    def test_tampered_license_rejected_with_error(
        self, authenticated_client, install_env
    ):
        import io
        import json as jsonlib

        source, target = install_env
        doc = jsonlib.loads(source.read_text())
        doc["license"]["tier"] = "enterprise"
        client = authenticated_client("admin")
        response = client.post(
            "/admin/license/install",
            data={
                "license_file": (
                    io.BytesIO(jsonlib.dumps(doc).encode()),
                    "license.json",
                )
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert not target.exists()
        assert b"rejected" in response.data.lower()

    def test_empty_submission_rejected(self, authenticated_client, install_env):
        client = authenticated_client("admin")
        response = client.post("/admin/license/install", data={}, follow_redirects=True)
        assert response.status_code == 200
        assert b"rejected" in response.data.lower() or b"No licence" in response.data

    def test_install_requires_admin(self, client, install_env):
        response = client.post("/admin/license/install", data={})
        assert response.status_code in (302, 401, 403)

    def test_install_writes_audit_log(self, authenticated_client, install_env, caplog):
        import io

        source, _ = install_env
        client = authenticated_client("admin")
        with caplog.at_level("INFO"):
            client.post(
                "/admin/license/install",
                data={"license_file": (io.BytesIO(source.read_bytes()), "l.json")},
                content_type="multipart/form-data",
            )
        assert "licence install" in caplog.text.lower()
        assert "test-licence-id" in caplog.text
