# ABOUTME: Cross-repo integration test — licences issued by the premium repo's sign_license.py
# ABOUTME: must verify through core's LicenseService (guards canonical-format drift).

import subprocess
import sys
from pathlib import Path

import pytest

from services.license_service import LicenseService

TOOLS_DIR = Path(__file__).resolve().parents[3] / "trakbridge-plugins-premium" / "tools"

pytestmark = pytest.mark.skipif(
    not TOOLS_DIR.is_dir(),
    reason="trakbridge-plugins-premium repo not present (private repo)",
)


def run_tool(script, *args):
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / script), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class TestSignedLicenseEndToEnd:
    def test_full_keygen_sign_verify_flow(self, tmp_path):
        key_path = tmp_path / "signing.pem"
        keygen_output = run_tool(
            "generate_license_keys.py",
            "--private-key",
            str(key_path),
            "--no-passphrase",
        )
        public_key_b64 = keygen_output.strip().splitlines()[-1]

        license_path = tmp_path / "customer-license.json"
        run_tool(
            "sign_license.py",
            "--private-key",
            str(key_path),
            "--customer-id",
            "integration-test-customer",
            "--tier",
            "enterprise",
            "--expires-in-days",
            "7",
            "--output",
            str(license_path),
            # Never contaminate the premium repo's authoritative issuance ledger
            # (issued_licences.csv) from a test run — the CLI defaults to writing
            # to it for real customer issuance.
            "--no-register",
        )

        service = LicenseService(
            license_path=license_path, public_key_b64=public_key_b64
        )
        assert service.get_tier() == "enterprise"
        info = service.get_license_info()
        assert info["status"] == "valid"
        assert info["customer_id"] == "integration-test-customer"

    def test_tampered_signed_license_rejected(self, tmp_path):
        import json

        key_path = tmp_path / "signing.pem"
        keygen_output = run_tool(
            "generate_license_keys.py",
            "--private-key",
            str(key_path),
            "--no-passphrase",
        )
        public_key_b64 = keygen_output.strip().splitlines()[-1]

        license_path = tmp_path / "license.json"
        run_tool(
            "sign_license.py",
            "--private-key",
            str(key_path),
            "--customer-id",
            "tamper-test",
            "--tier",
            "pro",
            "--expires-in-days",
            "7",
            "--output",
            str(license_path),
            # Never contaminate the premium repo's authoritative issuance ledger
            # (issued_licences.csv) from a test run — the CLI defaults to writing
            # to it for real customer issuance.
            "--no-register",
        )

        doc = json.loads(license_path.read_text())
        doc["license"]["tier"] = "enterprise"
        license_path.write_text(json.dumps(doc))

        service = LicenseService(
            license_path=license_path, public_key_b64=public_key_b64
        )
        assert service.get_tier() == "community"
        assert service.get_license_info()["status"] == "invalid"
