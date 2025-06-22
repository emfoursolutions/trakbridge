# =============================================================================
# services/cot_service_pytak.py - Fixed COT Service with PyTAK Integration
# =============================================================================

import asyncio
import ssl
import tempfile
import os
from lxml import etree
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
import logging

# PyTAK imports
try:
    import pytak

    PYTAK_AVAILABLE = True
except ImportError:
    PYTAK_AVAILABLE = False
    logging.warning("PyTAK not available. Install with: pip install pytak")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

logger = logging.getLogger(__name__)


class EnhancedCOTService:
    """Enhanced COT service with PyTAK integration and fallback to custom implementation"""

    COT_TYPES = {
        'friendly_ground': 'a-f-G-U-C',
        'friendly_air': 'a-f-A-C',
        'friendly_sea': 'a-f-S-C',
        'neutral_ground': 'a-n-G',
        'unknown_ground': 'a-u-G',
        'hostile_ground': 'a-h-G',
        'pending_ground': 'a-p-G',
        'assumed_friend': 'a-a-G',
    }

    def __init__(self, use_pytak: bool = True):
        """
        Initialize COT service

        Args:
            use_pytak: Whether to use PyTAK library when available
        """
        self.use_pytak = use_pytak and PYTAK_AVAILABLE

        if self.use_pytak:
            logger.debug("Using PyTAK library for COT transmission")
        else:
            logger.debug("Using custom COT transmission implementation")

    def _safe_float_convert(self, value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float, handling various input types"""
        if value is None:
            return default

        # Handle datetime objects (return default)
        if isinstance(value, datetime):
            logger.warning(f"Datetime object passed where float expected: {value}, using default {default}")
            return default

        try:
            return float(value)
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not convert {value} (type: {type(value)}) to float: {e}, using default {default}")
            return default

    def _validate_location_data(self, location: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean location data to prevent type errors"""
        cleaned_location = {}

        for key, value in location.items():
            if isinstance(value, datetime) and key not in ['timestamp']:
                logger.warning(f"Found datetime object in unexpected field '{key}': {value}")
                # Convert datetime to timestamp if it's not in timestamp field
                if key in ['lat', 'lon', 'altitude', 'hae', 'accuracy', 'ce', 'linear_error', 'le', 'speed', 'heading',
                           'course']:
                    cleaned_location[key] = 0.0  # Use default for numeric fields
                else:
                    cleaned_location[key] = str(value)  # Convert to string for other fields
            else:
                cleaned_location[key] = value

        return cleaned_location

    async def create_cot_events(self, locations: List[Dict[str, Any]],
                                cot_type: str = "a-f-G-U-C",
                                stale_time: int = 300) -> List[bytes]:
        """
        Create COT events from location data

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier
            stale_time: Time in seconds before event becomes stale

        Returns:
            List of COT events as XML bytes
        """
        if self.use_pytak:
            return await self._create_pytak_events(locations, cot_type, stale_time)
        else:
            return await self._create_custom_events(locations, cot_type, stale_time)

    async def _create_pytak_events(self, locations: List[Dict[str, Any]],
                                   cot_type: str, stale_time: int) -> List[bytes]:
        """Create COT events using PyTAK's XML generation"""
        events = []

        for location in locations:
            try:
                # Validate and clean location data first
                cleaned_location = self._validate_location_data(location)

                # Debug: Log the location data to see what we're working with
                logger.debug(f"Processing location: {cleaned_location}")

                # Parse timestamp - ensure we get a proper datetime object
                if 'timestamp' in cleaned_location and cleaned_location['timestamp']:
                    if isinstance(cleaned_location['timestamp'], str):
                        try:
                            event_time = datetime.fromisoformat(cleaned_location['timestamp'].replace('Z', '+00:00'))
                            # Remove timezone info to avoid issues
                            if event_time.tzinfo is not None:
                                event_time = event_time.replace(tzinfo=None)
                        except ValueError as e:
                            logger.warning(f"Could not parse timestamp '{cleaned_location['timestamp']}': {e}")
                            event_time = datetime.now(timezone.utc)
                    elif isinstance(cleaned_location['timestamp'], datetime):
                        event_time = cleaned_location['timestamp']
                        # Remove timezone info to avoid issues
                        if event_time.tzinfo is not None:
                            event_time = event_time.replace(tzinfo=None)
                    else:
                        logger.warning(f"Unexpected timestamp type: {type(cleaned_location['timestamp'])}")
                        event_time = datetime.now(timezone.utc)
                else:
                    event_time = datetime.now(timezone.utc)

                # Ensure event_time is a proper datetime object
                if not isinstance(event_time, datetime):
                    logger.error(f"event_time is not a datetime object: {type(event_time)}")
                    event_time = datetime.now(timezone.utc)

                # Create COT event data dictionary with safe conversions
                event_data = {
                    'uid': str(location['uid']),
                    'type': str(cot_type),
                    'time': event_time,
                    'start': event_time,
                    'stale': event_time + timedelta(seconds=int(stale_time)),
                    'how': 'm-g',  # Standard PyTAK "how" value
                    'lat': self._safe_float_convert(location['lat']),
                    'lon': self._safe_float_convert(location['lon']),
                    'hae': self._safe_float_convert(location.get('altitude', location.get('hae', 0.0))),
                    'ce': self._safe_float_convert(location.get('accuracy', location.get('ce', 999999)), 999999),
                    'le': self._safe_float_convert(location.get('linear_error', location.get('le', 999999)), 999999),
                    'callsign': str(location.get('name', 'Unknown'))
                }

                # Add optional fields with safe conversions
                if location.get('speed'):
                    event_data['speed'] = self._safe_float_convert(location['speed'])
                if location.get('heading') or location.get('course'):
                    event_data['course'] = self._safe_float_convert(
                        location.get('heading', location.get('course', 0.0)))
                if location.get('description'):
                    event_data['remarks'] = str(location['description'])

                # Debug: Log the event_data to see what we're passing to XML generation
                logger.debug(f"Event data created: {event_data}")

                # Generate COT XML using PyTAK's functions
                cot_xml = self._generate_cot_xml(event_data)
                events.append(cot_xml)
                logger.debug(cot_xml)
                logger.debug(f"Created PyTAK COT event for {cleaned_location.get('name', 'Unknown')}")

            except Exception as e:
                logger.error(f"Error creating PyTAK COT event for location {location.get('name', 'Unknown')}: {e}")
                logger.error(f"Location data: {location}")
                continue

        logger.debug(f"Created {len(events)} PyTAK COT events from {len(locations)} locations")
        return events

    def _generate_cot_xml(self, event_data: Dict[str, Any]) -> bytes:
        """Generate COT XML using PyTAK's XML structure"""
        try:
            # Always use manual formatting to avoid PyTAK time conversion issues
            # PyTAK's cot_time() function may have issues with datetime objects
            time_str = event_data['time'].strftime("%Y-%m-%dT%H:%M:%SZ")
            start_str = event_data['start'].strftime("%Y-%m-%dT%H:%M:%SZ")
            stale_str = event_data['stale'].strftime("%Y-%m-%dT%H:%M:%SZ")

            # Create COT event element
            cot_event = etree.Element("event")
            cot_event.set("version", "2.0")
            cot_event.set("uid", event_data['uid'])
            cot_event.set("type", event_data['type'])
            cot_event.set("time", time_str)
            cot_event.set("start", start_str)
            cot_event.set("stale", stale_str)
            cot_event.set("how", event_data['how'])

            # Add point element with proper attribute order and safe conversions
            point_attr = {
                "lat": f"{event_data['lat']:.8f}",
                "lon": f"{event_data['lon']:.8f}",
                "hae": f"{event_data['hae']:.2f}",  # Ensure float formatting
                "ce": f"{event_data['ce']:.2f}",  # Ensure float formatting
                "le": f"{event_data['le']:.2f}"  # Ensure float formatting
            }
            etree.SubElement(cot_event, "point", attrib=point_attr)

            # Add detail element
            detail = etree.SubElement(cot_event, "detail")

            # Add contact info with endpoint (important for TAK Server)
            contact = etree.SubElement(detail, "contact")
            contact.set("callsign", event_data['callsign'])
            # contact.set("endpoint", "*:-1:stcp")  # Standard endpoint format

            # Add track information if available
            if 'speed' in event_data or 'course' in event_data:
                track = etree.SubElement(detail, "track")
                if 'speed' in event_data:
                    track.set("speed", f"{event_data['speed']:.2f}")
                if 'course' in event_data:
                    track.set("course", f"{event_data['course']:.2f}")

            # Add remarks if available
            if 'remarks' in event_data:
                remarks = etree.SubElement(detail, "remarks")
                remarks.text = event_data['remarks']

            return etree.tostring(cot_event, pretty_print=False, xml_declaration=False)

        except Exception as e:
            logger.error(f"Error generating COT XML: {e}")
            raise

    async def _create_custom_events(self, locations: List[Dict[str, Any]],
                                    cot_type: str, stale_time: int) -> List[bytes]:
        """Create COT events using custom XML generation (fallback)"""
        cot_events = []

        for location in locations:
            try:
                # Use existing logic from your current implementation
                if 'timestamp' in location and location['timestamp']:
                    if isinstance(location['timestamp'], str):
                        try:
                            event_time = datetime.fromisoformat(location['timestamp'].replace('Z', '+00:00')).replace(
                                tzinfo=None)
                        except ValueError:
                            event_time = datetime.now(timezone.utc)
                    else:
                        event_time = location['timestamp']
                else:
                    event_time = datetime.now(timezone.utc)

                time_str = event_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                stale_str = (event_time + timedelta(seconds=stale_time)).strftime("%Y-%m-%dT%H:%M:%SZ")

                uid = location['uid']

                # Create COT event element
                cot_event = etree.Element("event")
                cot_event.set("version", "2.0")
                cot_event.set("uid", uid)
                cot_event.set("type", cot_type)
                cot_event.set("time", time_str)
                cot_event.set("start", time_str)
                cot_event.set("stale", stale_str)
                cot_event.set("how", "h-g-i-g-o")  # Use standard PyTAK "how" value

                # Add point element with proper attribute structure and safe conversions
                point_attr = {
                    "lat": f"{self._safe_float_convert(location['lat']):.8f}",
                    "lon": f"{self._safe_float_convert(location['lon']):.8f}",
                    "hae": f"{self._safe_float_convert(location.get('altitude', location.get('hae', 0.0))):.2f}",
                    "ce": f"{self._safe_float_convert(location.get('accuracy', location.get('ce', 999999)), 999999):.2f}",
                    "le": f"{self._safe_float_convert(location.get('linear_error', location.get('le', 999999)), 999999):.2f}"
                }
                etree.SubElement(cot_event, "point", attrib=point_attr)

                # Add detail element
                detail = etree.SubElement(cot_event, "detail")

                # Add contact with endpoint (important for TAK Server recognition)
                contact = etree.SubElement(detail, "contact")
                contact.set("callsign", str(location.get('name', 'Unknown')))
                contact.set("endpoint", "*:-1:stcp")

                # Add track information with safe conversions
                if location.get('speed') or location.get('heading') or location.get('course'):
                    track = etree.SubElement(detail, "track")
                    track.set("speed", f"{self._safe_float_convert(location.get('speed', 0.0)):.2f}")
                    track.set("course",
                              f"{self._safe_float_convert(location.get('heading', location.get('course', 0.0))):.2f}")

                # Add remarks if available
                if location.get('description'):
                    remarks = etree.SubElement(detail, "remarks")
                    remarks.text = str(location['description'])

                cot_events.append(etree.tostring(cot_event, pretty_print=False, xml_declaration=False))

            except Exception as e:
                logger.error(f"Error creating custom COT event: {e}")
                continue

        return cot_events

    async def send_to_tak_server(self, events: List[bytes], tak_server) -> bool:
        """
        Send COT events to TAK server using appropriate method

        Args:
            events: List of COT events as XML bytes
            tak_server: TAK server configuration

        Returns:
            bool: Success status
        """
        if self.use_pytak:
            return await self._send_with_pytak(events, tak_server)
        else:
            return await self._send_with_custom(events, tak_server)

    async def _send_with_pytak(self, events: List[bytes], tak_server) -> bool:
        """Send events using PyTAK - use CLITool approach"""
        try:
            return await self._send_with_pytak_clitool(events, tak_server)
        except Exception as e:
            logger.warning(f"PyTAK CLITool approach failed: {e}, falling back to custom implementation")
            return await self._send_with_custom(events, tak_server)

    async def _send_with_pytak_clitool(self, events: List[bytes], tak_server) -> bool:
        """Send events using PyTAK's CLITool"""
        cert_path = None
        key_path = None

        try:
            # Handle P12 certificate extraction first
            if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                logger.debug("Extracting P12 certificate for PyTAK")
                cert_pem, key_pem = self._extract_p12_certificate(
                    tak_server.cert_p12,
                    tak_server.cert_password
                )
                cert_path, key_path = self._create_temp_cert_files(cert_pem, key_pem)
                logger.debug(f"Created temporary cert files: {cert_path}, {key_path}")

            # Create PyTAK configuration
            from configparser import ConfigParser
            config = ConfigParser()

            # Determine protocol
            protocol = "tls" if tak_server.protocol.lower() in ['tls', 'ssl'] else "tcp"

            # Create the configuration section properly
            config.add_section('pytak_cot')
            config.set('pytak_cot', 'COT_URL', f"{protocol}://{tak_server.host}:{tak_server.port}")

            # Add TLS configuration if needed
            if protocol == "tls":
                config.set('pytak_cot', 'PYTAK_TLS_DONT_VERIFY', str(not tak_server.verify_ssl).lower())

                # Add certificate configuration if available
                if cert_path and key_path:
                    config.set('pytak_cot', 'PYTAK_TLS_CLIENT_CERT', cert_path)
                    config.set('pytak_cot', 'PYTAK_TLS_CLIENT_KEY', key_path)
                    logger.debug("Added client certificate to PyTAK configuration")

            # Create CLITool with proper config
            clitool = pytak.CLITool(config["pytak_cot"])
            await clitool.setup()

            # Create a simple worker class to send our events
            class EventSender(pytak.QueueWorker):
                def __init__(self, queue, config, events_to_send):
                    super().__init__(queue, config)
                    self.events_to_send = events_to_send
                    self.events_sent = 0
                    self.finished = False

                async def run(self):
                    """Send all events then mark as finished"""
                    logger.debug(f"Starting to send {len(self.events_to_send)} events")
                    for event in self.events_to_send:
                        await self.put_queue(event)
                        self.events_sent += 1
                        logger.debug(f"Queued event {self.events_sent}/{len(self.events_to_send)}")

                    logger.info(f"Queued {self.events_sent} events for transmission")

                    # Give some time for transmission to complete
                    await asyncio.sleep(3.0)
                    self.finished = True

            # Create sender worker
            sender = EventSender(clitool.tx_queue, config["pytak_cot"], events)

            # Add the sender task
            clitool.add_tasks(set([sender]))

            # Start CLITool in background and monitor sender completion
            clitool_task = None
            success = False

            try:
                clitool_task = asyncio.create_task(clitool.run())

                # Wait for sender to finish or timeout
                timeout_time = 60.0  # Increased timeout
                start_time = asyncio.get_event_loop().time()

                while (asyncio.get_event_loop().time() - start_time) < timeout_time:
                    if sender.finished:
                        logger.info(f"Successfully sent {len(events)} events to {tak_server.name}")
                        success = True
                        break
                    await asyncio.sleep(0.5)
                else:
                    logger.error("Events transmission timed out")
                    success = False

            except Exception as e:
                logger.error(f"Events transmission failed: {e}")
                success = False
            finally:
                # Clean up the CLITool task
                if clitool_task and not clitool_task.done():
                    clitool_task.cancel()
                    try:
                        await asyncio.wait_for(clitool_task, timeout=1.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

            # Clean up temporary certificate files
            self._cleanup_temp_files(cert_path, key_path)

            return success

        except Exception as e:
            logger.error(f"Failed to send events: {e}")
            # Clean up on error
            self._cleanup_temp_files(cert_path, key_path)
            return False

    async def _send_with_custom(self, events: List[bytes], tak_server) -> bool:
        """Send events using custom implementation"""
        return await self._send_cot_to_tak_server_direct(events, tak_server)

    async def _send_cot_to_tak_server_direct(self, cot_events: List[bytes], tak_server) -> bool:
        """Direct send implementation without PyTAK"""
        if not cot_events:
            logger.warning("No COT events to send")
            return True

        reader = None
        writer = None
        cert_path = None
        key_path = None

        try:
            ssl_context = None
            if tak_server.protocol.lower() in ['tls', 'ssl']:
                ssl_context = ssl.create_default_context()

                if not tak_server.verify_ssl:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                    try:
                        cert_pem, key_pem = self._extract_p12_certificate(
                            tak_server.cert_p12,
                            tak_server.cert_password
                        )
                        cert_path, key_path = self._create_temp_cert_files(cert_pem, key_pem)
                        ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
                    except Exception as e:
                        logger.error(f"Failed to load P12 certificate: {e}")
                        raise

            logger.info(f"Connecting to {tak_server.host}:{tak_server.port} using {'TLS' if ssl_context else 'TCP'}")

            if ssl_context:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(tak_server.host, tak_server.port, ssl=ssl_context),
                    timeout=30.0
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(tak_server.host, tak_server.port),
                    timeout=30.0
                )

            logger.info("Connected to TAK server, sending events...")

            events_sent = 0
            for cot_event in cot_events:
                writer.write(cot_event)
                await writer.drain()
                events_sent += 1
                logger.debug(f"Sent event {events_sent}/{len(cot_events)}")

            logger.info(f"Successfully sent {events_sent} COT events to {tak_server.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to send COT events to {tak_server.name}: {e}")
            return False
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception as e:
                    logger.debug(f"Error closing writer: {e}")
            self._cleanup_temp_files(cert_path, key_path)

    def _extract_p12_certificate(self, p12_data: bytes, password: Optional[str] = None) -> Tuple[bytes, bytes]:
        """Extract certificate and key from P12 data"""
        try:
            password_bytes = password.encode('utf-8') if password else None
            private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                p12_data, password_bytes
            )

            cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
            key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )

            return cert_pem, key_pem

        except Exception as e:
            raise Exception(f"P12 certificate extraction failed: {str(e)}")

    def _create_temp_cert_files(self, cert_pem: bytes, key_pem: bytes) -> Tuple[str, str]:
        """Create temporary certificate files"""
        cert_fd, cert_path = tempfile.mkstemp(suffix='.pem', prefix='tak_cert_')
        key_fd, key_path = tempfile.mkstemp(suffix='.pem', prefix='tak_key_')

        try:
            with os.fdopen(cert_fd, 'wb') as cert_file:
                cert_file.write(cert_pem)
            with os.fdopen(key_fd, 'wb') as key_file:
                key_file.write(key_pem)
            return cert_path, key_path
        except Exception as e:
            try:
                os.close(cert_fd)
                os.close(key_fd)
                os.unlink(cert_path)
                os.unlink(key_path)
            except:
                pass
            raise e

    def _cleanup_temp_files(self, *file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

    async def cleanup(self):
        """Clean up resources"""
        logger.debug("COT service cleanup completed")

    async def process_and_send_locations(self, locations: List[Dict[str, Any]],
                                         tak_server,
                                         cot_type: str = "a-f-G-U-C",
                                         stale_time: int = 300) -> bool:
        """
        Complete workflow: convert locations to COT events and send to TAK server
        """
        try:
            if not locations:
                logger.warning("No locations provided for processing")
                return True

            logger.info(f"Processing {len(locations)} locations for TAK server {tak_server.name}")

            # Create COT events
            events = await self.create_cot_events(locations, cot_type, stale_time)

            if not events:
                logger.warning("No COT events created from locations")
                return False

            logger.info(f"Created {len(events)} COT events, sending to TAK server...")

            # Send to TAK server
            result = await self.send_to_tak_server(events, tak_server)

            if result:
                logger.info(f"Successfully processed {len(locations)} locations to {tak_server.name}")
            else:
                logger.error(f"Failed to process locations for {tak_server.name}")

            return result

        except Exception as e:
            logger.error(f"Failed to process and send locations: {str(e)}")
            return False