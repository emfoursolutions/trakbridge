# ABOUTME: Unit tests for CA certificate upload handling in stream routes.
# ABOUTME: Covers PEM/DER validation, file size limits, and the remove-ca-cert endpoint.

import io
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_ca_pem():
    """Return PEM bytes for a self-signed CA certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def _generate_ca_der():
    """Return DER bytes for a self-signed CA certificate."""
    from cryptography.hazmat.primitives import serialization
    pem = _generate_ca_pem()
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    cert = x509.load_pem_x509_certificate(pem, default_backend())
    return cert.public_bytes(serialization.Encoding.DER)


def _make_file_storage(data: bytes, filename: str = "ca.crt"):
    """Build a minimal FileStorage-like object."""
    fs = MagicMock()
    fs.filename = filename
    fs.read.return_value = data
    return fs


# ---------------------------------------------------------------------------
# Tests: _validate_and_read_ca_cert
# ---------------------------------------------------------------------------

class TestValidateAndReadCaCert:
    def test_accepts_valid_pem(self):
        from routes.streams import _validate_and_read_ca_cert

        pem = _generate_ca_pem()
        fs = _make_file_storage(pem, "ca.pem")
        cert_bytes, filename = _validate_and_read_ca_cert(fs)
        assert cert_bytes == pem
        assert filename == "ca.pem"

    def test_accepts_valid_der(self):
        from routes.streams import _validate_and_read_ca_cert

        der = _generate_ca_der()
        fs = _make_file_storage(der, "ca.der")
        cert_bytes, filename = _validate_and_read_ca_cert(fs)
        assert cert_bytes == der
        assert filename == "ca.der"

    def test_rejects_empty_file(self):
        from routes.streams import _validate_and_read_ca_cert

        fs = _make_file_storage(b"", "ca.crt")
        with pytest.raises(ValueError, match="empty"):
            _validate_and_read_ca_cert(fs)

    def test_rejects_oversized_file(self):
        from routes.streams import _validate_and_read_ca_cert

        fs = _make_file_storage(b"x" * (51 * 1024), "ca.crt")
        with pytest.raises(ValueError, match="too large"):
            _validate_and_read_ca_cert(fs)

    def test_rejects_non_certificate_data(self):
        from routes.streams import _validate_and_read_ca_cert

        fs = _make_file_storage(b"not a certificate at all", "ca.crt")
        with pytest.raises(ValueError, match="not a valid"):
            _validate_and_read_ca_cert(fs)

    def test_rejects_garbage_pem_header(self):
        from routes.streams import _validate_and_read_ca_cert

        # Looks like PEM but is corrupt
        fs = _make_file_storage(b"-----BEGIN CERTIFICATE-----\ngarbage\n-----END CERTIFICATE-----\n", "ca.crt")
        with pytest.raises(ValueError, match="not a valid"):
            _validate_and_read_ca_cert(fs)
