# ABOUTME: Unit tests for services/cert_utils.py — CA extraction and SSL context building.
# ABOUTME: Uses real cryptography primitives to generate test P12 fixtures.

import ssl
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to generate minimal test certificates/P12 blobs
# ---------------------------------------------------------------------------

def _generate_test_p12(include_ca: bool = True):
    """Generate a minimal PKCS#12 blob for testing.

    Returns (p12_bytes, ca_cert_pem) where ca_cert_pem is the PEM of the CA
    included in the P12 (or None when include_ca=False).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    # Generate CA key and cert
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    # Generate client key and cert signed by CA
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Client")])
    client_cert = (
        x509.CertificateBuilder()
        .subject_name(client_name)
        .issuer_name(ca_name)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .sign(ca_key, hashes.SHA256())
    )

    additional = [ca_cert] if include_ca else []
    p12_bytes = pkcs12.serialize_key_and_certificates(
        name=b"test",
        key=client_key,
        cert=client_cert,
        cas=additional,
        encryption_algorithm=serialization.NoEncryption(),
    )
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM) if include_ca else None
    return p12_bytes, ca_pem


# ---------------------------------------------------------------------------
# Tests: extract_ca_from_p12
# ---------------------------------------------------------------------------
class TestExtractCaFromP12:
    def test_extracts_ca_pem_from_p12(self):
        from services.cert_utils import extract_ca_from_p12

        p12_bytes, ca_pem = _generate_test_p12(include_ca=True)
        result = extract_ca_from_p12(p12_bytes, password=None)

        assert result != b""
        assert b"BEGIN CERTIFICATE" in result
        assert result.strip() == ca_pem.strip()

    def test_returns_empty_bytes_when_no_ca_chain(self):
        from services.cert_utils import extract_ca_from_p12

        p12_bytes, _ = _generate_test_p12(include_ca=False)
        result = extract_ca_from_p12(p12_bytes, password=None)

        assert result == b""

    def test_accepts_none_password(self):
        from services.cert_utils import extract_ca_from_p12

        p12_bytes, _ = _generate_test_p12(include_ca=True)
        # Should not raise
        result = extract_ca_from_p12(p12_bytes, password=None)
        assert isinstance(result, bytes)

    def test_accepts_empty_string_password(self):
        from services.cert_utils import extract_ca_from_p12

        p12_bytes, _ = _generate_test_p12(include_ca=True)
        result = extract_ca_from_p12(p12_bytes, password="")
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# Tests: build_ssl_context
# ---------------------------------------------------------------------------
class TestBuildSslContext:
    def _make_stream(self, p12_bytes=None, password="", ca_cert=None):
        """Build a minimal mock stream with a tak_server."""
        tak_server = MagicMock()
        tak_server.cert_p12 = p12_bytes
        tak_server.get_cert_password.return_value = password

        stream = MagicMock()
        stream.tak_server = tak_server
        stream.ca_cert = ca_cert
        return stream

    def test_system_source_returns_default_context(self):
        from services.cert_utils import build_ssl_context

        stream = self._make_stream()
        ctx = build_ssl_context("system", stream=stream)

        assert isinstance(ctx, ssl.SSLContext)

    def test_tak_server_source_loads_ca_from_p12(self):
        from services.cert_utils import build_ssl_context

        p12_bytes, _ = _generate_test_p12(include_ca=True)
        stream = self._make_stream(p12_bytes=p12_bytes, password="")

        # Should not raise — CA from P12 loaded into context
        ctx = build_ssl_context("tak_server", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)

    def test_tak_server_source_no_p12_falls_back_gracefully(self):
        from services.cert_utils import build_ssl_context

        stream = self._make_stream(p12_bytes=None)
        # tak_server.cert_p12 is None — should not raise, just use default bundle
        ctx = build_ssl_context("tak_server", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)

    def test_tak_server_source_no_tak_server_falls_back_gracefully(self):
        from services.cert_utils import build_ssl_context

        stream = MagicMock()
        stream.tak_server = None
        ctx = build_ssl_context("tak_server", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)

    def test_upload_source_loads_ca_from_stream_ca_cert(self):
        from services.cert_utils import build_ssl_context

        _, ca_pem = _generate_test_p12(include_ca=True)
        stream = self._make_stream(ca_cert=ca_pem)
        ctx = build_ssl_context("upload", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)

    def test_upload_source_with_no_ca_cert_uses_system_bundle(self):
        from services.cert_utils import build_ssl_context

        stream = self._make_stream(ca_cert=None)
        # stream.ca_cert is None → fall through to system bundle
        ctx = build_ssl_context("upload", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)

    def test_unknown_source_uses_system_bundle(self):
        from services.cert_utils import build_ssl_context

        stream = self._make_stream()
        ctx = build_ssl_context("unknown_value", stream=stream)
        assert isinstance(ctx, ssl.SSLContext)
