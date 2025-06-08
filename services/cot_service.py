# =============================================================================
# services/cot_service.py - Enhanced COT Conversion Service with TAK Integration
# =============================================================================

import asyncio
import ssl
import socket
import uuid
from lxml import etree
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class COTService:
    """Enhanced service for converting GPS data to Cursor-on-Target (COT) format and sending to TAK servers"""

    # COT Type mappings for different scenarios
    COT_TYPES = {
        'friendly_ground': 'a-f-G-U-C',  # Friendly Ground Unit - Civil
        'friendly_air': 'a-f-A-C',  # Friendly Air - Civil
        'friendly_sea': 'a-f-S-C',  # Friendly Sea - Civil
        'neutral_ground': 'a-n-G',  # Neutral Ground
        'unknown_ground': 'a-u-G',  # Unknown Ground
        'hostile_ground': 'a-h-G',  # Hostile Ground
        'pending_ground': 'a-p-G',  # Pending Ground
        'assumed_friend': 'a-a-G',  # Assumed Friend Ground
    }

    @staticmethod
    def create_cot_events(locations: List[Dict[str, Any]],
                          cot_type: str = "a-f-G-U-C",
                          stale_time: int = 300,
                          uid_prefix: str = "GPS") -> List[bytes]:
        """
        Convert location data to COT events with enhanced metadata

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier
            stale_time: Time in seconds before the event becomes stale
            uid_prefix: Prefix for generating unique IDs

        Returns:
            List of COT event XML as bytes
        """
        cot_events = []

        for location in locations:
            try:
                # Use location timestamp if available, otherwise use current time
                if 'timestamp' in location and location['timestamp']:
                    if isinstance(location['timestamp'], str):
                        # Try to parse string timestamp
                        try:
                            event_time = datetime.fromisoformat(location['timestamp'].replace('Z', '+00:00')).replace(
                                tzinfo=None)
                        except ValueError:
                            event_time = datetime.utcnow()
                    else:
                        event_time = location['timestamp']
                else:
                    event_time = datetime.utcnow()

                time_str = event_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                stale_str = (event_time + timedelta(seconds=stale_time)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

                # Generate unique UID
                device_name = str(location.get('name', 'Unknown')).replace(' ', '_')
                # uid = f"{uid_prefix}-{device_name}-{uuid.uuid4().hex[:8]}"
                uid = location['uid']

                # Create COT event element
                cot_event = etree.Element("event")
                cot_event.set("version", "2.0")
                cot_event.set("uid", uid)
                cot_event.set("time", time_str)
                cot_event.set("start", time_str)
                cot_event.set("stale", stale_str)
                cot_event.set("type", cot_type)
                cot_event.set("how", "m-g")  # Machine Generated

                # Add point element with enhanced positioning data
                point = etree.SubElement(cot_event, "point")
                point.set("lat", f"{float(location['lat']):.8f}")
                point.set("lon", f"{float(location['lon']):.8f}")

                # Set accuracy values
                ce = location.get('accuracy', location.get('ce', 9999999.0))
                le = location.get('linear_error', location.get('le', 9999999.0))
                hae = location.get('altitude', location.get('hae', 0))

                point.set("ce", str(ce))  # Circular Error
                point.set("le", str(le))  # Linear Error
                point.set("hae", str(hae))  # Height Above Ellipsoid

                # Add detail element with comprehensive metadata
                detail = etree.SubElement(cot_event, "detail")

                # Contact information
                contact = etree.SubElement(detail, "contact")
                contact.set("callsign", str(location.get('name', 'Unknown')))

                # Add endpoint for network identification
                if location.get('device_id'):
                    contact.set("endpoint", f"*:-1:stcp:///{location['device_id']}")

                # Add track information if available
                track = etree.SubElement(detail, "track")
                track.set("speed", str(location.get('speed', 0.0)))
                track.set("course", str(location.get('heading', location.get('course', 0.0))))

                # Add precision location if available
                if any(key in location for key in ['accuracy', 'pdop', 'hdop', 'vdop']):
                    precisionlocation = etree.SubElement(detail, "precisionlocation")
                    if 'accuracy' in location:
                        precisionlocation.set("geopointsrc", "GPS")
                        precisionlocation.set("altsrc", "GPS")

                # Add status information
                status = etree.SubElement(detail, "status")
                status.set("battery", str(location.get('battery', 100)))

                # Add timestamps
                timestamps = etree.SubElement(detail, "__timestamps")
                timestamps.set("updated", time_str)
                timestamps.set("received", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"))

                # Add description/remarks if available
                description = location.get("description", "")
                if description:
                    remarks = etree.SubElement(detail, "remarks")
                    remarks.text = str(description)

                # Add source information
                source = location.get('additional_data', {}).get('source', 'unknown')
                if source:
                    source_elem = etree.SubElement(detail, "source")
                    source_elem.text = str(source)

                # Add any additional custom data
                if location.get("additional_data"):
                    custom_data = etree.SubElement(detail, "custom_data")
                    for key, value in location["additional_data"].items():
                        if key != 'source':  # Skip source as it's handled above
                            elem = etree.SubElement(custom_data, str(key).replace(' ', '_'))
                            elem.text = str(value)

                # Add Garmin-specific data if available
                if source == 'garmin' and 'extended_data' in location.get('additional_data', {}):
                    garmin_data = etree.SubElement(detail, "garmin")
                    for key, value in location['additional_data']['extended_data'].items():
                        elem = etree.SubElement(garmin_data, str(key).replace(' ', '_').lower())
                        elem.text = str(value)

                cot_events.append(etree.tostring(cot_event, pretty_print=True, xml_declaration=False))
                logger.debug(f"Created COT event for {location.get('name', 'Unknown')}")

            except Exception as e:
                logger.error(f"Error creating COT event for location {location.get('name', 'Unknown')}: {e}")
                continue

        logger.info(f"Created {len(cot_events)} COT events from {len(locations)} locations")
        return cot_events

    @staticmethod
    async def send_cot_to_tak_server_direct(cot_events: List[bytes], tak_server) -> bool:
        """
        Send COT events to a TAK server using direct connection (one-off connection)

        Args:
            cot_events: List of COT event XML as bytes
            tak_server: TakServer model instance

        Returns:
            bool: True if successful, False otherwise
        """
        if not cot_events:
            logger.warning("No COT events to send")
            return True

        reader = None
        writer = None

        try:
            # Create SSL context if using TLS
            ssl_context = None
            if tak_server.protocol.lower() in ['tls', 'ssl']:
                ssl_context = ssl.create_default_context()

                # Configure SSL verification
                if not tak_server.verify_ssl:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                # Load client certificates if provided
                if tak_server.cert_pem and tak_server.cert_key:
                    ssl_context.load_cert_chain(
                        certfile=tak_server.cert_pem,
                        keyfile=tak_server.cert_key,
                        password=tak_server.client_password
                    )

            # Connect to TAK server with timeout
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

            logger.info(f"Connected to TAK server {tak_server.name} at {tak_server.host}:{tak_server.port}")

            # Send each COT event
            events_sent = 0
            for cot_event in cot_events:
                writer.write(cot_event)
                await writer.drain()
                events_sent += 1
                logger.debug(f"Sent COT event {events_sent}/{len(cot_events)}")

            logger.info(f"Successfully sent {events_sent} COT events to {tak_server.name}")
            return True

        except asyncio.TimeoutError:
            logger.error(f"Timeout connecting to TAK server {tak_server.name}")
            return False
        except ConnectionRefusedError:
            logger.error(f"Connection refused by TAK server {tak_server.name}")
            return False
        except Exception as e:
            logger.error(f"Failed to send COT events to TAK server {tak_server.name}: {str(e)}")
            return False
        finally:
            # Clean up connection
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception as e:
                    logger.debug(f"Error closing connection: {e}")

    @staticmethod
    async def send_cot_via_writer(cot_events: List[bytes], writer) -> bool:
        """
        Send COT events using an existing writer connection

        Args:
            cot_events: List of COT event XML as bytes
            writer: AsyncIO StreamWriter

        Returns:
            bool: True if successful, False otherwise
        """
        if not cot_events or not writer:
            return False

        try:
            events_sent = 0
            for cot_event in cot_events:
                writer.write(cot_event)
                await writer.drain()
                events_sent += 1

            logger.debug(f"Sent {events_sent} COT events via existing connection")
            return True

        except Exception as e:
            logger.error(f"Failed to send COT events via writer: {e}")
            return False

    @staticmethod
    async def test_tak_connection(tak_server) -> Tuple[bool, str]:
        """
        Test connection to a TAK server

        Args:
            tak_server: TakServer model instance

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Create a simple test COT event
            test_locations = [{
                'name': 'TEST_CONNECTION',
                'lat': 0.0,
                'lon': 0.0,
                'timestamp': datetime.utcnow(),
                'description': 'Connection test event',
                'additional_data': {'source': 'test'}
            }]

            test_events = COTService.create_cot_events(
                test_locations,
                cot_type="a-f-G-U-C",
                stale_time=60,
                uid_prefix="TEST"
            )

            success = await COTService.send_cot_to_tak_server_direct(test_events, tak_server)

            if success:
                return True, f"Successfully connected to TAK server {tak_server.name}"
            else:
                return False, f"Failed to send test event to TAK server {tak_server.name}"

        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

    @staticmethod
    async def process_and_send_locations(locations: List[Dict[str, Any]],
                                         tak_server,
                                         cot_type: str = "a-f-G-U-C",
                                         stale_time: int = 300,
                                         uid_prefix: str = "GPS") -> bool:
        """
        Complete workflow: convert locations to COT events and send to TAK server

        Args:
            locations: List of location dictionaries
            tak_server: TakServer model instance
            cot_type: COT type identifier
            stale_time: Time in seconds before the event becomes stale
            uid_prefix: Prefix for unique ID generation

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not locations:
                logger.warning("No locations provided for processing")
                return True

            # Convert locations to COT events
            cot_events = COTService.create_cot_events(
                locations,
                cot_type,
                stale_time,
                uid_prefix
            )

            if not cot_events:
                logger.warning("No COT events created from locations")
                return False

            # Send to TAK server
            return await COTService.send_cot_to_tak_server_direct(cot_events, tak_server)

        except Exception as e:
            logger.error(f"Failed to process and send locations: {str(e)}")
            return False

    @staticmethod
    def get_cot_type_options() -> Dict[str, str]:
        """Get available COT type options for UI"""
        return {
            'a-f-G-U-C': 'Friendly Ground Unit - Civil',
            'a-f-G-U-M': 'Friendly Ground Unit - Military',
            'a-f-A-C': 'Friendly Air - Civil',
            'a-f-A-M': 'Friendly Air - Military',
            'a-f-S-C': 'Friendly Sea - Civil',
            'a-f-S-M': 'Friendly Sea - Military',
            'a-n-G': 'Neutral Ground',
            'a-u-G': 'Unknown Ground',
            'a-h-G': 'Hostile Ground',
            'a-p-G': 'Pending Ground',
            'a-a-G': 'Assumed Friend Ground'
        }

    @staticmethod
    def validate_cot_type(cot_type: str) -> bool:
        """Validate COT type format"""
        if not cot_type:
            return False

        # Basic COT type pattern: a-{affiliation}-{dimension}-{...}
        parts = cot_type.split('-')
        if len(parts) < 3:
            return False

        # Check first part
        if parts[0] != 'a':
            return False

        # Check affiliation
        valid_affiliations = ['f', 'h', 'n', 'u', 'p', 'a', 's']
        if parts[1] not in valid_affiliations:
            return False

        # Check dimension
        valid_dimensions = ['A', 'G', 'S', 'U', 'P']
        if parts[2] not in valid_dimensions:
            return False

        return True