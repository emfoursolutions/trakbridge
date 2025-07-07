# Standard library imports
import os
import base64
import hashlib
import secrets
import logging
import binascii
from typing import Dict, Any, Optional

# Third-party imports
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.exceptions import InvalidKey

# Local application imports
from services.exceptions import EncryptionError, EncryptionKeyError, EncryptionDataError

# Module-level logger
logger = logging.getLogger(__name__)


class EncryptionService:
    """Enhanced service for encrypting and decrypting sensitive configuration data"""

    def __init__(self, master_key: Optional[str] = None):
        self._master_key = master_key or self._get_or_create_master_key()
        self._cipher_suite = None

    def _get_or_create_master_key(self) -> str:
        """Get master key from environment, file, or create a new one"""
        # Priority order: ENV variable -> config file -> generate new

        # Try environment variable first
        master_key = os.environ.get('TB_MASTER_KEY')
        if master_key:
            logger.debug("Master key loaded from environment variable")
            return master_key

        # Try to get Flask app root path if available
        try:
            from flask import current_app
            app_root = current_app.root_path
        except (ImportError, RuntimeError):
            # Fallback to calculating from current file
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Try plain text key file first (most common)
        key_file_paths = [
            os.path.join(app_root, 'secrets', 'tb_master_key'),
        ]
        for key_file_path in key_file_paths:
            if os.path.exists(key_file_path):
                try:
                    with open(key_file_path, 'r') as f:
                        master_key = f.read().strip()
                        if master_key:
                            logger.debug(f"Master key loaded from {key_file_path}")
                            return master_key
                except Exception as e:
                    logger.warning(f"Failed to read key file {key_file_path}: {e}")

        # Generate new key as last resort
        master_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

        # Enhanced warning with actionable instructions
        logger.warning(
            "⚠️  ENCRYPTION KEY WARNING ⚠️\n"
            "No master key found. Generated temporary key for this session.\n"
            "🔧 TO FIX THIS:\n"
            "1. Set environment variable: export TB_MASTER_KEY='your_key_here'\n"
            "2. Or create config file with your key\n"
            "3. Use this generated key if starting fresh: (key logged below)\n"
            "⚠️  Data encrypted with this key will be LOST if app restarts without setting the key!"
        )

        # Only log in development/debug mode
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Generated Master Key: {master_key}")
        else:
            logger.info("Master key generated (not logged for security)")

        return master_key

    def _get_cipher_suite(self) -> Fernet:
        """Get or create the cipher suite for encryption/decryption"""
        if self._cipher_suite is None:
            # Use dynamic salt based on application context
            app_context = os.environ.get('TB_ID', 'tb_default')
            salt = hashlib.sha256(f"{app_context}_salt_2024".encode()).digest()[:16]

            master_key_bytes = self._master_key.encode()

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,  # OWASP recommended minimum
            )

            key = base64.urlsafe_b64encode(kdf.derive(master_key_bytes))
            self._cipher_suite = Fernet(key)

        return self._cipher_suite

    def encrypt_value(self, value: str) -> str:
        """
        Encrypt a sensitive value with enhanced error handling
        """
        if not value:
            return value

        try:
            cipher_suite = self._get_cipher_suite()
            encrypted_bytes = cipher_suite.encrypt(value.encode())
            encrypted_b64 = base64.urlsafe_b64encode(encrypted_bytes).decode()

            # Add versioned prefix for future compatibility
            return f"ENC:v1:{encrypted_b64}"

        except (ValueError, TypeError) as e:
            logger.error(f"Invalid input for encryption: {e}")
            raise EncryptionDataError(f"Invalid input for encryption: {e}") from e
        except (OSError, RuntimeError) as e:
            logger.error(f"System error during encryption: {e}")
            raise EncryptionError(f"System error during encryption: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during encryption: {e}")
            raise EncryptionError(f"Encryption failed: {e}") from e

    def decrypt_value(self, encrypted_value: str) -> str:
        """
        Decrypt a sensitive value with version support
        """
        if not encrypted_value:
            return encrypted_value

        # Check if value is encrypted
        if not encrypted_value.startswith("ENC:"):
            return encrypted_value  # Not encrypted, return as-is

        try:
            # Handle versioned encryption
            parts = encrypted_value.split(":")
            if len(parts) >= 3 and parts[1] == "v1":
                encrypted_b64 = ":".join(parts[2:])  # Handle colons in encrypted data
            else:
                # Legacy format (ENC:data)
                encrypted_b64 = encrypted_value[4:]

            encrypted_bytes = base64.urlsafe_b64decode(encrypted_b64.encode())

            cipher_suite = self._get_cipher_suite()
            decrypted_bytes = cipher_suite.decrypt(encrypted_bytes)

            return decrypted_bytes.decode()

        except Exception as e:
            logger.error(f"Failed to decrypt value: {e}")
            raise EncryptionError(f"Decryption failed: {e}")

    @staticmethod
    def is_encrypted(value: str) -> bool:
        """Check if a value is encrypted"""
        return isinstance(value, str) and value.startswith("ENC:")

    def encrypt_config(self, config: Dict[str, Any], sensitive_fields: list) -> Dict[str, Any]:
        """
        Encrypt sensitive fields in a configuration dictionary with validation
        """
        if not isinstance(config, dict):
            raise ValueError("Config must be a dictionary")

        encrypted_config = config.copy()

        for field_name in sensitive_fields:
            if field_name in encrypted_config:
                value = encrypted_config[field_name]
                if value and not EncryptionService.is_encrypted(str(value)):
                    try:
                        encrypted_config[field_name] = self.encrypt_value(str(value))
                        logger.debug(f"Encrypted field: {field_name}")
                    except Exception as e:
                        logger.error(f"Failed to encrypt field '{field_name}': {e}")
                        raise

        return encrypted_config

    def decrypt_config(self, config: Dict[str, Any], sensitive_fields: list) -> Dict[str, Any]:
        """
        Decrypt sensitive fields in a configuration dictionary with validation
        """
        if not isinstance(config, dict):
            raise ValueError("Config must be a dictionary")

        decrypted_config = config.copy()

        for field_name in sensitive_fields:
            if field_name in decrypted_config:
                value = decrypted_config[field_name]
                if value:
                    try:
                        decrypted_config[field_name] = self.decrypt_value(str(value))
                        logger.debug(f"Decrypted field: {field_name}")
                    except Exception as e:
                        logger.error(f"Failed to decrypt field '{field_name}': {e}")
                        # Keep original value if decryption fails
                        continue

        return decrypted_config

    def rotate_database_keys(self, new_master_key: str) -> Dict[str, Any]:
        """
        Rotate encryption keys for database records (certificate passwords and stream plugin passwords)
        """
        try:
            from models.tak_server import TakServer
            from models.stream import Stream
            from database import db
            from plugins.plugin_manager import get_plugin_manager
            import json

            rotated_count = 0
            errors = []

            # Create new service with new key
            new_service = EncryptionService(new_master_key)

            # 1. Rotate TAK server certificate passwords
            servers = TakServer.query.filter(TakServer.cert_password.isnot(None)).all()
            for server in servers:
                try:
                    # Decrypt with current key
                    old_password = self.decrypt_value(server.cert_password)

                    # Encrypt with new key
                    new_encrypted_password = new_service.encrypt_value(old_password)

                    # Update the database record
                    server.cert_password = new_encrypted_password
                    rotated_count += 1

                except Exception as e:
                    error_msg = f"Failed to rotate certificate password for server {server.name} (ID: {server.id}): {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            # 2. Rotate stream plugin passwords
            streams = Stream.query.filter(Stream.plugin_config.isnot(None)).all()
            plugin_manager = get_plugin_manager()

            for stream in streams:
                try:
                    if not stream.plugin_config:
                        continue

                    # Get plugin metadata to identify sensitive fields
                    metadata = plugin_manager.get_plugin_metadata(stream.plugin_type)
                    if not metadata:
                        continue

                    # Get list of sensitive fields
                    sensitive_fields = []
                    for field_data in metadata.get("config_fields", []):
                        if isinstance(field_data, dict) and field_data.get("sensitive"):
                            sensitive_fields.append(field_data["name"])
                        elif hasattr(field_data, 'sensitive') and field_data.sensitive:
                            sensitive_fields.append(field_data.name)

                    if not sensitive_fields:
                        continue

                    # Get current config and decrypt sensitive fields
                    current_config = stream.get_plugin_config()

                    # Re-encrypt sensitive fields with new key
                    rotated_config = new_service.encrypt_config(current_config, sensitive_fields)

                    # Update the stream's plugin config
                    stream.plugin_config = json.dumps(rotated_config)
                    rotated_count += 1

                except Exception as e:
                    error_msg = f"Failed to rotate plugin passwords for stream {stream.name} (ID: {stream.id}): {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            # Commit all changes
            if rotated_count > 0:
                db.session.commit()

            return {
                "success": True,
                "message": f"Successfully rotated {rotated_count} encrypted passwords (certificates + plugin configs)",
                "rotated_count": rotated_count,
                "errors": errors
            }

        except Exception as e:
            logger.error(f"Database key rotation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "rotated_count": 0,
                "errors": [str(e)]
            }

    def rotate_key(self, new_master_key: str, config_data: Dict[str, Any], sensitive_fields: list) -> Dict[str, Any]:
        """
        Rotate encryption key by decrypting with old key and encrypting with new key
        """
        try:
            # Decrypt with current key
            decrypted_data = self.decrypt_config(config_data, sensitive_fields)

            # Create new service with new key
            new_service = EncryptionService(new_master_key)

            # Encrypt with new key
            rotated_data = new_service.encrypt_config(decrypted_data, sensitive_fields)

            logger.info("Key rotation completed successfully")
            return rotated_data

        except Exception as e:
            logger.error(f"Key rotation failed: {e}")
            raise EncryptionError(f"Key rotation failed: {e}")

    @staticmethod
    def hash_password(password: str, salt: Optional[bytes] = None) -> tuple:
        """
        Hash a password with salt using enhanced security
        """
        if salt is None:
            salt = secrets.token_bytes(32)

        # Use higher iteration count for better security
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=200000,  # Increased from 100k
        )

        hashed = kdf.derive(password.encode())
        return base64.urlsafe_b64encode(hashed).decode(), base64.urlsafe_b64encode(salt).decode()

    def verify_password(self, password: str, hashed_password: str, salt: str) -> bool:
        """
        Verify a password against its hash with timing attack protection
        """
        try:
            salt_bytes = base64.urlsafe_b64decode(salt.encode())
            expected_hash = base64.urlsafe_b64decode(hashed_password.encode())

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt_bytes,
                iterations=200000,  # Match hash_password
            )

            try:
                kdf.verify(password.encode(), expected_hash)
                return True
            except InvalidKey:
                return False

        except (binascii.Error, ValueError, TypeError) as e:
            logger.error(f"Error verifying password: {e}")
            return False

    def health_check(self) -> Dict[str, Any]:
        """
        Perform encryption service health check
        """
        try:
            test_value = "health_check_test"
            encrypted = self.encrypt_value(test_value)
            decrypted = self.decrypt_value(encrypted)

            return {
                "status": "healthy" if decrypted == test_value else "unhealthy",
                "has_master_key": bool(self._master_key),
                "encryption_working": decrypted == test_value,
                "key_source": self._get_key_source()
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "has_master_key": bool(self._master_key),
                "encryption_working": False
            }

    def _get_key_source(self) -> str:
        """Identify where the master key came from"""
        if os.environ.get('TB_MASTER_KEY'):
            return "environment_variable"

        # Try to get Flask app root path if available
        try:
            from flask import current_app
            app_root = current_app.root_path
        except (ImportError, RuntimeError):
            # Fallback to calculating from current file
            app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Try plain text key file first (most common)
        key_file_paths = [
            os.path.join(app_root, 'secrets', 'master_key.txt'),
        ]
        for key_file_path in key_file_paths:
            if os.path.exists(key_file_path):
                try:
                    with open(key_file_path, 'r') as f:
                        master_key = f.read().strip()
                        if master_key:
                            logger.debug(f"Master key loaded from {key_file_path}")
                            return master_key
                except Exception as e:
                    logger.warning(f"Failed to read key file {key_file_path}: {e}")

        return "generated"


