# ABOUTME: Shared TLS certificate utilities for output plugins.
# ABOUTME: Provides CA extraction from P12 blobs and SSL context construction.

import ssl
from typing import Optional


def extract_ca_from_p12(p12_bytes: bytes, password: Optional[str]) -> bytes:
    """Extract the CA certificate chain from a PKCS#12 blob as PEM bytes.

    Returns the concatenated PEM bytes of all additional certificates (CA chain)
    found in the P12. Returns empty bytes if no CA chain is present.
    """
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.hazmat.primitives.serialization import Encoding

    password_bytes = password.encode() if password else None
    _, _, additional_certs = pkcs12.load_key_and_certificates(
        p12_bytes, password_bytes
    )
    if not additional_certs:
        return b""
    return b"".join(cert.public_bytes(Encoding.PEM) for cert in additional_certs)


def build_ssl_context(
    ca_source: str,
    stream,
) -> ssl.SSLContext:
    """Build an SSLContext for verifying a remote TLS endpoint.

    ca_source values:
      'system'     — Use Python's default system CA bundle (no extra config).
      'tak_server' — Extract the CA from the TAK server P12 stored on the stream.
      'upload'     — Load the CA cert uploaded to stream.ca_cert (PEM bytes).

    stream must have a .tak_server relationship with cert_p12 and get_cert_password(),
    and a .ca_cert attribute containing uploaded PEM bytes (or None).
    """
    ctx = ssl.create_default_context()

    if ca_source == "tak_server":
        tak_server = stream.tak_server
        if tak_server and tak_server.cert_p12:
            ca_pem = extract_ca_from_p12(
                tak_server.cert_p12, tak_server.get_cert_password()
            )
            if ca_pem:
                ctx.load_verify_locations(cadata=ca_pem.decode("ascii"))
    elif ca_source == "upload" and stream.ca_cert:
        ctx.load_verify_locations(cadata=stream.ca_cert.decode("ascii"))
    # 'system' — ctx already uses the system bundle, nothing to do

    return ctx
