"""
ABOUTME: Unit tests for the EncryptionService master key generation
ABOUTME: Verifies that sensitive key material is not leaked in DEBUG logs

File: tests/unit/test_encryption_service.py

Description:
    Tests for the EncryptionService, particularly focusing on ensuring
    that master keys generated during initialization are not logged
    at DEBUG level, which would expose sensitive cryptographic material
    to log aggregation systems.

Author: Emfour Solutions
Created: 2025-07-04
"""

import logging
import os
from unittest.mock import patch

import pytest

from services.encryption_service import EncryptionService


class TestEncryptionServiceMasterKey:
    """Test suite for master key generation and logging security"""

    def test_generated_master_key_not_leaked_in_debug_logs(self, caplog, tmp_path):
        """
        Test that when a master key is generated (no env var, no file),
        the key value never appears in log records at ANY level.

        This is a security test: DEBUG logs are often collected by
        observability systems, and logging the master key would expose
        the entire encryption keyring.
        """
        # Ensure we capture DEBUG and higher
        caplog.set_level(logging.DEBUG)

        # Mock environment to force key generation path
        with patch.dict(os.environ, {}, clear=False):
            # Remove TB_MASTER_KEY if present
            os.environ.pop("TB_MASTER_KEY", None)

            # Call the static method directly to generate a master key
            # This will log to the logger, which caplog captures
            generated_key = EncryptionService._get_or_create_master_key()

        # Verify a key was generated (non-empty)
        assert generated_key is not None
        assert len(generated_key) > 0

        # Extract all log records at ALL levels
        all_records = caplog.records

        # Check that the generated key value does not appear in any log record
        for record in all_records:
            record_text = record.getMessage()
            assert (
                generated_key not in record_text
            ), f"Master key leaked in {record.levelname} log: {record_text}"

    def test_key_loaded_from_env_var_not_leaked(self, caplog):
        """
        Test that a key loaded from environment variable is logged safely
        (only the source is logged, not the actual key value).
        """
        caplog.set_level(logging.DEBUG)

        test_key = "test-encryption-key-safe-to-log"

        with patch.dict(os.environ, {"TB_MASTER_KEY": test_key}):
            service = EncryptionService()

        # Should have logged "Master key loaded from environment variable"
        # but NOT the key itself
        all_records = caplog.records
        for record in all_records:
            record_text = record.getMessage()
            # The key value must not appear (even though it's a test string)
            assert test_key not in record_text

    def test_service_encryption_functional(self):
        """
        Basic functional test: encryption/decryption works
        (separate from security logging assertions).
        """
        with patch.dict(os.environ, {"TB_MASTER_KEY": "test-key-123"}):
            service = EncryptionService()

        plaintext = "sensitive data"
        encrypted = service.encrypt_value(plaintext)

        # Should be encrypted
        assert encrypted != plaintext
        assert encrypted.startswith("ENC:v1:")

        # Decryption should recover plaintext
        decrypted = service.decrypt_value(encrypted)
        assert decrypted == plaintext