# Global encryption service instance
encryption_service = EncryptionService()


def get_encryption_service():
    """Get the encryption service instance - check Flask app context first, then fall back to global"""
    try:
        from flask import current_app, has_app_context
        if has_app_context() and hasattr(current_app, 'encryption_service'):
            return current_app.encryption_service
    except (ImportError, RuntimeError):
        # Flask not available or no app context
        pass
    
    # Fallback to global instance for CLI/standalone use
    return encryption_service


# Enhanced base plugin class with encryption support
class EncryptedConfigMixin:
    """Mixin to add encryption support to plugin configurations"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.encryption_service = EncryptionService()

    def get_sensitive_fields(self) -> list:
        """Get list of sensitive field names from plugin metadata"""

        # Expects self.get_config_fields() to be provided by the base class
        sensitive_fields = []
        config_fields = self.get_config_fields()

        for field in config_fields:
            if hasattr(field, 'sensitive') and field.sensitive:
                sensitive_fields.append(field.name)

        return sensitive_fields

    def encrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt sensitive fields in configuration"""
        sensitive_fields = self.get_sensitive_fields()
        return self.encryption_service.encrypt_config(config, sensitive_fields)

    def decrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt sensitive fields in configuration"""
        sensitive_fields = self.get_sensitive_fields()
        return self.encryption_service.decrypt_config(config, sensitive_fields)

    def get_plugin_config(self) -> Dict[str, Any]:
        """Get plugin configuration with sensitive fields decrypted"""
        if hasattr(self, 'config'):
            return self.decrypt_config(self.config)
        return {}
