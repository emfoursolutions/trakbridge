# ABOUTME: Tests for services/plugin_package_verifier.py — canonical package digest and
# ABOUTME: Ed25519 signature verification for plugin packages (verified/unsigned/invalid).

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.plugin_package_verifier import (
    canonical_package_digest,
    verify_package_signature,
)


@pytest.fixture
def keypair():
    key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    return key, public_b64


def make_package(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def sign_package(root, key):
    digest = canonical_package_digest(root)
    sig = key.sign(digest)
    (root / "signature.sig").write_text(base64.b64encode(sig).decode("ascii") + "\n")


class TestCanonicalPackageDigest:
    def test_deterministic(self, tmp_path):
        files = {"plugin.yaml": b"id: x\n", "x.py": b"print(1)\n"}
        a = make_package(tmp_path / "a", files)
        b = make_package(tmp_path / "b", files)
        assert canonical_package_digest(a) == canonical_package_digest(b)

    def test_independent_of_creation_order(self, tmp_path):
        a = make_package(tmp_path / "a", {"z.py": b"z", "a.py": b"a"})
        b_root = tmp_path / "b"
        b_root.mkdir()
        (b_root / "a.py").write_bytes(b"a")
        (b_root / "z.py").write_bytes(b"z")
        assert canonical_package_digest(a) == canonical_package_digest(b_root)

    def test_content_change_changes_digest(self, tmp_path):
        a = make_package(tmp_path / "a", {"x.py": b"one"})
        b = make_package(tmp_path / "b", {"x.py": b"two"})
        assert canonical_package_digest(a) != canonical_package_digest(b)

    def test_path_change_changes_digest(self, tmp_path):
        a = make_package(tmp_path / "a", {"x.py": b"same"})
        b = make_package(tmp_path / "b", {"y.py": b"same"})
        assert canonical_package_digest(a) != canonical_package_digest(b)

    def test_signature_file_excluded(self, tmp_path):
        a = make_package(tmp_path / "a", {"x.py": b"code"})
        b = make_package(tmp_path / "b", {"x.py": b"code"})
        (b / "signature.sig").write_text("whatever")
        assert canonical_package_digest(a) == canonical_package_digest(b)

    def test_boundary_ambiguity_prevented(self, tmp_path):
        # Same concatenated bytes, different path/content split
        a = make_package(tmp_path / "a", {"ab": b"c"})
        b = make_package(tmp_path / "b", {"a": b"bc"})
        assert canonical_package_digest(a) != canonical_package_digest(b)

    def test_subdirectories_included(self, tmp_path):
        a = make_package(tmp_path / "a", {"sub/helper.py": b"h", "x.py": b"x"})
        b = make_package(tmp_path / "b", {"x.py": b"x"})
        assert canonical_package_digest(a) != canonical_package_digest(b)

    def test_symlink_rejected(self, tmp_path):
        root = make_package(tmp_path / "a", {"x.py": b"x"})
        (root / "link.py").symlink_to(root / "x.py")
        with pytest.raises(ValueError, match="symlink"):
            canonical_package_digest(root)


class TestVerifyPackageSignature:
    def test_signed_package_verified(self, tmp_path, keypair):
        key, public_b64 = keypair
        root = make_package(tmp_path / "p", {"plugin.yaml": b"id: x\n", "x.py": b"1"})
        sign_package(root, key)
        assert verify_package_signature(root, public_key_b64=public_b64) == "verified"

    def test_missing_signature_is_unsigned(self, tmp_path, keypair):
        _, public_b64 = keypair
        root = make_package(tmp_path / "p", {"x.py": b"1"})
        assert verify_package_signature(root, public_key_b64=public_b64) == "unsigned"

    def test_tampered_content_is_invalid(self, tmp_path, keypair):
        key, public_b64 = keypair
        root = make_package(tmp_path / "p", {"x.py": b"good"})
        sign_package(root, key)
        (root / "x.py").write_bytes(b"evil")
        assert verify_package_signature(root, public_key_b64=public_b64) == "invalid"

    def test_garbage_signature_is_invalid(self, tmp_path, keypair):
        _, public_b64 = keypair
        root = make_package(tmp_path / "p", {"x.py": b"1"})
        (root / "signature.sig").write_text("not base64!!!")
        assert verify_package_signature(root, public_key_b64=public_b64) == "invalid"

    def test_wrong_key_is_invalid(self, tmp_path, keypair):
        key, _ = keypair
        other = Ed25519PrivateKey.generate()
        other_pub = base64.b64encode(
            other.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        root = make_package(tmp_path / "p", {"x.py": b"1"})
        sign_package(root, key)
        assert verify_package_signature(root, public_key_b64=other_pub) == "invalid"

    def test_no_embedded_key_treats_signed_as_invalid(self, tmp_path, keypair):
        key, _ = keypair
        root = make_package(tmp_path / "p", {"x.py": b"1"})
        sign_package(root, key)
        assert verify_package_signature(root, public_key_b64=None) == "invalid"

    def test_defaults_to_embedded_key(self, tmp_path, monkeypatch, keypair):
        key, public_b64 = keypair
        monkeypatch.setattr(
            "services.license_service.EMBEDDED_LICENSE_PUBLIC_KEY", public_b64
        )
        root = make_package(tmp_path / "p", {"x.py": b"1"})
        sign_package(root, key)
        assert verify_package_signature(root) == "verified"
