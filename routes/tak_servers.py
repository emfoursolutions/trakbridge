# =============================================================================
# routes/tak_servers.py - TAK Server Routes (Updated with Certificate Verification)
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from database import db
from models.tak_server import TakServer
import base64
import logging
import socket
import ssl
import tempfile
import os
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography import x509
from datetime import datetime, timezone
import traceback
import asyncio
from configparser import ConfigParser
import uuid
import xml.etree.ElementTree as ET
import pytak

# Set up logging
logger = logging.getLogger(__name__)

bp = Blueprint('tak_servers', __name__)


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


@bp.route('/validate-certificate', methods=['POST'])
def validate_certificate():
    """Validate uploaded P12 certificate"""
    try:
        # Handle file upload
        if 'cert_file' not in request.files:
            return jsonify({'success': False, 'error': 'No certificate file provided'}), 400

        cert_file = request.files['cert_file']
        if not cert_file or not cert_file.filename:
            return jsonify({'success': False, 'error': 'No certificate file selected'}), 400

        # Get password
        password = request.form.get('password', '')

        # Read certificate data
        cert_data = cert_file.read()
        if not cert_data:
            return jsonify({'success': False, 'error': 'Certificate file is empty'}), 400

        # Validate file size (max 5MB)
        if len(cert_data) > 5 * 1024 * 1024:
            return jsonify({'success': False, 'error': 'Certificate file too large (max 5MB)'}), 400

        # Validate certificate
        result = validate_certificate_data(cert_data, password)

        if result['success']:
            logger.info(f"Certificate validation successful for {cert_file.filename}")
        else:
            logger.warning(f"Certificate validation failed for {cert_file.filename}: {result['error']}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"Certificate validation endpoint error: {str(e)}")
        return jsonify({'success': False, 'error': f'Validation failed: {str(e)}'}), 500

@bp.route('/<int:server_id>/validate-certificate', methods=['POST'])
def validate_stored_certificate(server_id):
    try:
        server = TakServer.query.get_or_404(server_id)

        # Check if certificate data exists
        if not server.cert_p12:
            return jsonify({
                'success': False,
                'error': 'No certificate data found for this server'
            }), 400

        # Decode the base64 certificate data (if stored as base64)
        try:
            # If cert_p12 is stored as base64 string
            if isinstance(server.cert_p12, str):
                cert_data = base64.b64decode(server.cert_p12)
            else:
                # If cert_p12 is stored as binary data
                cert_data = server.cert_p12
        except Exception as decode_error:
            return jsonify({
                'success': False,
                'error': f'Failed to decode certificate data: {str(decode_error)}'
            }), 400

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
                return jsonify({
                    'success': False,
                    'error': f'Failed to parse PKCS#12 certificate. Invalid password or corrupted certificate: {str(pkcs12_error)}'
                }), 400

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
        return jsonify({
            'success': True,
            'cert_info': cert_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Certificate validation failed: {str(e)}'
        }), 500

@bp.route('/')
def list_tak_servers():
    """List all TAK servers"""
    from models.tak_server import TakServer
    servers = TakServer.query.all()
    return render_template('tak_servers.html', servers=servers)


@bp.route('/create', methods=['GET', 'POST'])
def create_tak_server():
    """Create a new TAK server"""
    if request.method == 'GET':
        return render_template('create_tak_server.html')

    from models.tak_server import TakServer

    try:
        # Handle file upload differently for form vs JSON
        if request.is_json:
            data = request.get_json()
            cert_p12_data = None
            cert_filename = None

            # Handle base64 encoded certificate from JSON
            if data.get('cert_p12_base64'):
                try:
                    cert_p12_data = base64.b64decode(data['cert_p12_base64'])
                    cert_filename = data.get('cert_p12_filename', 'certificate.p12')
                    logger.info(f"Decoded certificate data: {len(cert_p12_data)} bytes")
                except Exception as e:
                    logger.error(f"Failed to decode certificate: {str(e)}")
                    return jsonify({'success': False, 'error': f'Invalid certificate data: {str(e)}'}), 400
        else:
            data = request.form
            cert_p12_data = None
            cert_filename = None

            # Handle file upload from form
            if 'cert_p12_file' in request.files:
                cert_file = request.files['cert_p12_file']
                if cert_file and cert_file.filename:
                    cert_p12_data = cert_file.read()
                    cert_filename = cert_file.filename
                    logger.info(f"Read certificate file: {cert_filename}, {len(cert_p12_data)} bytes")

        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get('verify_ssl', True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() in ['true', 'on', '1']
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        # Validate required fields
        if not data.get('name'):
            raise ValueError("Server name is required")
        if not data.get('host'):
            raise ValueError("Host address is required")
        if not data.get('port'):
            raise ValueError("Port is required")

        # Validate port range
        port = int(data['port'])
        if port < 1 or port > 65535:
            raise ValueError("Port must be between 1 and 65535")

        # Validate certificate if provided
        if cert_p12_data:
            cert_password = data.get('cert_password', '')
            validation_result = validate_certificate_data(cert_p12_data, cert_password)
            if not validation_result['success']:
                raise ValueError(f"Certificate validation failed: {validation_result['error']}")

        # Log the data being inserted
        logger.info(f"Creating TAK server: {data.get('name')} at {data.get('host')}:{port}")
        logger.info(f"Protocol: {data.get('protocol', 'tls')}, SSL Verify: {verify_ssl}")
        logger.info(f"Certificate: {'Yes' if cert_p12_data else 'No'}")

        server = TakServer(
            name=data['name'],
            host=data['host'],
            port=port,
            protocol=data.get('protocol', 'tls'),
            cert_p12=cert_p12_data,
            cert_p12_filename=cert_filename,
            cert_password=data.get('cert_password', ''),
            verify_ssl=verify_ssl
        )

        # Add to session and attempt commit
        db.session.add(server)
        db.session.flush()  # This will raise an exception if there's a constraint violation
        db.session.commit()

        logger.info(f"Successfully created TAK server with ID: {server.id}")

        if request.is_json:
            return jsonify({'success': True, 'server_id': server.id})
        else:
            flash('TAK Server created successfully', 'success')
            return redirect(url_for('tak_servers.list_tak_servers'))

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Validation error: {str(e)}', 'error')
            return redirect(url_for('tak_servers.create_tak_server'))

    except Exception as e:
        logger.error(f"Database error creating TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500
        else:
            flash(f'Error creating TAK server: {str(e)}', 'error')
            return redirect(url_for('tak_servers.create_tak_server'))


@bp.route('/<int:server_id>')
def view_tak_server(server_id):
    """View TAK server details"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)
    return render_template('tak_server_detail.html', server=server)


@bp.route('/<int:server_id>/edit', methods=['GET', 'POST'])
def edit_tak_server(server_id):
    """Edit TAK server"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)

    if request.method == 'GET':
        return render_template('edit_tak_server.html', server=server)

    try:
        # Handle file upload differently for form vs JSON
        if request.is_json:
            data = request.get_json()
            cert_p12_data = server.cert_p12  # Keep existing if not updated
            cert_filename = server.cert_p12_filename

            # Handle base64 encoded certificate from JSON
            if data.get('cert_p12_base64'):
                try:
                    cert_p12_data = base64.b64decode(data['cert_p12_base64'])
                    cert_filename = data.get('cert_p12_filename', 'certificate.p12')
                except Exception as e:
                    return jsonify({'success': False, 'error': f'Invalid certificate data: {str(e)}'}), 400
            elif data.get('remove_certificate'):
                cert_p12_data = None
                cert_filename = None
        else:
            data = request.form
            cert_p12_data = server.cert_p12  # Keep existing if not updated
            cert_filename = server.cert_p12_filename

            # Handle file upload from form
            if 'cert_p12_file' in request.files:
                cert_file = request.files['cert_p12_file']
                if cert_file and cert_file.filename:
                    cert_p12_data = cert_file.read()
                    cert_filename = cert_file.filename

            # Handle certificate removal
            if data.get('remove_certificate') == 'on':
                cert_p12_data = None
                cert_filename = None

        # Handle verify_ssl for both form data (string) and JSON data (boolean)
        verify_ssl_value = data.get('verify_ssl', True)
        if isinstance(verify_ssl_value, str):
            verify_ssl = verify_ssl_value.lower() in ['true', 'on', '1']
        elif isinstance(verify_ssl_value, bool):
            verify_ssl = verify_ssl_value
        else:
            verify_ssl = True  # Default to True

        # Validate required fields
        if not data.get('name'):
            raise ValueError("Server name is required")
        if not data.get('host'):
            raise ValueError("Host address is required")
        if not data.get('port'):
            raise ValueError("Port is required")

        # Validate port range
        port = int(data['port'])
        if port < 1 or port > 65535:
            raise ValueError("Port must be between 1 and 65535")

        # Validate certificate if provided and changed
        if cert_p12_data and cert_p12_data != server.cert_p12:
            cert_password = data.get('cert_password', '')
            validation_result = validate_certificate_data(cert_p12_data, cert_password)
            if not validation_result['success']:
                raise ValueError(f"Certificate validation failed: {validation_result['error']}")

        server.name = data['name']
        server.host = data['host']
        server.port = port
        server.protocol = data.get('protocol', 'tls')
        server.cert_p12 = cert_p12_data
        server.cert_p12_filename = cert_filename
        server.cert_password = data.get('cert_password', '')
        server.verify_ssl = verify_ssl

        db.session.flush()  # Check for constraint violations
        db.session.commit()

        logger.info(f"Successfully updated TAK server ID: {server_id}")

        if request.is_json:
            return jsonify({'success': True})
        else:
            flash('TAK Server updated successfully', 'success')
            return redirect(url_for('tak_servers.view_tak_server', server_id=server_id))

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': str(e)}), 400
        else:
            flash(f'Validation error: {str(e)}', 'error')
            return redirect(url_for('tak_servers.edit_tak_server', server_id=server_id))

    except Exception as e:
        logger.error(f"Database error updating TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        if request.is_json:
            return jsonify({'success': False, 'error': f'Database error: {str(e)}'}), 500
        else:
            flash(f'Error updating TAK server: {str(e)}', 'error')
            return redirect(url_for('tak_servers.edit_tak_server', server_id=server_id))


@bp.route('/<int:server_id>/delete', methods=['DELETE'])
def delete_tak_server(server_id):
    """Delete TAK server"""
    try:
        from models.tak_server import TakServer
        server = TakServer.query.get_or_404(server_id)

        if server.streams:
            return jsonify({
                'success': False,
                'error': 'Cannot delete server with associated streams'
            }), 400

        db.session.delete(server)
        db.session.commit()

        logger.info(f"Successfully deleted TAK server ID: {server_id}")
        return jsonify({'success': True, 'message': 'TAK Server deleted'})

    except Exception as e:
        logger.error(f"Error deleting TAK server: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/<int:server_id>/test', methods=['POST'])
def test_tak_server(server_id):
    """Test connection to existing TAK server using pytak"""
    from models.tak_server import TakServer
    server = TakServer.query.get_or_404(server_id)

    try:
        # Run the async connection test
        result = asyncio.run(test_pytak_connection(server))

        if result['success']:
            logger.info(f"PyTAK connection test successful for server {server_id}")
        else:
            logger.warning(f"PyTAK connection test failed for server {server_id}: {result['error']}")

        return jsonify(result)

    except Exception as e:
        logger.error(f"PyTAK connection test error for server {server_id}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


async def test_pytak_connection(server):
    """Test TAK server connection using pytak library"""
    cert_file = None
    temp_files = []

    try:
        # Prepare certificate if provided
        if server.cert_p12:
            cert_file = await prepare_certificate(server, temp_files)

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
        connection_result = await test_connection_with_timeout(config_section, timeout=10)

        return connection_result

    except Exception as e:
        return {
            'success': False,
            'error': f'Connection test failed: {str(e)}'
        }
    finally:
        # Clean up temporary files
        cleanup_temp_files(temp_files)


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
            test_cot = create_test_cot_message()
            await self.handle_data(test_cot)
            self.message_sent = True
            self._logger.info("Test COT message queued for transmission")

            # Signal success after a short delay to allow transmission
            await asyncio.sleep(2)
            if self.success_callback:
                await self.success_callback()


async def test_connection_with_timeout(config, timeout=10):
    """Test connection with specified timeout"""

    try:
        # Set up connection timeout
        connection_task = asyncio.create_task(attempt_connection(config))

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


async def attempt_connection(config):
    """Attempt to connect and send test COT"""
    import pytak

    try:
        # Initialize pytak CLITool
        clitool = pytak.CLITool(config)
        await clitool.setup()

        # Create a flag to track success
        connection_success = asyncio.Event()
        connection_error = None

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


def cleanup_temp_files(temp_files):
    """Clean up temporary certificate files"""
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file {temp_file}: {str(e)}")


# Alternative simpler version using basic socket connection if pytak is too complex
async def test_basic_tak_connection(server):
    """Basic socket-level connection test as fallback"""
    import socket
    import ssl

    temp_files = []

    try:
        if server.protocol.lower() == 'tls':
            # Test TLS connection
            context = ssl.create_default_context()

            if not server.verify_ssl:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

            if server.cert_p12 and server.cert_password:
                # Load client certificate if provided
                cert_file = await prepare_certificate(server, temp_files)
                context.load_cert_chain(cert_file, password=server.cert_password)

            with socket.create_connection((server.host, server.port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=server.host) as ssock:
                    # Connection successful
                    return {
                        'success': True,
                        'message': 'Successfully established TLS connection to TAK server',
                        'details': {
                            'protocol': 'tls',
                            'cipher': ssock.cipher(),
                            'peer_cert': bool(ssock.getpeercert())
                        }
                    }
        else:
            # Test TCP connection
            with socket.create_connection((server.host, server.port), timeout=10) as sock:
                return {
                    'success': True,
                    'message': 'Successfully established TCP connection to TAK server',
                    'details': {
                        'protocol': 'tcp'
                    }
                }

    except socket.timeout:
        return {
            'success': False,
            'error': 'Connection timeout - server may be unreachable',
            'error_type': 'timeout'
        }
    except socket.gaierror as e:
        return {
            'success': False,
            'error': f'DNS resolution failed: {str(e)}',
            'error_type': 'dns'
        }
    except ConnectionRefusedError:
        return {
            'success': False,
            'error': 'Connection refused - server may not be running or port blocked',
            'error_type': 'refused'
        }
    except ssl.SSLError as e:
        return {
            'success': False,
            'error': f'SSL/TLS error: {str(e)}',
            'error_type': 'ssl'
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Connection failed: {str(e)}',
            'error_type': 'general'
        }
    finally:
        cleanup_temp_files(temp_files)