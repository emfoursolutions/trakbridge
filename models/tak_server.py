"""
File: models/tak_server.py

Description:
    tak_server Model

Author: Emfour Solutions
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Local application imports
from database import TimestampMixin, db
from services.encryption_service import get_encryption_service


class TakServer(db.Model, TimestampMixin):
    __tablename__ = "tak_servers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    protocol = db.Column(db.String(10), nullable=False, default="tls", index=True)

    # TLS Configuration - Updated for P12 support
    cert_p12 = db.Column(db.LargeBinary)  # Store P12 certificate file as binary
    cert_p12_filename = db.Column(db.String(255))  # Store original filename
    cert_password = db.Column(db.String(255))  # Password for P12 certificate (encrypted)
    verify_ssl = db.Column(db.Boolean, default=True)

    # Use back_populates instead of backref to match Stream model
    streams = db.relationship(
        "Stream", back_populates="tak_server", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<TakServer {self.name}>"

    def has_cert_password(self) -> bool:
        """Check if a certificate password is set"""
        return bool(self.cert_password)

    def get_cert_password(self) -> str:
        """Get the decrypted certificate password"""
        if not self.cert_password:
            return ""

        try:
            encryption_service = get_encryption_service()
            return encryption_service.decrypt_value(self.cert_password)
        except Exception as e:
            # Log the error but don't fail - return empty string
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to decrypt certificate password for server {self.id}: {e}")
            return ""

    def set_cert_password(self, password: str):
        """Set the certificate password (encrypted)"""
        if not password:
            self.cert_password = None
            return

        try:
            encryption_service = get_encryption_service()
            self.cert_password = encryption_service.encrypt_value(password)
        except Exception as e:
            # Log the error and raise it
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Failed to encrypt certificate password for server {self.id}: {e}")
            raise

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "verify_ssl": self.verify_ssl,
            "has_certificate": bool(self.cert_p12),
            "cert_filename": self.cert_p12_filename,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def get_pytak_config(self):
        """Generate PyTAK configuration for this server"""
        config = {
            "COT_URL": f"{self.protocol}://{self.host}:{self.port}",
            "PYTAK_TLS_DONT_VERIFY": not self.verify_ssl,
        }

        if self.cert_p12:
            # For PyTAK, we'll need to extract the cert and key from P12
            # This will be handled in the COT service
            config["PYTAK_TLS_CLIENT_P12"] = self.cert_p12
            config["PYTAK_TLS_CLIENT_PASSWORD"] = self.get_cert_password()

        return config
