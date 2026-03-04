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
            2027, 12, 31, tzinfo=timezone.utc
        )
        mock_certificate.not_valid_before = datetime(2024, 1, 1)
        mock_certificate.not_valid_after = datetime(2027, 12, 31)

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
        # Mock no certificate found - use MagicMock to avoid async issues
        mock_private_key = MagicMock()
        mock_pkcs12_load.return_value = (mock_private_key, None, [])

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


class TestPrepareCertificate:
    """Test prepare_certificate P12 to PEM conversion."""

    def _make_mock_server(self, cert_p12=b"fake_p12", password="testpass", verify_ssl=False, name="test-server"):
        """Create a mock server object for testing."""
        server = Mock()
        server.cert_p12 = cert_p12
        server.get_cert_password.return_value = password
        server.verify_ssl = verify_ssl
        server.name = name
        return server

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_with_ca_cert(self, mock_pkcs12_load):
        """Test P12 with CA cert produces cert, key, and CA PEM files."""
        mock_private_key = Mock()
        mock_private_key.private_bytes.return_value = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake_cert\n-----END CERTIFICATE-----"
        mock_ca_cert = Mock()
        mock_ca_cert.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake_ca\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [mock_ca_cert])

        server = self._make_mock_server()
        temp_files = []

        result = await TakServerConnectionTester.prepare_certificate(server, temp_files)

        assert result["cert_path"] is not None
        assert result["key_path"] is not None
        assert result["ca_path"] is not None
        assert result["warnings"] == []
        assert len(temp_files) == 3  # cert, key, CA
        # Verify PEM files exist and have .pem extension
        assert result["cert_path"].endswith(".pem")
        assert result["key_path"].endswith(".pem")
        assert result["ca_path"].endswith(".pem")

        # Cleanup
        TakServerConnectionTester.cleanup_temp_files(temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_without_ca_cert(self, mock_pkcs12_load):
        """Test P12 without CA cert produces warning and no CA PEM file."""
        mock_private_key = Mock()
        mock_private_key.private_bytes.return_value = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake_cert\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        server = self._make_mock_server()
        temp_files = []

        result = await TakServerConnectionTester.prepare_certificate(server, temp_files)

        assert result["cert_path"] is not None
        assert result["key_path"] is not None
        assert result["ca_path"] is None
        assert len(result["warnings"]) > 0
        assert "CA certificate" in result["warnings"][0]
        assert len(temp_files) == 2  # cert and key only

        # Cleanup
        TakServerConnectionTester.cleanup_temp_files(temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_without_ca_verify_ssl_enabled(self, mock_pkcs12_load):
        """Test warning is more specific when verify_ssl is enabled and no CA cert."""
        mock_private_key = Mock()
        mock_private_key.private_bytes.return_value = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake_cert\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        server = self._make_mock_server(verify_ssl=True)
        temp_files = []

        result = await TakServerConnectionTester.prepare_certificate(server, temp_files)

        assert result["ca_path"] is None
        assert len(result["warnings"]) > 0
        assert "SSL verification is enabled" in result["warnings"][0]

        # Cleanup
        TakServerConnectionTester.cleanup_temp_files(temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_without_ca_verify_ssl_disabled(self, mock_pkcs12_load):
        """Test warning is reassuring when verify_ssl is disabled and no CA cert."""
        mock_private_key = Mock()
        mock_private_key.private_bytes.return_value = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake_cert\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        server = self._make_mock_server(verify_ssl=False)
        temp_files = []

        result = await TakServerConnectionTester.prepare_certificate(server, temp_files)

        assert result["ca_path"] is None
        assert len(result["warnings"]) > 0
        assert "SSL verification is disabled" in result["warnings"][0]

        # Cleanup
        TakServerConnectionTester.cleanup_temp_files(temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_no_private_key(self, mock_pkcs12_load):
        """Test that missing private key raises an exception."""
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (None, mock_certificate, [])

        server = self._make_mock_server()
        temp_files = []

        with pytest.raises(Exception, match="private key"):
            await TakServerConnectionTester.prepare_certificate(server, temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_no_certificate(self, mock_pkcs12_load):
        """Test that missing certificate raises an exception."""
        mock_private_key = Mock()

        mock_pkcs12_load.return_value = (mock_private_key, None, [])

        server = self._make_mock_server()
        temp_files = []

        with pytest.raises(Exception, match="client certificate"):
            await TakServerConnectionTester.prepare_certificate(server, temp_files)

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    async def test_prepare_certificate_base64_encoded(self, mock_pkcs12_load):
        """Test that base64-encoded cert_p12 is correctly decoded."""
        mock_private_key = Mock()
        mock_private_key.private_bytes.return_value = b"-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----"
        mock_certificate = Mock()
        mock_certificate.public_bytes.return_value = b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        raw_data = b"fake_p12_data"
        encoded_data = base64.b64encode(raw_data).decode("utf-8")
        server = self._make_mock_server(cert_p12=encoded_data)
        temp_files = []

        result = await TakServerConnectionTester.prepare_certificate(server, temp_files)

        assert result["cert_path"] is not None
        # Verify the pkcs12 loader received decoded data
        mock_pkcs12_load.assert_called_once()
        call_args = mock_pkcs12_load.call_args[0]
        assert call_args[0] == raw_data

        # Cleanup
        TakServerConnectionTester.cleanup_temp_files(temp_files)


class TestValidateCertificateDataWarnings:
    """Test validate_certificate_data CA cert warnings."""

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_warns_when_ca_cert_missing(self, mock_pkcs12_load):
        """Test that validation warns when P12 has no CA cert."""
        mock_private_key = Mock()
        mock_certificate = Mock()
        mock_certificate.subject.rfc4514_string.return_value = "CN=test"
        mock_certificate.issuer.rfc4514_string.return_value = "CN=CA"
        mock_certificate.serial_number = 12345
        mock_certificate.not_valid_before_utc = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_certificate.not_valid_after_utc = datetime(2027, 12, 31, tzinfo=timezone.utc)

        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [])

        result = TakServerService.validate_certificate_data(b"fake_data", "password")

        assert result["success"] is True
        assert len(result["warnings"]) > 0
        assert "CA certificate" in result["warnings"][0]

    @patch("services.tak_servers_service.pkcs12.load_key_and_certificates")
    def test_no_warning_when_ca_cert_present(self, mock_pkcs12_load):
        """Test that validation does not warn when P12 has CA cert."""
        mock_private_key = Mock()
        mock_certificate = Mock()
        mock_certificate.subject.rfc4514_string.return_value = "CN=test"
        mock_certificate.issuer.rfc4514_string.return_value = "CN=CA"
        mock_certificate.serial_number = 12345
        mock_certificate.not_valid_before_utc = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_certificate.not_valid_after_utc = datetime(2027, 12, 31, tzinfo=timezone.utc)

        mock_ca_cert = Mock()
        mock_pkcs12_load.return_value = (mock_private_key, mock_certificate, [mock_ca_cert])

        result = TakServerService.validate_certificate_data(b"fake_data", "password")

        assert result["success"] is True
        assert result["warnings"] == []


class TestPytakConnectionWarnings:
    """Test that warnings propagate through the connection test flow."""

    def _make_mock_server(self, protocol="tls", host="tak.example.com", port=8089,
                          verify_ssl=False, cert_p12=b"fake", name="test"):
        """Create a mock server for connection testing."""
        server = Mock()
        server.protocol = protocol
        server.host = host
        server.port = port
        server.verify_ssl = verify_ssl
        server.cert_p12 = cert_p12
        server.name = name
        server.get_cert_password.return_value = "password"
        server.id = 1
        return server

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.TakServerConnectionTester.test_connection_with_timeout")
    @patch("services.tak_servers_service.TakServerConnectionTester.prepare_certificate")
    async def test_propagates_warnings_on_success(self, mock_prepare, mock_test_conn):
        """Test that cert warnings are included in successful connection results."""
        mock_prepare.return_value = {
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
            "ca_path": None,
            "warnings": ["Certificate does not contain a CA certificate."],
        }
        mock_test_conn.return_value = {
            "success": True,
            "message": "Connected",
        }

        server = self._make_mock_server()
        result = await TakServerConnectionTester.test_pytak_connection(server)

        assert result["success"] is True
        assert "warnings" in result
        assert "CA certificate" in result["warnings"][0]

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.TakServerConnectionTester.test_connection_with_timeout")
    @patch("services.tak_servers_service.TakServerConnectionTester.prepare_certificate")
    async def test_propagates_warnings_on_failure(self, mock_prepare, mock_test_conn):
        """Test that cert warnings are included in failed connection results."""
        mock_prepare.return_value = {
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
            "ca_path": None,
            "warnings": ["Certificate does not contain a CA certificate."],
        }
        mock_test_conn.return_value = {
            "success": False,
            "error": "SSL error occurred",
        }

        server = self._make_mock_server()
        result = await TakServerConnectionTester.test_pytak_connection(server)

        assert result["success"] is False
        assert "warnings" in result
        assert "CA certificate" in result["warnings"][0]

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.TakServerConnectionTester.test_connection_with_timeout")
    @patch("services.tak_servers_service.TakServerConnectionTester.prepare_certificate")
    async def test_no_warnings_key_when_no_warnings(self, mock_prepare, mock_test_conn):
        """Test that warnings key is absent when there are no warnings."""
        mock_prepare.return_value = {
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
            "ca_path": "/tmp/ca.pem",
            "warnings": [],
        }
        mock_test_conn.return_value = {
            "success": True,
            "message": "Connected",
        }

        server = self._make_mock_server()
        result = await TakServerConnectionTester.test_pytak_connection(server)

        assert result["success"] is True
        assert "warnings" not in result

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.TakServerConnectionTester.test_connection_with_timeout")
    @patch("services.tak_servers_service.TakServerConnectionTester.prepare_certificate")
    async def test_sets_cafile_when_ca_available(self, mock_prepare, mock_test_conn):
        """Test that PYTAK_TLS_CLIENT_CAFILE is set when CA cert is available."""
        mock_prepare.return_value = {
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
            "ca_path": "/tmp/ca.pem",
            "warnings": [],
        }
        mock_test_conn.return_value = {"success": True, "message": "Connected"}

        server = self._make_mock_server()
        result = await TakServerConnectionTester.test_pytak_connection(server)

        # Check that test_connection_with_timeout was called with a config
        # that includes PYTAK_TLS_CLIENT_CAFILE
        call_args = mock_test_conn.call_args
        config_section = call_args[0][0] if call_args[0] else call_args[1]["config"]
        assert config_section.get("PYTAK_TLS_CLIENT_CAFILE") == "/tmp/ca.pem"

    @pytest.mark.asyncio
    @patch("services.tak_servers_service.TakServerConnectionTester.test_connection_with_timeout")
    @patch("services.tak_servers_service.TakServerConnectionTester.prepare_certificate")
    async def test_no_cafile_when_ca_not_available(self, mock_prepare, mock_test_conn):
        """Test that PYTAK_TLS_CLIENT_CAFILE is not set when no CA cert."""
        mock_prepare.return_value = {
            "cert_path": "/tmp/cert.pem",
            "key_path": "/tmp/key.pem",
            "ca_path": None,
            "warnings": ["Missing CA cert"],
        }
        mock_test_conn.return_value = {"success": True, "message": "Connected"}

        server = self._make_mock_server()
        result = await TakServerConnectionTester.test_pytak_connection(server)

        call_args = mock_test_conn.call_args
        config_section = call_args[0][0] if call_args[0] else call_args[1]["config"]
        assert config_section.get("PYTAK_TLS_CLIENT_CAFILE") is None
