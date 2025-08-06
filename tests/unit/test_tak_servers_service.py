"""
ABOUTME: Unit tests for TAK server connection functionality and COT message creation
ABOUTME: Tests certificate validation, connection testing, and XML generation for TAK servers

Unit tests for TrakBridge TAK server services.

File: tests/unit/test_tak_servers_service.py

Description:
    Comprehensive unit tests for the TAK server connection service, including:
    - COT message creation and XML validation
    - Certificate validation and P12 processing
    - Connection testing with various configurations
    - Error handling and edge cases
    - Security validation for XML processing

Author: Emfour Solutions
Created: 2025-08-05
Last Modified: 2025-08-05
Version: 1.0.0
"""

import base64
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from services.tak_servers_service import TakServerConnectionTester, TakServerService


class TestTakServerService:
    """Test the TakServerService class."""

    def test_tak_server_service_initialization(self):
        """Test TakServerService initialization."""
        service = TakServerService()
        assert service is not None

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_validate_certificate_data_valid(self, mock_pkcs12_load):
        """Test certificate validation with valid P12 data."""
        # Mock certificate data
        mock_private_key = Mock()
        mock_certificate = Mock()
        mock_certificate.subject.rfc4514_string.return_value = "CN=test,O=example"
        mock_certificate.issuer.rfc4514_string.return_value = "CN=CA,O=example"
        mock_certificate.serial_number = 12345
        mock_certificate.not_valid_before_utc = datetime(
            2024, 1, 1, tzinfo=timezone.utc
        )
        mock_certificate.not_valid_after_utc = datetime(
            2025, 12, 31, tzinfo=timezone.utc
        )
        mock_certificate.not_valid_before = datetime(2024, 1, 1)
        mock_certificate.not_valid_after = datetime(2025, 12, 31)

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        # Test valid certificate
        cert_data = b"fake_certificate_data"
        password = "test_password"

        result = TakServerService.validate_certificate_data(cert_data, password)

        assert result is not None
        assert result["success"] is True
        assert "cert_info" in result
        cert_info = result["cert_info"]
        assert cert_info["has_private_key"] is True
        assert cert_info["is_expired"] is False
        assert cert_info["subject"] == "CN=test,O=example"
        mock_pkcs12_load.assert_called_once_with(cert_data, b"test_password")

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_validate_certificate_data_invalid_password(self, mock_pkcs12_load):
        """Test certificate validation with invalid password."""
        # Mock password error
        mock_pkcs12_load.side_effect = ValueError("mac verify failure")

        cert_data = b"fake_certificate_data"
        password = "wrong_password"

        result = TakServerService.validate_certificate_data(cert_data, password)

        assert result["success"] is False
        assert result["error"] == "Invalid certificate password"

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_validate_certificate_data_no_certificate(self, mock_pkcs12_load):
        """Test certificate validation with no certificate in P12."""
        # Mock no certificate found
        mock_pkcs12_load.return_value = (Mock(), None, [])

        cert_data = b"fake_certificate_data"
        password = "test_password"

        result = TakServerService.validate_certificate_data(cert_data, password)

        assert result["success"] is False
        assert result["error"] == "No certificate found in P12 file"

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_validate_certificate_data_general_error(self, mock_pkcs12_load):
        """Test certificate validation with general error."""
        # Mock general error
        mock_pkcs12_load.side_effect = Exception("General error")

        cert_data = b"fake_certificate_data"
        password = "test_password"

        result = TakServerService.validate_certificate_data(cert_data, password)

        assert result["success"] is False
        assert "Certificate validation failed" in result["error"]


