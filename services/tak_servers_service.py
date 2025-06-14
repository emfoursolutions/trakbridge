# =============================================================================
# services/tak_servers_service.py - TAK Server Business Logic Service
# =============================================================================

import base64
import logging
import socket
import ssl
import tempfile
import os
import asyncio
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from configparser import ConfigParser

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
import pytak

# Set up logging
logger = logging.getLogger(__name__)


class TakServerService:
    """Service class for TAK server operations"""

    @staticmethod
    def validate_certificate_data(cert_data, password):
        """
        Validate P12 certificate data and extract certificate information

        Args:
            cert_data (bytes): P12 certificate data
            password (str): Certificate password

        Returns:
            dict: Certificate information or error details
        """
        try:
            # Load the P12 certificate
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                cert_data, password.encode('utf-8') if password else None
            )

            if not certificate:
                return {'success': False, 'error': 'No certificate found in P12 file'}

            # Extract certificate information
            subject = certificate.subject.rfc4514_string()
            issuer = certificate.issuer.rfc4514_string()
            serial_number = str(certificate.serial_number)
            not_valid_before = certificate.not_valid_before.isoformat()
            not_valid_after = certificate.not_valid_after.isoformat()

            # Check if certificate is currently valid
            now = datetime.now(timezone.utc)
            is_expired = certificate.not_valid_after.replace(tzinfo=timezone.utc) < now
            is_not_yet_valid = certificate.not_valid_before.replace(tzinfo=timezone.utc) > now

            cert_info = {
                'subject': subject,
                'issuer': issuer,
                'serial_number': serial_number,
                'not_valid_before': not_valid_before,
                'not_valid_after': not_valid_after,
                'is_expired': is_expired,
                'is_not_yet_valid': is_not_yet_valid,
                'has_private_key': private_key is not None
            }

            return {
                'success': True,
                'cert_info': cert_info,
                'warnings': []
            }

        except ValueError as e:
            # Usually password-related errors
            error_msg = str(e)
            if 'mac verify failure' in error_msg.lower() or 'invalid' in error_msg.lower():
                return {'success': False, 'error': 'Invalid certificate password'}
            return {'success': False, 'error': f'Certificate validation failed: {error_msg}'}
        except Exception as e:
            logger.error(f"Certificate validation error: {str(e)}")
            return {'success': False, 'error': f'Certificate validation failed: {str(e)}'}

    @staticmethod
    def validate_stored_certificate(server):
        """
        Validate certificate stored in server model

        Args:
            server: TakServer model instance

        Returns:
            dict: Validation result with certificate information
        """
        try:
            # Check if certificate data exists
            if not server.cert_p12:
                return {
                    'success': False,
                    'error': 'No certificate data found for this server'
                }

            # Decode the base64 certificate data (if stored as base64)
            try:
                # If cert_p12 is stored as base64 string
                if isinstance(server.cert_p12, str):
                    cert_data = base64.b64decode(server.cert_p12)
                else:
                    # If cert_p12 is stored as binary data
                    cert_data = server.cert_p12
            except Exception as decode_error:
                return {
                    'success': False,
                    'error': f'Failed to decode certificate data: {str(decode_error)}'
                }

            # Parse the PKCS#12 certificate
            try:
                # Get password from database field
                password = server.cert_password.encode('utf-8') if server.cert_password else None

                private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                    cert_data,
                    password
                )

            except Exception as pkcs12_error:
                # If password fails, try with empty password as fallback
                try:
                    private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                        cert_data,
                        None
                    )
                except Exception:
                    return {
                        'success': False,
                        'error': f'Failed to parse PKCS#12 certificate. Invalid password or corrupted certificate: {str(pkcs12_error)}'
                    }

            # Extract certificate information
            cert_info = {}

            if certificate:
                # Subject information
                subject_components = []
                for attribute in certificate.subject:
                    subject_components.append(f"{attribute.oid._name}={attribute.value}")
                cert_info['subject'] = ", ".join(subject_components)

                # Issuer information
                issuer_components = []
                for attribute in certificate.issuer:
                    issuer_components.append(f"{attribute.oid._name}={attribute.value}")
                cert_info['issuer'] = ", ".join(issuer_components)

                # Validity dates (using UTC-aware properties)
                cert_info['not_before'] = certificate.not_valid_before_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
                cert_info['not_after'] = certificate.not_valid_after_utc.strftime('%Y-%m-%d %H:%M:%S UTC')
                cert_info['not_before_iso'] = certificate.not_valid_before_utc.isoformat()
                cert_info['not_after_iso'] = certificate.not_valid_after_utc.isoformat()

                # Check if certificate is currently valid
                now = datetime.now().astimezone()  # Get current time with timezone
                cert_info['is_valid'] = (
                        certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc
                )

                # Days until expiration
                days_until_expiry = (certificate.not_valid_after_utc - now).days
                cert_info['days_until_expiry'] = days_until_expiry
                cert_info['expires_soon'] = days_until_expiry <= 30  # Warning if expires within 30 days

                # Serial number
                cert_info['serial_number'] = str(certificate.serial_number)

                # Common Name (if available)
                try:
                    common_name = certificate.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
                    cert_info['common_name'] = common_name
                except (IndexError, AttributeError):
                    cert_info['common_name'] = None

                # Subject Alternative Names (if available)
                try:
                    san_extension = certificate.extensions.get_extension_for_oid(
                        x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                    san_names = []
                    for name in san_extension.value:
                        san_names.append(name.value)
                    cert_info['subject_alt_names'] = san_names
                except x509.ExtensionNotFound:
                    cert_info['subject_alt_names'] = []

                # Certificate chain information
                cert_info['has_private_key'] = private_key is not None
                cert_info['additional_certificates_count'] = len(additional_certificates) if additional_certificates else 0

                # Fingerprint (SHA-256)
                fingerprint = certificate.fingerprint(hashes.SHA256())
                cert_info['fingerprint_sha256'] = fingerprint.hex(':').upper()
                logger.info(cert_info)

            return {
                'success': True,
                'cert_info': cert_info
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Certificate validation failed: {str(e)}'
            }

    @staticmethod
    def validate_server_data(data):
        """
        Validate TAK server data before creation/update

        Args:
            data: Dictionary containing server data

        Returns:
            dict: Validation result
        """
        errors = []

        # Validate required fields
        if not data.get('name'):
            errors.append("Server name is required")
        if not data.get('host'):
            errors.append("Host address is required")
        if not data.get('port'):
            errors.append("Port is required")

        # Validate port range
        try:
            port = int(data['port'])
            if port < 1 or port > 65535:
                errors.append("Port must be between 1 and 65535")
        except (ValueError, TypeError):
            errors.append("Port must be a valid number")

        if errors:
            return {'success': False, 'errors': errors}

        return {'success': True}

    @staticmethod
    async def test_server_connection(server):
        """
        Test connection to TAK server using pytak

        Args:
            server: TakServer model instance

        Returns:
            dict: Connection test result
        """
        try:
            # Run the async connection test
            result = await TakServerConnectionTester.test_pytak_connection(server)

            if result['success']:
                logger.info(f"Connection test successful for server {server.id}")
            else:
                logger.warning(f"Connection test failed for server {server.id}: {result['error']}")

            return result

        except Exception as e:
            logger.error(f"Connection test error for server {server.id}: {str(e)}")
            return {'success': False, 'error': str(e)}


class TakServerConnectionTester:
    """Handles TAK server connection testing"""

    @staticmethod
    async def test_pytak_connection(server):
        """Test TAK server connection using pytak library"""
        cert_file = None
        temp_files = []

        try:
            # Prepare certificate if provided
            if server.cert_p12:
                cert_file = await TakServerConnectionTester.prepare_certificate(server, temp_files)

            # Create pytak configuration
            config = ConfigParser()
            config_dict = {
                'COT_URL': f"{server.protocol}://{server.host}:{server.port}"
            }

            # Add TLS configuration if needed
            if server.protocol.lower() == 'tls':
                if cert_file:
                    config_dict['PYTAK_TLS_CLIENT_CERT'] = cert_file
                    config_dict['PYTAK_TLS_CLIENT_KEY'] = cert_file  # P12 contains both
                    if server.cert_password:
                        config_dict['PYTAK_TLS_CLIENT_PASSWORD'] = server.cert_password

                if not server.verify_ssl:
                    config_dict['PYTAK_TLS_DONT_VERIFY'] = '1'
                    config_dict['PYTAK_TLS_DONT_CHECK_HOSTNAME'] = '1'

            config['test_section'] = config_dict
            config_section = config['test_section']

            # Test connection with timeout
            connection_result = await TakServerConnectionTester.test_connection_with_timeout(config_section, timeout=10)

            return connection_result

        except Exception as e:
            return {
                'success': False,
                'error': f'Connection test failed: {str(e)}'
            }
        finally:
            # Clean up temporary files
            TakServerConnectionTester.cleanup_temp_files(temp_files)

    @staticmethod
    async def prepare_certificate(server, temp_files):
        """Prepare certificate file for pytak"""
        try:
            # Decode P12 certificate data
            if isinstance(server.cert_p12, str):
                cert_data = base64.b64decode(server.cert_p12)
            else:
                cert_data = server.cert_p12

            # Create temporary P12 file
            with tempfile.NamedTemporaryFile(suffix='.p12', delete=False) as temp_cert:
                temp_cert.write(cert_data)
                temp_cert_path = temp_cert.name
                temp_files.append(temp_cert_path)

            return temp_cert_path

        except Exception as e:
            raise Exception(f"Failed to prepare certificate: {str(e)}")

    @staticmethod
    def create_test_cot_message():
        """Create a simple test COT message"""
        uid = str(uuid.uuid4())

        # Create COT event using ElementTree (pytak standard)
        root = ET.Element("event")
        root.set("version", "2.0")
        root.set("uid", uid)
        root.set("type", "a-f-G-U-C")  # Friendly unit
        root.set("time", pytak.cot_time())
        root.set("start", pytak.cot_time())
        root.set("stale", pytak.cot_time(300))  # 5 minutes
        root.set("how", "h-g-i-g-o")

        # Add point element
        point_attr = {
            "lat": "0.0",
            "lon": "0.0",
            "hae": "0.0",
            "ce": "999999",
            "le": "999999"
        }
        ET.SubElement(root, "point", attrib=point_attr)

        # Add detail element
        detail = ET.SubElement(root, "detail")
        contact = ET.SubElement(detail, "contact")
        contact.set("callsign", "CONNECTION_TEST")
        contact.set("endpoint", "*:-1:stcp")

        remarks = ET.SubElement(detail, "remarks")
        remarks.text = "PyTAK Connection Test"

        return ET.tostring(root)

    @staticmethod
    async def test_connection_with_timeout(config, timeout=10):
        """Test connection with specified timeout"""
        try:
            # Set up connection timeout
            connection_task = asyncio.create_task(TakServerConnectionTester.attempt_connection(config))

            try:
                result = await asyncio.wait_for(connection_task, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                connection_task.cancel()
                return {
                    'success': False,
                    'error': f'Connection timeout after {timeout} seconds'
                }

        except Exception as e:
            return {
                'success': False,
                'error': f'Connection test failed: {str(e)}'
            }

    @staticmethod
    async def attempt_connection(config):
        """Attempt to connect and send test COT"""
        try:
            # Initialize pytak CLITool
            clitool = pytak.CLITool(config)
            await clitool.setup()

            # Create a flag to track success
            connection_success = asyncio.Event()

            # Create test sender
            test_sender = TestSender(clitool.tx_queue, config)

            # Set up success callback
            async def success_callback():
                connection_success.set()

            test_sender.success_callback = success_callback

            # Add sender task
            clitool.add_tasks(set([test_sender]))

            # Start tasks in background
            run_task = asyncio.create_task(clitool.run())

            try:
                # Wait for either success or failure with a reasonable timeout
                await asyncio.wait_for(connection_success.wait(), timeout=5)

                # Cancel the main run task
                run_task.cancel()

                try:
                    await run_task
                except asyncio.CancelledError:
                    pass

                return {
                    'success': True,
                    'message': 'Successfully connected to TAK server and sent test COT message',
                    'details': {
                        'protocol': config.get('COT_URL', '').split('://')[0] if '://' in config.get('COT_URL',
                                                                                                     '') else 'unknown',
                        'tls_enabled': 'tls' in config.get('COT_URL', '').lower(),
                        'certificate_used': bool(config.get('PYTAK_TLS_CLIENT_CERT'))
                    }
                }

            except asyncio.TimeoutError:
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass
                return {
                    'success': False,
                    'error': 'Failed to send test message within timeout period'
                }

        except ssl.SSLError as e:
            return {
                'success': False,
                'error': f'SSL/TLS error: {str(e)}',
                'error_type': 'ssl'
            }
        except socket.error as e:
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'error_type': 'network'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Connection error: {str(e)}',
                'error_type': 'connection'
            }

    @staticmethod
    def cleanup_temp_files(temp_files):
        """Clean up temporary certificate files"""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {temp_file}: {str(e)}")


class TestSender(pytak.QueueWorker):
    """Test sender that sends one COT message and stops"""

    def __init__(self, queue, config):
        super().__init__(queue, config)
        self.message_sent = False
        self.success_callback = None

    async def handle_data(self, data):
        """Handle pre-COT data, serialize to COT Event, then puts on queue."""
        await self.put_queue(data)

    async def run(self):
        """Send test message once"""
        if not self.message_sent:
            test_cot = TakServerConnectionTester.create_test_cot_message()
            await self.handle_data(test_cot)
            self.message_sent = True
            self._logger.info("Test COT message queued for transmission")

            # Signal success after a short delay to allow transmission
            await asyncio.sleep(2)
            if self.success_callback:
                await self.success_callback()