# ABOUTME: End-to-end plugin manager tests — upload through the Flask client, badges in the UI,
# ABOUTME: tier gating with a real signed licence, and cross-repo signing-CLI compatibility.

import base64
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures"))
from plugin_package_builder import (
    build_package_dir,
    build_plugin_zip,
    zip_package_dir,
)  # noqa: E402

from services.license_service import (
    canonical_license_bytes,
    reset_license_service,
)  # noqa: E402

PREMIUM_TOOLS = (
    Path(__file__).resolve().parents[3] / "trakbridge-plugins-premium" / "tools"
)


@pytest.fixture
def keypair(monkeypatch):
    key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    monkeypatch.setattr(
        "services.license_service.EMBEDDED_LICENSE_PUBLIC_KEY", public_b64
    )
    return key, public_b64


@pytest.fixture
def env(tmp_path, monkeypatch, app, db_session):
    external = tmp_path / "external_plugins"
    external.mkdir()
    whitelist = tmp_path / "plugins.yaml"
    whitelist.write_text("allowed_plugin_modules: []\n")
    monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr("routes.plugin_admin.EXTERNAL_DIR_OVERRIDE", external)
    monkeypatch.setattr("routes.plugin_admin.WHITELIST_OVERRIDE", whitelist)
    reset_license_service()
    yield external, whitelist
    reset_license_service()


def install_pro_license(tmp_path, key, monkeypatch):
    issued = datetime.now(timezone.utc)
    license_data = {
        "customer_id": "e2e-customer",
        "tier": "pro",
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(days=30)).isoformat(),
        "licence_id": "e2e-licence",
    }
    signature = key.sign(canonical_license_bytes(license_data))
    lic = tmp_path / "license.json"
    lic.write_text(
        json.dumps(
            {
                "license": license_data,
                "signature": base64.b64encode(signature).decode("ascii"),
            }
        )
    )
    monkeypatch.setenv("TRAKBRIDGE_LICENSE_FILE", str(lic))
    reset_license_service()


def upload(client, data, filename="pkg.zip"):
    return client.post(
        "/admin/plugins/upload",
        data={"plugin_file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
        follow_redirects=True,
    )


class TestBadges:
    def test_signed_package_shows_verified_badge(
        self, authenticated_client, env, tmp_path, keypair
    ):
        key, _ = keypair
        client = authenticated_client("admin")
        upload(client, build_plugin_zip(tmp_path, "signed_e2e", sign_key=key))
        page = client.get("/admin/plugins/")
        assert b"signed_e2e" in page.data
        assert b"Verified" in page.data

        detail = client.get("/admin/plugins/signed_e2e")
        assert b"Verified" in detail.data

    def test_unsigned_package_shows_unverified_badge(
        self, authenticated_client, env, tmp_path, keypair
    ):
        client = authenticated_client("admin")
        upload(client, build_plugin_zip(tmp_path, "unsigned_e2e"))
        page = client.get("/admin/plugins/")
        assert b"Unverified" in page.data


class TestTierGatingEndToEnd:
    def test_pro_plugin_refused_on_community_installs_on_pro(
        self, authenticated_client, env, tmp_path, keypair, monkeypatch
    ):
        key, _ = keypair
        external, whitelist = env
        client = authenticated_client("admin")
        data = build_plugin_zip(tmp_path, "pro_e2e", tier="pro", sign_key=key)

        # Community: refused
        response = upload(client, data)
        assert b"rejected" in response.data.lower()
        assert not (external / "pro_e2e").exists()

        # Install a real signed Pro licence, retry: accepted
        install_pro_license(tmp_path, key, monkeypatch)
        response = upload(client, data)
        assert (external / "pro_e2e").exists()
        assert b"pro_e2e" in response.data

    def test_sideloaded_pro_package_skipped_at_load_on_community(
        self, env, tmp_path, keypair
    ):
        from plugins.plugin_manager import PluginManager

        external, whitelist = env
        build_package_dir(external, "sideload_pro", tier="pro")
        pm = PluginManager()
        pm._allowed_modules.add("external_plugins.sideload_pro")
        pm._load_package_plugins(str(external))
        assert "sideload_pro" not in pm.plugins


@pytest.mark.skipif(
    not PREMIUM_TOOLS.is_dir(),
    reason="trakbridge-plugins-premium repo not present (private repo)",
)
class TestCrossRepoSigning:
    def test_cli_signed_package_verifies_and_installs(
        self, authenticated_client, env, tmp_path, keypair, monkeypatch
    ):
        """The premium repo's sign_plugin_package.py output must install
        as Verified through the real upload route — guards digest drift."""
        key, _ = keypair
        external, whitelist = env

        # Write the throwaway private key as PEM for the CLI
        pem_path = tmp_path / "signing.pem"
        pem_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        pkg = build_package_dir(tmp_path / "src", "cli_signed")
        result = subprocess.run(
            [
                sys.executable,
                str(PREMIUM_TOOLS / "sign_plugin_package.py"),
                str(pkg),
                "--private-key",
                str(pem_path),
                "--output",
                str(tmp_path / "cli_signed.zip"),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        client = authenticated_client("admin")
        response = upload(
            client, (tmp_path / "cli_signed.zip").read_bytes(), "cli_signed.zip"
        )
        assert b"signature verified" in response.data.lower()

        from models.installed_plugin import InstalledPlugin

        row = InstalledPlugin.query.filter_by(plugin_id="cli_signed").one()
        assert row.is_verified is True