class TestTakServerConnectionTester:
    """Test the TakServerConnectionTester class."""

    def test_create_test_cot_message(self):
        """Test COT message creation and XML structure."""
        cot_xml = TakServerConnectionTester.create_test_cot_message()

        # Verify it's bytes
        assert isinstance(cot_xml, bytes)

        # Parse and validate XML structure
        root = ET.fromstring(cot_xml)

        # Verify root element
        assert root.tag == "event"
        assert root.get("version") == "2.0"
        assert root.get("type") == "a-f-G-U-C"
        assert root.get("how") == "h-g-i-g-o"

        # Verify UID is a valid UUID
        uid = root.get("uid")
        assert uid is not None
        uuid.UUID(uid)  # This will raise ValueError if invalid

        # Verify timestamps are present
        assert root.get("time") is not None
        assert root.get("start") is not None
        assert root.get("stale") is not None

        # Verify point element
        point = root.find("point")
        assert point is not None
        assert point.get("lat") == "0.0"
        assert point.get("lon") == "0.0"
        assert point.get("hae") == "0.0"
        assert point.get("ce") == "999999"
        assert point.get("le") == "999999"

        # Verify detail element
        detail = root.find("detail")
        assert detail is not None

        # Verify contact element
        contact = detail.find("contact")
        assert contact is not None
        assert contact.get("callsign") == "CONNECTION_TEST"
        assert contact.get("endpoint") == "*:-1:stcp"

        # Verify remarks element
        remarks = detail.find("remarks")
        assert remarks is not None
        assert remarks.text == "PyTAK Connection Test"

    def test_create_test_cot_message_uniqueness(self):
        """Test that each COT message has a unique UID."""
        cot_xml1 = TakServerConnectionTester.create_test_cot_message()
        cot_xml2 = TakServerConnectionTester.create_test_cot_message()

        root1 = ET.fromstring(cot_xml1)
        root2 = ET.fromstring(cot_xml2)

        uid1 = root1.get("uid")
        uid2 = root2.get("uid")

        assert uid1 != uid2

    def test_create_test_cot_message_xml_safety(self):
        """Test that COT message creation is safe from XML vulnerabilities."""
        cot_xml = TakServerConnectionTester.create_test_cot_message()

        # Verify it's well-formed XML
        root = ET.fromstring(cot_xml)

        # Verify no suspicious content
        xml_string = cot_xml.decode("utf-8")
        assert "<!DOCTYPE" not in xml_string  # No DTD declarations
        assert "<!ENTITY" not in xml_string  # No entity declarations

    def test_connection_tester_class_exists(self):
        """Test that TakServerConnectionTester class exists and can be instantiated."""
        # Since it's a class with static methods, we just verify it exists
        assert TakServerConnectionTester is not None

        # Verify key methods exist
        assert hasattr(TakServerConnectionTester, "create_test_cot_message")
        assert hasattr(TakServerConnectionTester, "test_connection_with_timeout")
        assert hasattr(TakServerConnectionTester, "attempt_connection")
        assert hasattr(TakServerConnectionTester, "cleanup_temp_files")

    def test_cot_message_xml_attributes(self):
        """Test specific XML attributes in COT message."""
        cot_xml = TakServerConnectionTester.create_test_cot_message()
        root = ET.fromstring(cot_xml)

        # Test specific attribute values for TAK compatibility
        assert root.get("version") == "2.0"
        assert root.get("type") == "a-f-G-U-C"  # Friendly unit
        assert root.get("how") == "h-g-i-g-o"  # GPS input

        # Test point attributes
        point = root.find("point")
        assert point.get("lat") == "0.0"
        assert point.get("lon") == "0.0"
        assert point.get("hae") == "0.0"  # Height above ellipsoid
        assert point.get("ce") == "999999"  # Circular error
        assert point.get("le") == "999999"  # Linear error

    def test_cot_message_structure_validation(self):
        """Test COT message has correct structure for TAK."""
        cot_xml = TakServerConnectionTester.create_test_cot_message()
        root = ET.fromstring(cot_xml)

        # Must have exactly one point element
        points = root.findall("point")
        assert len(points) == 1

        # Must have exactly one detail element
        details = root.findall("detail")
        assert len(details) == 1

        # Detail must have contact and remarks
        detail = details[0]
        contacts = detail.findall("contact")
        remarks = detail.findall("remarks")

        assert len(contacts) == 1
        assert len(remarks) == 1

        # Contact must have required attributes
        contact = contacts[0]
        assert contact.get("callsign") is not None
        assert contact.get("endpoint") is not None

    @patch("services.tak_servers_service.pytak.cot_time")
    def test_cot_message_timestamps(self, mock_cot_time):
        """Test COT message timestamp generation."""
        # Mock pytak.cot_time to return predictable values
        mock_cot_time.side_effect = [
            "20250805T120000Z",
            "20250805T120000Z",
            "20250805T120500Z",
        ]

        cot_xml = TakServerConnectionTester.create_test_cot_message()
        root = ET.fromstring(cot_xml)

        # Verify timestamps are set
        assert root.get("time") == "20250805T120000Z"
        assert root.get("start") == "20250805T120000Z"
        assert root.get("stale") == "20250805T120500Z"

        # Verify pytak.cot_time was called correctly
        assert mock_cot_time.call_count == 3

    def test_cleanup_temp_files_method_exists(self):
        """Test that cleanup_temp_files method exists."""
        assert hasattr(TakServerConnectionTester, "cleanup_temp_files")

        # Test that it can be called without error (with empty list)
        TakServerConnectionTester.cleanup_temp_files([])

    @patch("os.path.exists")
    @patch("os.unlink")
    def test_cleanup_temp_files(self, mock_unlink, mock_exists):
        """Test cleanup of temporary files."""
        mock_exists.return_value = True
        temp_files = ["/tmp/test1.p12", "/tmp/test2.p12"]

        TakServerConnectionTester.cleanup_temp_files(temp_files)

        # Verify files were checked and deleted
        assert mock_exists.call_count == 2
        assert mock_unlink.call_count == 2
