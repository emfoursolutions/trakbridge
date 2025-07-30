"""Unit tests for TrakBridge services."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from services.stream_manager import StreamManager
from services.encryption_service import EncryptionService
from services.logging_service import setup_logging
from services.version import get_version, get_version_info


class TestStreamManager:
    """Test the StreamManager service."""

    def test_stream_manager_initialization(self, app):
        """Test StreamManager initialization."""
        with app.app_context():
            stream_manager = StreamManager()
            assert stream_manager is not None

    @patch("services.stream_manager.StreamWorker")
    def test_start_stream(self, mock_worker, app):
        """Test starting a stream."""
        with app.app_context():
            stream_manager = StreamManager()
            mock_worker_instance = Mock()
            mock_worker.return_value = mock_worker_instance

            # Mock a stream
            mock_stream = Mock()
            mock_stream.id = 1
            mock_stream.name = "Test Stream"
            mock_stream.plugin_type = "garmin"

            result = stream_manager._start_stream_worker(mock_stream)
            assert result is True


class TestEncryptionService:
    """Test the EncryptionService."""

    def test_encryption_service_initialization(self, app):
        """Test EncryptionService initialization."""
        with app.app_context():
            encryption_service = EncryptionService()
            assert encryption_service is not None

    def test_encrypt_decrypt(self, app):
        """Test encryption and decryption."""
        with app.app_context():
            encryption_service = EncryptionService()

            # Test data
            test_data = "sensitive information"

            # Encrypt
            encrypted = encryption_service.encrypt(test_data)
            assert encrypted != test_data
            assert encrypted is not None

            # Decrypt
            decrypted = encryption_service.decrypt(encrypted)
            assert decrypted == test_data


class TestVersionService:
    """Test version-related services."""

    def test_get_version(self):
        """Test getting version information."""
        version = get_version()
        assert version is not None
        assert isinstance(version, str)

    def test_get_version_info(self):
        """Test getting detailed version information."""
        version_info = get_version_info()
        assert version_info is not None
        assert isinstance(version_info, dict)
        assert "version" in version_info


class TestLoggingService:
    """Test logging service."""

    def test_setup_logging(self, app):
        """Test logging setup."""
        with app.app_context():
            # This should not raise an exception
            setup_logging(app)
            assert True  # If we get here, setup_logging worked
