"""
File: services/cot_service.py

Description:
    Enhanced Cursor-on-Target (COT) service providing comprehensive COT event generation
    and transmission capabilities for the TrakBridge application. This service handles
    both PyTAK-based and custom implementations for robust COT operations with TAK servers.

Key features:
    - Dual implementation support: PyTAK library integration with custom fallback
    - Comprehensive COT event creation from location data with proper XML generation
    - Multiple transmission methods: direct TCP/TLS connections and persistent queues
    - P12 certificate handling and extraction for secure TAK server authentication
    - Persistent worker management with automatic connection recovery and monitoring
    - Asynchronous event processing with queue-based architecture for high throughput
    - Proper SSL/TLS context management with configurable certificate verification
    - Data validation and type safety with comprehensive error handling
    - Temporary file management for certificate operations with automatic cleanup
    - Support for various COT types including friendly, hostile, neutral, and unknown units
    - Stale time management and proper timestamp handling for event lifecycle
    - Connection pooling and resource management for efficient server communication
    - Detailed logging and diagnostics for troubleshooting and monitoring
    - Thread-safe operations with proper asyncio task management
    - Flexible configuration support for different TAK server protocols and settings

Author: Emfour Solutions
Created: 18-Jul-2025
"""

# Standard library imports
import asyncio
import logging
import os
import ssl
import tempfile
import time
import yaml
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Third-party imports
from lxml import etree
import xml.etree.ElementTree as ET

from services.logging_service import get_module_logger
from services.device_state_manager import DeviceStateManager

# PyTAK imports
try:
    import pytak

    PYTAK_AVAILABLE = True
except ImportError:
    pytak = None
    PYTAK_AVAILABLE = False
    logging.warning("PyTAK not available. Install with: pip install pytak")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

logger = get_module_logger(__name__)


class EnhancedCOTService:
    """Enhanced COT service with PyTAK integration and fallback to custom implementation"""

    COT_TYPES = {
        "friendly_ground": "a-f-G-U-C",
        "friendly_air": "a-f-A-C",
        "friendly_sea": "a-f-S-C",
        "neutral_ground": "a-n-G",
        "unknown_ground": "a-u-G",
        "hostile_ground": "a-h-G",
        "pending_ground": "a-p-G",
        "assumed_friend": "a-a-G",
    }

    def __init__(self, use_pytak: bool = True):
        """
        Initialize COT service

        Args:
            use_pytak: Whether to use PyTAK library when available
        """
        self.use_pytak = use_pytak and PYTAK_AVAILABLE
        self.device_state_manager = DeviceStateManager()

        # Phase 1B: Initialize performance configuration with defaults
        self.parallel_config = self._get_default_performance_config()
        self._load_performance_config()

        # Phase 1B: Initialize fallback tracking
        self.fallback_statistics = {
            "total_fallbacks": 0,
            "fallback_reasons": {},
            "total_parallel_attempts": 0,
            "successful_parallel_operations": 0,
            "circuit_breaker_open": False,
            "consecutive_failures": 0,
            "last_failure_time": None,
            "last_success_time": time.time(),
        }

        if self.use_pytak:
            logger.debug("Using PyTAK library for COT transmission")
        else:
            logger.debug("Using custom COT transmission implementation")

    @staticmethod
    def _safe_float_convert(value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float, handling various input types"""
        if value is None:
            return default

        # Handle datetime objects (return default)
        if isinstance(value, datetime):
            logger.warning(
                f"Datetime object passed where float expected: {value}, using default {default}"
            )
            return default

        try:
            return float(value)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Could not convert {value} (type: {type(value)}) to float: {e}, "
                f"using default {default}"
            )
            return default

    @staticmethod
    def _validate_location_data(location: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and clean location data to prevent type errors"""
        cleaned_location = {}

        for key, value in location.items():
            if isinstance(value, datetime) and key not in ["timestamp"]:
                logger.warning(
                    f"Found datetime object in unexpected field '{key}': {value}"
                )
                # Convert datetime to timestamp if it's not in timestamp field
                if key in [
                    "lat",
                    "lon",
                    "altitude",
                    "hae",
                    "accuracy",
                    "ce",
                    "linear_error",
                    "le",
                    "speed",
                    "heading",
                    "course",
                ]:
                    cleaned_location[key] = 0.0  # Use default for numeric fields
                else:
                    cleaned_location[key] = str(
                        value
                    )  # Convert to string for other fields
            else:
                cleaned_location[key] = value

        return cleaned_location

    async def create_cot_events(
        self,
        locations: List[Dict[str, Any]],
        cot_type: str = "a-f-G-U-C",
        stale_time: int = 300,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """
        Create COT events from location data

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier (used when cot_type_mode is "stream")
            stale_time: Time in seconds before event becomes stale
            cot_type_mode: "stream" or "per_point" to determine COT type source

        Returns:
            List of COT events as XML bytes
        """
        logger.debug(
            f"create_cot_events called with: cot_type_mode='{cot_type_mode}', cot_type='{cot_type}', locations={len(locations)}"
        )
        if self.use_pytak:
            # Use parallel processing for larger datasets to improve performance
            if len(locations) >= 10:  # Threshold for parallel processing
                logger.debug(
                    f"Using parallel processing for {len(locations)} locations"
                )
                return await self._create_parallel_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
            else:
                logger.debug(
                    f"Using serial processing for {len(locations)} locations (below threshold)"
                )
                return await EnhancedCOTService._create_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
        else:
            return await EnhancedCOTService._create_custom_events(
                locations, cot_type, stale_time, cot_type_mode
            )

    @staticmethod
    async def _create_pytak_events(
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """Create COT events using PyTAK's XML generation"""
        events = []

        for location in locations:
            try:
                # Check for error responses from plugins
                if "_error" in location:
                    error_code = location.get("_error", "unknown")
                    error_message = location.get("_error_message", "Unknown error")
                    logger.warning(
                        f"Skipping error response from plugin: {error_code} - {error_message}"
                    )
                    continue

                # Validate and clean location data first
                cleaned_location = EnhancedCOTService._validate_location_data(location)

                # Debug: Log the location data to see what we're working with
                logger.debug(f"Processing location: {cleaned_location}")

                # Parse timestamp - ensure we get a proper datetime object
                if "timestamp" in cleaned_location and cleaned_location["timestamp"]:
                    if isinstance(cleaned_location["timestamp"], str):
                        try:
                            event_time = datetime.fromisoformat(
                                cleaned_location["timestamp"].replace("Z", "+00:00")
                            )
                            # Remove timezone info to avoid issues
                            if event_time.tzinfo is not None:
                                event_time = event_time.replace(tzinfo=None)
                        except ValueError as e:
                            logger.warning(
                                f"Could not parse timestamp '{cleaned_location['timestamp']}': {e}"
                            )
                            event_time = datetime.now(timezone.utc)
                    elif isinstance(cleaned_location["timestamp"], datetime):
                        event_time = cleaned_location["timestamp"]
                        # Remove timezone info to avoid issues
                        if event_time.tzinfo is not None:
                            event_time = event_time.replace(tzinfo=None)
                    else:
                        logger.warning(
                            f"Unexpected timestamp type: {type(cleaned_location['timestamp'])}"
                        )
                        event_time = datetime.now(timezone.utc)
                else:
                    event_time = datetime.now(timezone.utc)

                # Ensure event_time is a proper datetime object
                if not isinstance(event_time, datetime):
                    logger.error(
                        f"event_time is not a datetime object: {type(event_time)}"
                    )
                    event_time = datetime.now(timezone.utc)

                # Determine COT type based on mode
                if cot_type_mode == "per_point" and "cot_type" in location:
                    point_cot_type = location["cot_type"]
                    logger.debug(
                        f"Using per-point CoT type: {point_cot_type} (mode: {cot_type_mode})"
                    )
                else:
                    point_cot_type = cot_type
                    logger.debug(
                        f"Using stream CoT type: {point_cot_type} (mode: {cot_type_mode}, has cot_type: {'cot_type' in location})"
                    )

                # Create COT event data dictionary with safe conversions
                event_data = {
                    "uid": str(location["uid"]),
                    "type": str(point_cot_type),  # Use determined COT type
                    "time": event_time,
                    "start": event_time,
                    "stale": event_time + timedelta(seconds=int(stale_time)),
                    "how": "m-g",  # Standard PyTAK "how" value
                    "lat": EnhancedCOTService._safe_float_convert(location["lat"]),
                    "lon": EnhancedCOTService._safe_float_convert(location["lon"]),
                    "hae": EnhancedCOTService._safe_float_convert(
                        location.get("altitude", location.get("hae", 0.0))
                    ),
                    "ce": EnhancedCOTService._safe_float_convert(
                        location.get("accuracy", location.get("ce", 999999)), 999999
                    ),
                    "le": EnhancedCOTService._safe_float_convert(
                        location.get("linear_error", location.get("le", 999999)), 999999
                    ),
                    "callsign": str(location.get("name", "Unknown")),
                }

                # Add optional fields with safe conversions
                if location.get("speed"):
                    event_data["speed"] = EnhancedCOTService._safe_float_convert(
                        location["speed"]
                    )
                if location.get("heading") or location.get("course"):
                    event_data["course"] = EnhancedCOTService._safe_float_convert(
                        location.get("heading", location.get("course", 0.0))
                    )
                if location.get("description"):
                    event_data["remarks"] = str(location["description"])

                # Debug: Log the event_data to see what we're passing to XML generation
                logger.debug(f"Event data created: {event_data}")

                # Generate COT XML using PyTAK's functions
                cot_xml = EnhancedCOTService._generate_cot_xml(event_data)
                events.append(cot_xml)
                logger.debug(cot_xml)
                logger.debug(
                    f"Created COT event for {cleaned_location.get('name', 'Unknown')}"
                )

            except Exception as e:
                location_name = location.get("name", "Unknown")
                logger.error(
                    f"Error creating COT event for location {location_name}: {e}"
                )
                logger.error(f"Location data: {location}")
                continue

        logger.debug(
            f"Created {len(events)} COT events from {len(locations)} locations"
        )
        return events

    async def _create_parallel_pytak_events(
        self,
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """
        Create COT events using parallel processing for improved performance

        This method processes multiple locations concurrently using asyncio.gather()
        to significantly improve performance for large datasets (50+ points).

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier (used when cot_type_mode is "stream")
            stale_time: Time in seconds before event becomes stale
            cot_type_mode: "stream" or "per_point" to determine COT type source

        Returns:
            List of COT events as XML bytes
        """
        if not locations:
            logger.debug("No locations to process in parallel")
            return []

        logger.debug(f"Starting parallel processing of {len(locations)} locations")

        # Get max concurrent tasks from configuration
        max_concurrent = self.parallel_config.get("max_concurrent_tasks", 50)

        # Process locations in batches to respect max_concurrent_tasks limit
        all_results = []

        for i in range(0, len(locations), max_concurrent):
            batch = locations[i : i + max_concurrent]

            # Create async tasks for this batch
            tasks = [
                EnhancedCOTService._process_single_location_async(
                    location, cot_type, stale_time, cot_type_mode
                )
                for location in batch
            ]

            # Execute batch concurrently
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            all_results.extend(batch_results)

        results = all_results

        # Filter out exceptions and collect valid COT events
        valid_events = []
        error_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Log error but continue processing other locations
                location_name = locations[i].get("name", f"Location_{i}")
                logger.error(f"Error processing location {location_name}: {result}")
                error_count += 1
            elif result is not None:  # Valid COT event
                valid_events.append(result)

        logger.debug(
            f"Parallel processing completed: {len(valid_events)} valid events, "
            f"{error_count} errors from {len(locations)} locations"
        )

        return valid_events

    @staticmethod
    async def _process_single_location_async(
        location: Dict[str, Any], cot_type: str, stale_time: int, cot_type_mode: str
    ) -> bytes:
        """
        Process a single location to COT event asynchronously

        This wraps the existing single-location processing logic in an async function
        to enable concurrent processing via asyncio.gather().

        Args:
            location: Single location dictionary
            cot_type: COT type identifier
            stale_time: Time in seconds before event becomes stale
            cot_type_mode: "stream" or "per_point" mode

        Returns:
            COT event as XML bytes

        Raises:
            Exception: If location processing fails
        """
        try:
            # Check for error responses from plugins
            if "_error" in location:
                error_code = location.get("_error", "unknown")
                error_message = location.get("_error_message", "Unknown error")
                logger.warning(
                    f"Skipping error response from plugin: {error_code} - {error_message}"
                )
                raise ValueError(f"Plugin error: {error_code} - {error_message}")

            # Validate and clean location data first
            cleaned_location = EnhancedCOTService._validate_location_data(location)

            # Parse timestamp - ensure we get a proper datetime object
            if "timestamp" in cleaned_location and cleaned_location["timestamp"]:
                if isinstance(cleaned_location["timestamp"], str):
                    try:
                        event_time = datetime.fromisoformat(
                            cleaned_location["timestamp"].replace("Z", "+00:00")
                        )
                        # Remove timezone info to avoid issues
                        if event_time.tzinfo is not None:
                            event_time = event_time.replace(tzinfo=None)
                    except ValueError as e:
                        logger.warning(
                            f"Could not parse timestamp '{cleaned_location['timestamp']}': {e}"
                        )
                        event_time = datetime.now(timezone.utc)
                elif isinstance(cleaned_location["timestamp"], datetime):
                    event_time = cleaned_location["timestamp"]
                    # Remove timezone info to avoid issues
                    if event_time.tzinfo is not None:
                        event_time = event_time.replace(tzinfo=None)
                else:
                    logger.warning(
                        f"Unexpected timestamp type: {type(cleaned_location['timestamp'])}"
                    )
                    event_time = datetime.now(timezone.utc)
            else:
                event_time = datetime.now(timezone.utc)

            # Ensure event_time is a proper datetime object
            if not isinstance(event_time, datetime):
                logger.error(f"event_time is not a datetime object: {type(event_time)}")
                event_time = datetime.now(timezone.utc)

            # Determine COT type based on mode
            if cot_type_mode == "per_point" and "cot_type" in location:
                point_cot_type = location["cot_type"]
            else:
                point_cot_type = cot_type

            # Create COT event data dictionary with safe conversions
            event_data = {
                "uid": str(location["uid"]),
                "type": str(point_cot_type),  # Use determined COT type
                "time": event_time,
                "start": event_time,
                "stale": event_time + timedelta(seconds=int(stale_time)),
                "how": "m-g",  # Standard PyTAK "how" value
                "lat": EnhancedCOTService._safe_float_convert(location["lat"]),
                "lon": EnhancedCOTService._safe_float_convert(location["lon"]),
                "hae": EnhancedCOTService._safe_float_convert(
                    location.get("altitude", location.get("hae", 0.0))
                ),
                "ce": EnhancedCOTService._safe_float_convert(
                    location.get("accuracy", location.get("ce", 999999)), 999999
                ),
                "le": EnhancedCOTService._safe_float_convert(
                    location.get("linear_error", location.get("le", 999999)), 999999
                ),
                "callsign": str(location.get("name", "Unknown")),
            }

            # Add optional fields with safe conversions
            if location.get("speed"):
                event_data["speed"] = EnhancedCOTService._safe_float_convert(
                    location["speed"]
                )
            if location.get("heading") or location.get("course"):
                event_data["course"] = EnhancedCOTService._safe_float_convert(
                    location.get("heading", location.get("course", 0.0))
                )
            if location.get("description"):
                event_data["remarks"] = str(location["description"])

            # Generate COT XML using PyTAK's functions
            cot_xml = EnhancedCOTService._generate_cot_xml(event_data)

            return cot_xml

        except Exception as e:
            location_name = location.get("name", "Unknown")
            logger.debug(f"Error processing location {location_name}: {e}")
            raise  # Re-raise to be handled by caller

    @staticmethod
    def _generate_cot_xml(event_data: Dict[str, Any]) -> bytes:
        """Generate COT XML using PyTAK's XML structure"""
        try:
            # Always use manual formatting to avoid PyTAK time conversion issues
            # PyTAK's cot_time() function may have issues with datetime objects
            time_str = event_data["time"].strftime("%Y-%m-%dT%H:%M:%SZ")
            start_str = event_data["start"].strftime("%Y-%m-%dT%H:%M:%SZ")
            stale_str = event_data["stale"].strftime("%Y-%m-%dT%H:%M:%SZ")

            # Create COT event element
            cot_event = etree.Element("event")
            cot_event.set("version", "2.0")
            cot_event.set("uid", event_data["uid"])
            cot_event.set("type", event_data["type"])
            cot_event.set("time", time_str)
            cot_event.set("start", start_str)
            cot_event.set("stale", stale_str)
            cot_event.set("how", event_data["how"])

            # Add point element with proper attribute order and safe conversions
            point_attr = {
                "lat": f"{event_data['lat']:.8f}",
                "lon": f"{event_data['lon']:.8f}",
                "hae": f"{event_data['hae']:.2f}",  # Ensure float formatting
                "ce": f"{event_data['ce']:.2f}",  # Ensure float formatting
                "le": f"{event_data['le']:.2f}",  # Ensure float formatting
            }
            etree.SubElement(cot_event, "point", attrib=point_attr)

            # Add detail element
            detail = etree.SubElement(cot_event, "detail")

            # Add contact info with endpoint (important for TAK Server)
            contact = etree.SubElement(detail, "contact")
            contact.set("callsign", event_data["callsign"])
            # contact.set("endpoint", "*:-1:stcp")  # Standard endpoint format

            # Add track information if available
            if "speed" in event_data or "course" in event_data:
                track = etree.SubElement(detail, "track")
                if "speed" in event_data:
                    track.set("speed", f"{event_data['speed']:.2f}")
                if "course" in event_data:
                    track.set("course", f"{event_data['course']:.2f}")

            # Add remarks if available
            if "remarks" in event_data:
                remarks = etree.SubElement(detail, "remarks")
                remarks.text = event_data["remarks"]

            return etree.tostring(cot_event, pretty_print=False, xml_declaration=False)

        except Exception as e:
            logger.error(f"Error generating COT XML: {e}")
            raise

    @staticmethod
    async def _create_custom_events(
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """Create COT events using custom XML generation (fallback)"""
        cot_events = []

        for location in locations:
            try:
                # Check for error responses from plugins
                if "_error" in location:
                    error_code = location.get("_error", "unknown")
                    error_message = location.get("_error_message", "Unknown error")
                    logger.warning(
                        f"Skipping error response from plugin: {error_code} - {error_message}"
                    )
                    continue

                # Use existing logic from your current implementation
                if "timestamp" in location and location["timestamp"]:
                    if isinstance(location["timestamp"], str):
                        try:
                            event_time = datetime.fromisoformat(
                                location["timestamp"].replace("Z", "+00:00")
                            ).replace(tzinfo=None)
                        except ValueError:
                            event_time = datetime.now(timezone.utc)
                    else:
                        event_time = location["timestamp"]
                else:
                    event_time = datetime.now(timezone.utc)

                time_str = event_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                stale_str = (event_time + timedelta(seconds=stale_time)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

                uid = location["uid"]

                # Determine COT type based on mode
                if cot_type_mode == "per_point" and "cot_type" in location:
                    point_cot_type = location["cot_type"]
                    logger.debug(
                        f"Custom: Using per-point CoT type: {point_cot_type} (mode: {cot_type_mode})"
                    )
                else:
                    point_cot_type = cot_type
                    logger.debug(
                        f"Custom: Using stream CoT type: {point_cot_type} (mode: {cot_type_mode}, has cot_type: {'cot_type' in location})"
                    )

                # Create COT event element
                cot_event = etree.Element("event")
                cot_event.set("version", "2.0")
                cot_event.set("uid", uid)
                cot_event.set("type", point_cot_type)
                cot_event.set("time", time_str)
                cot_event.set("start", time_str)
                cot_event.set("stale", stale_str)
                cot_event.set("how", "h-g-i-g-o")  # Use standard PyTAK "how" value

                # Add point element with proper attribute structure and safe conversions
                # Extract the conversions first, then format with bounds checking
                lat_val = max(
                    -90.0,
                    min(90.0, EnhancedCOTService._safe_float_convert(location["lat"])),
                )
                lon_val = max(
                    -180.0,
                    min(180.0, EnhancedCOTService._safe_float_convert(location["lon"])),
                )
                hae_val = EnhancedCOTService._safe_float_convert(
                    location.get("altitude", location.get("hae", 0.0))
                )
                ce_val = EnhancedCOTService._safe_float_convert(
                    location.get("accuracy", location.get("ce", 999999)), 999999
                )
                le_val = EnhancedCOTService._safe_float_convert(
                    location.get("linear_error", location.get("le", 999999)), 999999
                )

                point_attr = {
                    "lat": f"{lat_val:.8f}",
                    "lon": f"{lon_val:.8f}",
                    "hae": f"{hae_val:.2f}",
                    "ce": f"{ce_val:.2f}",
                    "le": f"{le_val:.2f}",
                }
                etree.SubElement(cot_event, "point", attrib=point_attr)

                # Add detail element
                detail = etree.SubElement(cot_event, "detail")

                # Add contact with endpoint (important for TAK Server recognition)
                contact = etree.SubElement(detail, "contact")
                contact.set("callsign", str(location.get("name", "Unknown")))
                contact.set("endpoint", "*:-1:stcp")

                # Add track information with safe conversions
                if (
                    location.get("speed")
                    or location.get("heading")
                    or location.get("course")
                ):
                    track = etree.SubElement(detail, "track")

                    speed_val = max(
                        0.0,
                        EnhancedCOTService._safe_float_convert(
                            location.get("speed", 0.0)
                        ),
                    )
                    course_val = (
                        EnhancedCOTService._safe_float_convert(
                            location.get("heading", location.get("course", 0.0))
                        )
                        % 360.0
                    )

                    track.set("speed", f"{speed_val:.2f}")
                    track.set("course", f"{course_val:.2f}")

                # Add remarks if available
                if location.get("description"):
                    remarks = etree.SubElement(detail, "remarks")
                    remarks.text = str(location["description"])

                cot_events.append(
                    etree.tostring(cot_event, pretty_print=False, xml_declaration=False)
                )

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
            return await EnhancedCOTService._send_with_custom(events, tak_server)

    async def _send_with_pytak(self, events: List[bytes], tak_server) -> bool:
        """Send events using PyTAK - use CLITool approach"""
        try:
            return await self._send_with_pytak_clitool(events, tak_server)
        except Exception as e:
            logger.warning(
                f"PyTAK CLITool approach failed: {e}, falling back to custom implementation"
            )
            return await EnhancedCOTService._send_with_custom(events, tak_server)

    async def send_to_persistent_service(
        self,
        locations: List[Dict[str, Any]],
        tak_server,
        cot_type: str = "a-f-G-U-C",
        stale_time: int = 300,
    ) -> bool:
        """
        Send locations to persistent COT service (queue-based)
        """
        try:
            # Create COT events
            events = await self.create_cot_events(locations, cot_type, stale_time)

            if not events:
                logger.warning("No COT events created from locations")
                return False

            # Log the start of queue operations
            logger.info(
                f"Starting to enqueue {len(events)} COT events for TAK server '{tak_server.name}' "
                f"(ID: {tak_server.id}). Queue operation initiated."
            )

            # Get initial queue size for comparison
            initial_queue_size = 0
            if tak_server.id in cot_service.queues:
                initial_queue_size = cot_service.queues[tak_server.id].qsize()
                logger.debug(
                    f"Initial queue size for TAK server {tak_server.name}: {initial_queue_size}"
                )

            # Send events to persistent service
            success_count = 0
            for i, event in enumerate(events, 1):
                success = await cot_service.enqueue_event(event, tak_server.id)
                if success:
                    success_count += 1
                    logger.debug(
                        f"Enqueued event {i}/{len(events)} for TAK server {tak_server.name}"
                    )
                else:
                    logger.warning(
                        f"Failed to enqueue event {i}/{len(events)} for TAK server {tak_server.name}"
                    )

            # Log completion of queuing
            final_queue_size = 0
            if tak_server.id in cot_service.queues:
                final_queue_size = cot_service.queues[tak_server.id].qsize()

            logger.info(
                f"Completed enqueueing for TAK server '{tak_server.name}': "
                f"{success_count}/{len(events)} events successfully queued. "
                f"Queue size: {initial_queue_size} → {final_queue_size}"
            )

            return success_count > 0

        except Exception as e:
            logger.error(
                f"Failed to send to persistent service for TAK server '{tak_server.name}': {e}"
            )
            return False

    async def _send_with_pytak_clitool(self, events: List[bytes], tak_server) -> bool:
        """Send events using PyTAK's CLITool"""
        cert_path = None
        key_path = None

        try:
            # Handle P12 certificate extraction first
            if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                logger.debug("Extracting P12 certificate for PyTAK")
                cert_pem, key_pem = EnhancedCOTService._extract_p12_certificate(
                    tak_server.cert_p12, tak_server.get_cert_password()
                )
                cert_path, key_path = EnhancedCOTService._create_temp_cert_files(
                    cert_pem, key_pem
                )
                logger.debug(f"Created temporary cert files: {cert_path}, {key_path}")

            # Create PyTAK configuration
            from configparser import ConfigParser

            tak_config = ConfigParser(interpolation=None)

            # Determine protocol
            protocol = "tls" if tak_server.protocol.lower() in ["tls", "ssl"] else "tcp"

            # Create the configuration section properly
            tak_config.add_section("pytak_cot")
            tak_config.set(
                "pytak_cot",
                "COT_URL",
                f"{protocol}://{tak_server.host}:{tak_server.port}",
            )

            # Add TLS configuration if needed
            if protocol == "tls":
                tak_config.set(
                    "pytak_cot",
                    "PYTAK_TLS_DONT_VERIFY",
                    str(not tak_server.verify_ssl).lower(),
                )

                # Add certificate configuration if available
                if cert_path and key_path:
                    tak_config.set("pytak_cot", "PYTAK_TLS_CLIENT_CERT", cert_path)
                    tak_config.set("pytak_cot", "PYTAK_TLS_CLIENT_KEY", key_path)
                    logger.debug("Added client certificate to PyTAK configuration")

            # Create CLITool with proper config
            clitool = pytak.CLITool(tak_config["pytak_cot"])
            await clitool.setup()

            # Create a simple worker class to send our events
            class EventSender(pytak.QueueWorker):
                def __init__(self, queue, pytak_config, events_to_send):
                    super().__init__(queue, pytak_config)
                    self.events_to_send = events_to_send
                    self.events_sent = 0
                    self.finished = False

                async def run(self, number_of_iterations=-1):
                    """Send all events, then wait for queue to empty, then mark as finished."""
                    logger.debug(f"Starting to send {len(self.events_to_send)} events")
                    for event in self.events_to_send:
                        await self.put_queue(event)
                        self.events_sent += 1
                        logger.debug(
                            f"Queued event {self.events_sent}/{len(self.events_to_send)}"
                        )

                    logger.info(f"Queued {self.events_sent} events for transmission")

                    # Wait for the queue to empty (i.e., all events processed)
                    max_wait = 60  # seconds
                    waited = 0
                    while not self.queue.empty() and waited < max_wait:
                        logger.debug(
                            f"Waiting for queue to empty... (size: {self.queue.qsize()})"
                        )
                        await asyncio.sleep(1)
                        waited += 1

                    if self.queue.empty():
                        logger.info("All events have been processed by PyTAK worker.")
                    else:
                        logger.warning(
                            "Timeout waiting for PyTAK queue to empty. Some events may not have been sent."
                        )

                    self.finished = True

            # Create sender worker
            sender = EventSender(clitool.tx_queue, tak_config["pytak_cot"], events)

            # Add the sender task
            clitool.add_tasks({sender})

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
                        logger.info(
                            f"Successfully sent {len(events)} events to {tak_server.name}"
                        )
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
            EnhancedCOTService._cleanup_temp_files(cert_path, key_path)

            return success

        except Exception as e:
            logger.error(f"Failed to send events: {e}")
            # Clean up on error
            EnhancedCOTService._cleanup_temp_files(cert_path, key_path)
            return False

    @staticmethod
    async def _send_with_custom(events: List[bytes], tak_server) -> bool:
        """Send events using custom implementation"""
        return await EnhancedCOTService._send_cot_to_tak_server_direct(
            events, tak_server
        )

    @staticmethod
    async def _send_cot_to_tak_server_direct(
        cot_events: List[bytes], tak_server
    ) -> bool:
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
            if tak_server.protocol.lower() in ["tls", "ssl"]:
                ssl_context = EnhancedCOTService._create_ssl_context(tak_server)

                if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                    try:
                        cert_pem, key_pem = EnhancedCOTService._extract_p12_certificate(
                            tak_server.cert_p12, tak_server.get_cert_password()
                        )
                        cert_path, key_path = (
                            EnhancedCOTService._create_temp_cert_files(
                                cert_pem, key_pem
                            )
                        )
                        ssl_context.load_cert_chain(
                            certfile=cert_path, keyfile=key_path
                        )
                        logger.debug(
                            f"Loaded client certificate for TAK server '{tak_server.name}'"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to load P12 certificate for TAK server '{tak_server.name}': {e}"
                        )
                        raise

            logger.info(
                f"Connecting to {tak_server.host}:{tak_server.port} "
                f"using {'TLS' if ssl_context else 'TCP'}"
            )

            if ssl_context:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        tak_server.host, tak_server.port, ssl=ssl_context
                    ),
                    timeout=30.0,
                )
            else:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(tak_server.host, tak_server.port),
                    timeout=30.0,
                )

            logger.info("Connected to TAK server, sending events...")

            events_sent = 0
            for cot_event in cot_events:
                writer.write(cot_event)
                await writer.drain()
                events_sent += 1
                logger.debug(f"Sent event {events_sent}/{len(cot_events)}")

            logger.info(
                f"Successfully sent {events_sent} COT events to {tak_server.name}"
            )
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
            EnhancedCOTService._cleanup_temp_files(cert_path, key_path)

    @staticmethod
    def _create_ssl_context(tak_server):
        """Create SSL context with configurable TLS version and TAK server compatibility"""
        ssl_context = ssl.create_default_context()

        # Get TLS version from server config, default to auto (1.3 with fallback)
        tls_version = getattr(tak_server, "tls_version", "auto")

        try:
            if tls_version == "1.3":
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
                logger.debug(f"TAK server '{tak_server.name}': Using TLS 1.3 only")
            elif tls_version == "1.2":
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2
                logger.debug(f"TAK server '{tak_server.name}': Using TLS 1.2 only")
            elif tls_version == "1.1":
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_1
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_1
                logger.debug(f"TAK server '{tak_server.name}': Using TLS 1.1 only")
            else:  # 'auto' or any other value
                ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3
                logger.debug(
                    f"TAK server '{tak_server.name}': Using TLS 1.2-1.3 (auto)"
                )

            # Set cipher suites compatible with TAK servers
            ssl_context.set_ciphers(
                "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS"
            )

        except Exception as e:
            logger.warning(
                f"Failed to set specific TLS version '{tls_version}' for TAK server '{tak_server.name}': {e}. Using defaults."
            )
            # Fall back to secure defaults
            ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Configure certificate verification
        if not tak_server.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            logger.debug(
                f"SSL verification disabled for TAK server '{tak_server.name}'"
            )
        else:
            logger.debug(f"SSL verification enabled for TAK server '{tak_server.name}'")

        return ssl_context

    @staticmethod
    def _extract_p12_certificate(
        p12_data: bytes, password: Optional[str] = None
    ) -> Tuple[bytes, bytes]:
        """Extract certificate and key from P12 data"""
        try:
            password_bytes = password.encode("utf-8") if password else None
            private_key, certificate, additional_certificates = (
                pkcs12.load_key_and_certificates(p12_data, password_bytes)
            )

            cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
            key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )

            return cert_pem, key_pem

        except Exception as e:
            raise Exception(f"P12 certificate extraction failed: {str(e)}")

    @staticmethod
    def _create_temp_cert_files(cert_pem: bytes, key_pem: bytes) -> Tuple[str, str]:
        """Create temporary certificate files"""
        cert_fd, cert_path = tempfile.mkstemp(suffix=".pem", prefix="tak_cert_")
        key_fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="tak_key_")

        try:
            with os.fdopen(cert_fd, "wb") as cert_file:
                cert_file.write(cert_pem)
            with os.fdopen(key_fd, "wb") as key_file:
                key_file.write(key_pem)
            return cert_path, key_path
        except Exception as e:
            try:
                os.close(cert_fd)
                os.close(key_fd)
                os.unlink(cert_path)
                os.unlink(key_path)
            except Exception as cleanup_error:
                logger.error(
                    f"Error cleaning up temporary Certificate Files: {cleanup_error}"
                )
            logger.error(f"Error creating temporary Certificate Files: {e}")
            raise

    @staticmethod
    def _cleanup_temp_files(*file_paths):
        """Clean up temporary files"""
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(f"Cleaned up temp file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {file_path}: {e}")

    @staticmethod
    async def cleanup():
        """Clean up resources"""
        logger.debug("COT service cleanup completed")

    async def process_and_send_locations(
        self,
        locations: List[Dict[str, Any]],
        tak_server,
        cot_type: str = "a-f-G-U-C",
        stale_time: int = 300,
    ) -> bool:
        """
        Complete workflow: convert locations to COT events and send to TAK server
        """
        try:
            if not locations:
                logger.warning("No locations provided for processing")
                return True

            logger.info(
                f"Starting location processing workflow for TAK server '{tak_server.name}': "
                f"{len(locations)} locations to process"
            )

            # Create COT events
            events = await self.create_cot_events(locations, cot_type, stale_time)

            if not events:
                logger.warning(f"No COT events created from {len(locations)} locations")
                return False

            logger.info(
                f"Successfully created {len(events)} COT events from {len(locations)} locations. "
                f"Proceeding to send to TAK server '{tak_server.name}'"
            )

            # Send to TAK server
            result = await self.send_to_tak_server(events, tak_server)

            if result:
                logger.info(
                    f"Location processing workflow completed successfully: "
                    f"{len(locations)} locations → {len(events)} events → "
                    f"transmitted to '{tak_server.name}'"
                )
            else:
                logger.error(
                    f"Location processing workflow failed for TAK server '{tak_server.name}': "
                    f"{len(locations)} locations processed, {len(events)} events created, "
                    f"but transmission failed"
                )

            return result

        except Exception as e:
            logger.error(
                f"Location processing workflow exception for TAK server '{tak_server.name}': {e}. "
                f"Input: {len(locations) if locations else 0} locations"
            )
            return False

    # Phase 1B: Configuration & Fallback Methods

    def _get_default_performance_config(self) -> Dict[str, Any]:
        """Get default performance configuration values"""
        return {
            "enabled": True,
            "batch_size_threshold": 10,
            "max_concurrent_tasks": 50,
            "fallback_on_error": True,
            "processing_timeout": 30.0,
            "enable_performance_logging": True,
            "circuit_breaker": {
                "enabled": True,
                "failure_threshold": 3,
                "recovery_timeout": 60.0,
            },
        }

    def load_performance_config(
        self, config_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Load performance configuration from YAML file

        Args:
            config_path: Optional path to config file. If None, uses default paths.

        Returns:
            Configuration dictionary
        """
        if config_path:
            config_paths = [config_path]
        else:
            config_paths = self.get_config_file_search_paths()

        config = {}
        for path in config_paths:
            try:
                expanded_path = os.path.expanduser(path)
                if os.path.exists(expanded_path):
                    with open(expanded_path, "r") as f:
                        file_config = yaml.safe_load(f) or {}
                        if "parallel_processing" in file_config:
                            config = file_config["parallel_processing"]
                            logger.debug(
                                f"Loaded performance configuration from {expanded_path}"
                            )
                            break
                        elif (
                            file_config
                        ):  # File exists but no parallel_processing section
                            logger.warning(
                                f"Configuration file {expanded_path} missing 'parallel_processing' section"
                            )
            except Exception as e:
                logger.warning(f"Failed to load configuration from {path}: {e}")
                continue

        # If no config found, return the full structure expected by tests
        if not config:
            return {"parallel_processing": self._get_default_performance_config()}

        return {"parallel_processing": config}

    def get_config_file_search_paths(self) -> List[str]:
        """Get list of paths to search for configuration files"""
        return [
            "config/settings/performance.yaml",
            "/etc/trakbridge/performance.yaml",
            "~/.trakbridge/performance.yaml",
        ]

    def _load_performance_config(self):
        """Load and apply performance configuration with environment overrides"""
        # Load from file
        file_config = self.load_performance_config()

        # Apply file configuration over defaults
        if file_config:
            self.parallel_config.update(file_config)

        # Apply environment variable overrides
        env_config = self.load_performance_config_with_env_override()
        self.parallel_config.update(env_config)

        # Validate configuration
        self.parallel_config = self.validate_performance_config(self.parallel_config)

    def load_performance_config_with_env_override(self) -> Dict[str, Any]:
        """Load configuration overrides from environment variables"""
        env_config = {}

        # Boolean environment variables
        if "TRAKBRIDGE_PARALLEL_ENABLED" in os.environ:
            env_config["enabled"] = (
                os.environ["TRAKBRIDGE_PARALLEL_ENABLED"].lower() == "true"
            )

        if "TRAKBRIDGE_FALLBACK_ON_ERROR" in os.environ:
            env_config["fallback_on_error"] = (
                os.environ["TRAKBRIDGE_FALLBACK_ON_ERROR"].lower() == "true"
            )

        # Numeric environment variables
        for env_var, config_key in [
            ("TRAKBRIDGE_BATCH_SIZE_THRESHOLD", "batch_size_threshold"),
            ("TRAKBRIDGE_MAX_CONCURRENT_TASKS", "max_concurrent_tasks"),
        ]:
            if env_var in os.environ:
                try:
                    env_config[config_key] = int(os.environ[env_var])
                except ValueError:
                    logger.warning(
                        f"Invalid value for {env_var}: {os.environ[env_var]}"
                    )

        return env_config

    def validate_performance_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and sanitize performance configuration

        Args:
            config: Raw configuration dictionary

        Returns:
            Validated configuration with defaults for missing values
        """
        defaults = self._get_default_performance_config()
        validated = {}

        # Validate boolean values
        for key in ["enabled", "fallback_on_error", "enable_performance_logging"]:
            value = config.get(key, defaults[key])
            validated[key] = (
                bool(value) if isinstance(value, (bool, str)) else defaults[key]
            )

        # Validate positive integers
        for key in ["batch_size_threshold", "max_concurrent_tasks"]:
            value = config.get(key, defaults[key])
            if isinstance(value, (int, float)) and value > 0:
                validated[key] = int(value)
            else:
                validated[key] = defaults[key]
                logger.warning(f"Invalid {key}: {value}, using default {defaults[key]}")

        # Validate timeout (allow 0 for no timeout)
        timeout = config.get("processing_timeout", defaults["processing_timeout"])
        if isinstance(timeout, (int, float)) and timeout >= 0:
            validated["processing_timeout"] = float(timeout)
        else:
            validated["processing_timeout"] = defaults["processing_timeout"]

        # Validate circuit breaker config
        cb_config = config.get("circuit_breaker", defaults["circuit_breaker"])
        if isinstance(cb_config, dict):
            validated["circuit_breaker"] = {
                "enabled": bool(
                    cb_config.get("enabled", defaults["circuit_breaker"]["enabled"])
                ),
                "failure_threshold": max(
                    1,
                    int(
                        cb_config.get(
                            "failure_threshold",
                            defaults["circuit_breaker"]["failure_threshold"],
                        )
                    ),
                ),
                "recovery_timeout": max(
                    1.0,
                    float(
                        cb_config.get(
                            "recovery_timeout",
                            defaults["circuit_breaker"]["recovery_timeout"],
                        )
                    ),
                ),
            }
        else:
            validated["circuit_breaker"] = defaults["circuit_breaker"]

        return validated

    def reload_performance_config(self, config_path: Optional[str] = None):
        """Reload configuration from file"""
        old_config = self.parallel_config.copy()

        # Load new config
        if config_path:
            loaded = self.load_performance_config(config_path)
            if loaded and "parallel_processing" in loaded:
                self.parallel_config = loaded["parallel_processing"]

        self._load_performance_config()

        if old_config != self.parallel_config:
            logger.info("Performance configuration reloaded with changes")

    def should_log_performance(self) -> bool:
        """Check if performance logging is enabled"""
        return self.parallel_config.get("enable_performance_logging", True)

    def _choose_processing_method(self, locations: List[Dict[str, Any]]) -> str:
        """
        Choose between serial and parallel processing based on configuration

        Args:
            locations: List of location data

        Returns:
            'serial' or 'parallel' indicating which method to use
        """
        # Check if parallel processing is enabled
        if not self.parallel_config.get("enabled", True):
            return "serial"

        # Check circuit breaker
        if self.is_circuit_breaker_open():
            return "serial"

        # Check batch size threshold
        if len(locations) < self.parallel_config.get("batch_size_threshold", 10):
            return "serial"

        return "parallel"

    async def create_cot_events_with_fallback(
        self,
        locations: List[Dict[str, Any]],
        cot_type: str,
        stale_time: int,
        cot_type_mode: str = "stream",
    ) -> List[bytes]:
        """
        Create COT events with automatic fallback to serial processing on error

        Args:
            locations: List of location dictionaries
            cot_type: COT event type
            stale_time: Event stale time in seconds
            cot_type_mode: Processing mode

        Returns:
            List of COT events as bytes
        """
        if not locations:
            return []

        processing_method = self._choose_processing_method(locations)

        if processing_method == "serial":
            if self.should_log_performance():
                logger.debug(f"Using serial processing for {len(locations)} locations")
            return await self._create_pytak_events(
                locations, cot_type, stale_time, cot_type_mode
            )

        # Try parallel processing with fallback
        self.fallback_statistics["total_parallel_attempts"] += 1

        try:
            # Apply processing timeout if configured
            timeout = self.parallel_config.get("processing_timeout", 0)
            if timeout > 0:
                result = await asyncio.wait_for(
                    self._create_parallel_pytak_events(
                        locations, cot_type, stale_time, cot_type_mode
                    ),
                    timeout=timeout,
                )
            else:
                result = await self._create_parallel_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )

            # Record successful parallel processing
            self.record_successful_parallel_processing()

            if self.should_log_performance():
                logger.debug(
                    f"Parallel processing succeeded for {len(locations)} locations"
                )

            return result

        except Exception as e:
            # Check if fallback is enabled
            if not self.parallel_config.get("fallback_on_error", True):
                logger.error(f"Parallel processing failed and fallback disabled: {e}")
                raise

            # Record failure and fallback
            error_type = type(e).__name__
            if isinstance(e, asyncio.TimeoutError):
                error_type = "timeout"

            self.record_fallback_event(error_type, str(e))

            logger.warning(
                f"Parallel processing failed ({error_type}), falling back to serial processing: {e}"
            )

            # Fallback to serial processing
            try:
                result = await self._create_pytak_events(
                    locations, cot_type, stale_time, cot_type_mode
                )
                logger.info(f"Serial fallback succeeded for {len(locations)} locations")
                return result
            except Exception as fallback_error:
                logger.error(f"Serial fallback also failed: {fallback_error}")
                raise

    def record_fallback_event(self, reason: str, error_message: str):
        """Record a fallback event for monitoring"""
        self.fallback_statistics["total_fallbacks"] += 1
        self.fallback_statistics["consecutive_failures"] += 1
        self.fallback_statistics["last_failure_time"] = time.time()

        if reason not in self.fallback_statistics["fallback_reasons"]:
            self.fallback_statistics["fallback_reasons"][reason] = 0
        self.fallback_statistics["fallback_reasons"][reason] += 1

        # Check circuit breaker
        if self.parallel_config.get("circuit_breaker", {}).get(
            "enabled", True
        ) and self.fallback_statistics[
            "consecutive_failures"
        ] >= self.parallel_config.get(
            "circuit_breaker", {}
        ).get(
            "failure_threshold", 3
        ):
            self.fallback_statistics["circuit_breaker_open"] = True
            logger.warning(
                f"Circuit breaker opened after {self.fallback_statistics['consecutive_failures']} failures"
            )

    def record_successful_parallel_processing(self):
        """Record successful parallel processing"""
        self.fallback_statistics["successful_parallel_operations"] += 1
        self.fallback_statistics["consecutive_failures"] = 0
        self.fallback_statistics["last_success_time"] = time.time()
        self.fallback_statistics["circuit_breaker_open"] = False

    def get_fallback_statistics(self) -> Dict[str, Any]:
        """Get current fallback statistics"""
        stats = self.fallback_statistics.copy()

        # Calculate fallback rate
        total_attempts = stats["total_parallel_attempts"] + stats["total_fallbacks"]
        if total_attempts > 0:
            stats["fallback_rate"] = stats["total_fallbacks"] / total_attempts
        else:
            stats["fallback_rate"] = 0.0

        return stats

    def is_parallel_processing_healthy(self) -> bool:
        """Check if parallel processing is healthy based on recent performance"""
        # Consider healthy if we've had recent successes and low failure rate
        recent_successes = self.fallback_statistics["successful_parallel_operations"]
        consecutive_failures = self.fallback_statistics["consecutive_failures"]

        # Healthy if we have successes and not too many consecutive failures
        return recent_successes > 0 and consecutive_failures < 3

    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is currently open"""
        if not self.fallback_statistics.get("circuit_breaker_open", False):
            return False

        # Check if recovery timeout has passed
        last_failure = self.fallback_statistics.get("last_failure_time")
        if last_failure is None:
            return False

        recovery_timeout = self.parallel_config.get("circuit_breaker", {}).get(
            "recovery_timeout", 60.0
        )
        return (time.time() - last_failure) < recovery_timeout

    def extract_uid_from_cot_event(self, event: bytes) -> Optional[str]:
        """
        Extract device UID from COT event XML for deduplication.

        Args:
            event: COT event XML as bytes

        Returns:
            Device UID if found, None if extraction fails
        """
        try:
            root = ET.fromstring(event.decode("utf-8"))
            uid = root.get("uid")
            return uid
        except Exception as e:
            logger.warning(f"Failed to extract UID from COT event: {e}")
            return None

    def extract_timestamp_from_cot_event(self, event: bytes) -> Optional[datetime]:
        """
        Extract timestamp from COT event XML for freshness comparison.

        Args:
            event: COT event XML as bytes

        Returns:
            Event timestamp if found, None if extraction fails
        """
        try:
            root = ET.fromstring(event.decode("utf-8"))
            time_str = root.get("time")
            if time_str:
                # Parse ISO format timestamp
                return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return None
        except Exception as e:
            logger.warning(f"Failed to extract timestamp from COT event: {e}")
            return None

    async def remove_events_by_uid(
        self, tak_server_id: int, uids_to_remove: List[str]
    ) -> int:
        """
        Remove events with specific UIDs from the queue.

        Args:
            tak_server_id: TAK server ID
            uids_to_remove: List of device UIDs to remove from queue

        Returns:
            Number of events removed
        """
        if tak_server_id not in self.queues:
            return 0

        queue = self.queues[tak_server_id]

        # Create new temporary queue to hold non-matching events
        temp_events = []
        removed_count = 0

        # Drain the queue and filter out events with matching UIDs
        while not queue.empty():
            try:
                event = queue.get_nowait()
                uid = self.extract_uid_from_cot_event(event)

                if uid in uids_to_remove:
                    removed_count += 1
                    logger.debug(f"Removing old event for device {uid}")
                else:
                    temp_events.append(event)

            except asyncio.QueueEmpty:
                break

        # Put back the events we want to keep
        for event in temp_events:
            await queue.put(event)

        if removed_count > 0:
            logger.info(
                f"Removed {removed_count} old events from queue for TAK server {tak_server_id}"
            )

        return removed_count

    async def enqueue_with_replacement(
        self, events: List[bytes], tak_server_id: int
    ) -> bool:
        """
        Enqueue events while replacing outdated ones for same devices.

        This implements the core queue management enhancement to prevent event accumulation.
        Events from same device UID replace older events instead of accumulating.

        Args:
            events: List of COT events to enqueue
            tak_server_id: Target TAK server ID

        Returns:
            True if successfully processed, False otherwise
        """
        if tak_server_id not in self.queues:
            available_queues = list(self.queues.keys())
            available_workers = list(self.workers.keys())
            logger.error(
                f"No queue found for TAK server {tak_server_id}. Available queues: {available_queues}, Available workers: {available_workers}"
            )
            return False

        if not events:
            return True

        try:
            queue = self.queues[tak_server_id]
            queue_size_before = queue.qsize()

            # Track statistics
            new_events = 0
            updated_events = 0
            skipped_events = 0

            # Group events by UID and find newest timestamp for each device
            device_events = {}
            uids_to_remove = []

            for event in events:
                uid = self.extract_uid_from_cot_event(event)
                timestamp = self.extract_timestamp_from_cot_event(event)

                if uid is None:
                    logger.warning("Event has no UID, skipping deduplication")
                    await queue.put(event)
                    new_events += 1
                    continue

                if timestamp is None:
                    logger.warning(
                        f"Event {uid} has no timestamp, skipping deduplication"
                    )
                    await queue.put(event)
                    new_events += 1
                    continue

                # Get or create server-specific device state manager (lazy initialization)
                if tak_server_id not in self.device_state_managers:
                    self.device_state_managers[tak_server_id] = DeviceStateManager()

                server_device_manager = self.device_state_managers[tak_server_id]

                # Check if we should update this device
                if server_device_manager.should_update_device(uid, timestamp):
                    # Update device state
                    server_device_manager.update_device_state(
                        uid, {"timestamp": timestamp, "uid": uid}
                    )

                    # Track for old event removal
                    uids_to_remove.append(uid)
                    device_events[uid] = event

                    # Check if this is a new device or an update
                    if uid in server_device_manager.device_states:
                        updated_events += 1
                    else:
                        new_events += 1
                else:
                    # Event is older than current state, skip it
                    skipped_events += 1
                    logger.debug(f"Skipping older event for device {uid}")
                    continue

            # Remove old events for devices we're updating
            if uids_to_remove:
                removed_count = await self.remove_events_by_uid(
                    tak_server_id, uids_to_remove
                )
                logger.debug(
                    f"Removed {removed_count} old events for {len(uids_to_remove)} devices"
                )

            # Add new/updated events to queue
            for uid, event in device_events.items():
                await queue.put(event)

            queue_size_after = queue.qsize()

            # Log replacement statistics
            logger.debug(
                f"Queue replacement statistics for TAK server {tak_server_id}: "
                f"new={new_events}, updated={updated_events}, skipped={skipped_events}, "
                f"queue size: {queue_size_before} → {queue_size_after}"
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to enqueue events with replacement for TAK server {tak_server_id}: {e}"
            )
            return False


class PersistentCOTService:
    """
    Manages persistent PyTAK workers and queues for each TAK server.
    """

    def __init__(self):
        self.workers: Dict[int, asyncio.Task] = {}  # tak_server_id -> worker task
        self.queues: Dict[int, asyncio.Queue] = {}  # tak_server_id -> event queue
        self.connections: Dict[int, Any] = {}  # tak_server_id -> pytak connection
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self.device_state_managers: Dict[int, DeviceStateManager] = (
            {}
        )  # Per-server device state managers for queue replacement functionality

    async def start_worker(self, tak_server):
        """
        Start a persistent PyTAK worker for a given TAK server.
        Returns True if successful, False otherwise.
        """
        tak_server_id = tak_server.id
        if tak_server_id in self.workers:
            logger.info(f"Worker for TAK server {tak_server_id} already running.")
            return True  # Return True since worker is already running

        if not PYTAK_AVAILABLE:
            logger.error("PyTAK not available. Cannot start persistent worker.")
            return False

        queue = asyncio.Queue()
        self.queues[tak_server_id] = queue

        # Create an event to signal when connection is established
        connection_ready = asyncio.Event()
        connection_error = None

        async def cot_worker():
            """PyTAK worker coroutine"""
            nonlocal connection_error
            try:
                logger.info(
                    f"Starting persistent worker for TAK server {tak_server.name}"
                )

                # Create PyTAK configuration
                config = await self._create_pytak_config(tak_server)

                # Create connection using PyTAK's protocol factory with timeout
                try:
                    logger.debug(
                        f"Attempting to connect to TAK server {tak_server.name} "
                        f"at {tak_server.host}:{tak_server.port}"
                    )
                    # Add timeout to prevent hanging
                    connection_result = await asyncio.wait_for(
                        pytak.protocol_factory(config),
                        timeout=30.0,  # 30 second timeout
                    )

                    # Handle the connection result (might be a tuple for TCP)
                    if (
                        isinstance(connection_result, tuple)
                        and len(connection_result) == 2
                    ):
                        reader, writer = connection_result
                        logger.info(
                            f"Received (reader, writer) tuple for TAK server {tak_server.name}"
                        )
                        self.connections[tak_server_id] = (reader, writer)
                    else:
                        logger.info(
                            f"Received single connection object for TAK server {tak_server.name}"
                        )
                        self.connections[tak_server_id] = connection_result

                    logger.info(
                        f"Successfully connected to TAK server {tak_server.name}"
                    )

                    # Signal that connection is ready
                    connection_ready.set()

                except asyncio.TimeoutError:
                    error_msg = f"Timeout connecting to TAK server {tak_server.name}"
                    logger.error(error_msg)
                    connection_error = Exception(error_msg)
                    return
                except Exception as e:
                    error_msg = (
                        f"Failed to connect to TAK server {tak_server.name}: {e}"
                    )
                    logger.error(error_msg)
                    connection_error = Exception(error_msg)
                    return

                # Start the transmission worker
                await self._transmission_worker(
                    queue, self.connections[tak_server_id], tak_server
                )

            except Exception as e:
                logger.error(f"PyTAK worker failed for TAK server {tak_server_id}: {e}")
                connection_error = e
                # Clean up on error
                await self._cleanup_worker(tak_server_id)

        try:
            # Create the task
            task = asyncio.create_task(cot_worker())
            self.workers[tak_server_id] = task

            # Wait for connection to be established (with timeout)
            try:
                await asyncio.wait_for(
                    connection_ready.wait(), timeout=35.0
                )  # Slightly longer than connection timeout
                logger.info(f"Started PyTAK worker for TAK server {tak_server_id}.")
                return True
            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout waiting for worker to start for TAK server {tak_server_id}"
                )
                # Clean up the task
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                return False

        except Exception as e:
            logger.error(f"Failed to start worker for TAK server {tak_server_id}: {e}")
            return False

        # Check if there was a connection error
        if connection_error:
            logger.error(
                f"Connection error for TAK server {tak_server_id}: {connection_error}"
            )
            return False

    @staticmethod
    async def _transmission_worker(queue: asyncio.Queue, connection, tak_server):
        """Handle transmission of COT events from queue"""
        logger.info(
            f"Starting transmission worker for TAK server '{tak_server.name}' (ID: {tak_server.id})"
        )

        # Track queue processing statistics
        events_processed = 0
        last_queue_size_log = None
        queue_empty_logged = False

        # Handle the case where connection might be a tuple (reader, writer)
        if isinstance(connection, tuple) and len(connection) == 2:
            reader, writer = connection
            logger.info(
                f"Using (reader, writer) tuple for TAK server '{tak_server.name}'"
            )
            use_writer = True
        else:
            reader = connection
            writer = None
            use_writer = False
            logger.info(
                f"Using single connection object for TAK server '{tak_server.name}'"
            )

        try:
            while True:
                try:
                    # Check queue size periodically for logging
                    current_queue_size = queue.qsize()

                    # Log when queue becomes empty after having events
                    if (
                        current_queue_size == 0
                        and not queue_empty_logged
                        and events_processed > 0
                    ):
                        logger.info(
                            f"Queue cleared for TAK server '{tak_server.name}' - "
                            f"all {events_processed} events have been processed and transmitted"
                        )
                        queue_empty_logged = True

                    # Log significant queue size changes (every 10 events)
                    if (
                        last_queue_size_log is None
                        or abs(current_queue_size - last_queue_size_log) >= 10
                    ):
                        if current_queue_size > 0:
                            logger.debug(
                                f"Queue status for TAK server '{tak_server.name}': "
                                f"{current_queue_size} events pending, "
                                f"{events_processed} events processed so far"
                            )
                        last_queue_size_log = current_queue_size

                    logger.debug(
                        f"Waiting for events from queue for TAK server '{tak_server.name}'..."
                    )

                    # Get event from queue with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    if event is None:  # Shutdown signal
                        logger.info(
                            f"Received shutdown signal for TAK server '{tak_server.name}'. "
                            f"Total events processed: {events_processed}"
                        )
                        break

                    # Reset queue empty flag when we get an event
                    if queue_empty_logged:
                        queue_empty_logged = False
                        logger.debug(
                            f"Queue activity resumed for TAK server '{tak_server.name}'"
                        )

                    logger.debug(
                        f"Processing event {events_processed + 1} from queue for TAK server '{tak_server.name}'"
                    )

                    # Send the event using the appropriate method
                    if use_writer and writer:
                        # Use writer for TCP connections
                        writer.write(event)
                        await writer.drain()
                        logger.debug(
                            f"Successfully transmitted COT event to TAK server '{tak_server.name}'"
                        )
                    elif hasattr(reader, "send"):
                        # Use reader.send for other connection types
                        await reader.send(event)
                        logger.debug(
                            f"Successfully transmitted COT event to TAK server '{tak_server.name}'"
                        )
                    else:
                        logger.error(
                            f"No suitable send method found for TAK server '{tak_server.name}'. "
                            f"Event {events_processed + 1} not transmitted."
                        )
                        queue.task_done()
                        continue

                    events_processed += 1

                    # Log milestone events (every 50 events)
                    if events_processed % 50 == 0:
                        logger.info(
                            f"Transmission milestone for TAK server '{tak_server.name}': "
                            f"{events_processed} events successfully transmitted"
                        )

                    # Mark task as done
                    queue.task_done()

                except asyncio.TimeoutError:
                    # Timeout is normal when no events are available
                    logger.debug(
                        f"No events received (timeout) for TAK server '{tak_server.name}'"
                    )
                    continue

                except Exception as e:
                    logger.error(
                        f"Error transmitting COT event to TAK server '{tak_server.name}': {e}. "
                        f"Event {events_processed + 1} failed."
                    )
                    # Mark task as done even on error
                    queue.task_done()

        except Exception as e:
            logger.error(
                f"Transmission worker error for TAK server '{tak_server.name}': {e}"
            )
        finally:
            # Log final statistics
            logger.info(
                f"Transmission worker shutting down for TAK server '{tak_server.name}'. "
                f"Total events processed: {events_processed}"
            )

            # Clean up connection
            if use_writer and writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                    logger.info(
                        f"Closed writer connection for TAK server '{tak_server.name}'"
                    )
                except Exception as e:
                    logger.debug(
                        f"Error closing writer for TAK server '{tak_server.name}': {e}"
                    )
            elif hasattr(reader, "close"):
                try:
                    await reader.close()
                    logger.info(
                        f"Closed reader connection for TAK server '{tak_server.name}'"
                    )
                except Exception as e:
                    logger.debug(
                        f"Error closing reader for TAK server '{tak_server.name}': {e}"
                    )

    def log_queue_status(self, tak_server_id: int, context: str = ""):
        """Log current queue status for a TAK server"""
        if tak_server_id not in self.queues:
            logger.warning(
                f"No queue found for TAK server {tak_server_id} when logging status"
            )
            return

        queue = self.queues[tak_server_id]
        queue_size = queue.qsize()

        context_str = f" ({context})" if context else ""

        if queue_size == 0:
            logger.info(f"Queue is empty for TAK server {tak_server_id}{context_str}")
        else:
            logger.info(
                f"Queue contains {queue_size} pending events for TAK server {tak_server_id}{context_str}"
            )

    @staticmethod
    async def _create_pytak_config(tak_server):
        """Create PyTAK configuration from TAK server settings"""
        from configparser import ConfigParser

        config = ConfigParser(interpolation=None)
        config.add_section("pytak")

        # Determine protocol
        protocol = "tls" if tak_server.protocol.lower() in ["tls", "ssl"] else "tcp"
        config.set(
            "pytak", "COT_URL", f"{protocol}://{tak_server.host}:{tak_server.port}"
        )

        # Add TLS configuration if needed
        if protocol == "tls":
            config.set(
                "pytak", "PYTAK_TLS_DONT_VERIFY", str(not tak_server.verify_ssl).lower()
            )

            # Handle P12 certificate if available
            if tak_server.cert_p12 and len(tak_server.cert_p12) > 0:
                try:
                    cert_pem, key_pem = EnhancedCOTService._extract_p12_certificate(
                        tak_server.cert_p12, tak_server.get_cert_password()
                    )
                    cert_path, key_path = EnhancedCOTService._create_temp_cert_files(
                        cert_pem, key_pem
                    )
                    config.set("pytak", "PYTAK_TLS_CLIENT_CERT", cert_path)
                    config.set("pytak", "PYTAK_TLS_CLIENT_KEY", key_path)
                except Exception as e:
                    logger.error(f"Failed to configure P12 certificate: {e}")

        logger.debug(
            f"Created PyTAK config for {tak_server.name}: {dict(config['pytak'])}"
        )
        return config["pytak"]

    async def stop_worker(self, tak_server_id: int):
        """
        Stop the PyTAK worker for a given TAK server.
        """
        await self._cleanup_worker(tak_server_id)

    async def _cleanup_worker(self, tak_server_id: int):
        """Clean up worker resources"""
        try:
            # Send shutdown signal to queue
            if tak_server_id in self.queues:
                await self.queues[tak_server_id].put(None)

            # Cancel worker task
            if tak_server_id in self.workers:
                task = self.workers[tak_server_id]
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                del self.workers[tak_server_id]

            # Clean up connection
            if tak_server_id in self.connections:
                connection = self.connections[tak_server_id]
                try:
                    await connection.close()
                except Exception as e:
                    logger.debug(f"Error closing connection: {e}")
                del self.connections[tak_server_id]

            # Clean up queue
            if tak_server_id in self.queues:
                del self.queues[tak_server_id]

            logger.info(f"Cleaned up PyTAK worker for TAK server {tak_server_id}.")

        except Exception as e:
            logger.error(f"Error cleaning up worker {tak_server_id}: {e}")

    async def enqueue_event(self, event: bytes, tak_server_id: int):
        """
        Put a COT event onto the TAK server's queue.
        """
        if tak_server_id not in self.queues:
            logger.error(
                f"No queue found for TAK server {tak_server_id}. Event not sent."
            )
            return False

        try:
            queue = self.queues[tak_server_id]
            queue_size_before = queue.qsize()

            # Log if this is the first event being added to an empty queue
            if queue_size_before == 0:
                logger.info(
                    f"Adding first event to empty queue for TAK server {tak_server_id}"
                )

            await queue.put(event)
            queue_size_after = queue.qsize()

            logger.debug(
                f"Successfully enqueued COT event for TAK server {tak_server_id}. "
                f"Queue size: {queue_size_before} → {queue_size_after}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to enqueue event for TAK server {tak_server_id}: {e}")
            return False

    async def ensure_workers(self):
        """
        Ensure a worker is running for each TAK server in the database.
        """
        try:
            # Import here to avoid circular imports
            from database import db
            from models.tak_server import TakServer

            tak_servers = db.session.query(TakServer).all()
            for tak_server in tak_servers:
                if tak_server.id not in self.workers:
                    await self.start_worker(tak_server)
        except Exception as e:
            logger.error(f"Error ensuring workers: {e}")

    def get_worker_status(self, tak_server_id: int) -> Dict[str, Any]:
        """Get status information for a specific worker"""
        status = {
            "worker_running": tak_server_id in self.workers,
            "queue_exists": tak_server_id in self.queues,
            "connection_exists": tak_server_id in self.connections,
            "queue_size": 0,
        }

        if tak_server_id in self.queues:
            status["queue_size"] = self.queues[tak_server_id].qsize()

        if tak_server_id in self.workers:
            task = self.workers[tak_server_id]
            status["worker_done"] = task.done()
            status["worker_cancelled"] = task.cancelled()
            if task.done() and not task.cancelled():
                try:
                    exception = task.exception()
                    status["worker_exception"] = str(exception) if exception else None
                except Exception:
                    status["worker_exception"] = "Unknown"

        return status

    def get_all_worker_status(self) -> Dict[int, Dict[str, Any]]:
        """Get status for all workers"""
        return {
            tak_server_id: self.get_worker_status(tak_server_id)
            for tak_server_id in set(
                list(self.workers.keys()) + list(self.queues.keys())
            )
        }

    def get_detailed_worker_status(self, tak_server_id: int) -> Dict[str, Any]:
        """Get detailed status information for a specific worker"""
        status = self.get_worker_status(tak_server_id)

        # Add more detailed information
        if tak_server_id in self.queues:
            queue = self.queues[tak_server_id]
            status["queue_size"] = queue.qsize()
            status["queue_full"] = queue.full()
            status["queue_empty"] = queue.empty()

        if tak_server_id in self.workers:
            task = self.workers[tak_server_id]
            status["worker_done"] = task.done()
            status["worker_cancelled"] = task.cancelled()
            status["worker_running"] = not task.done() and not task.cancelled()

            if task.done() and not task.cancelled():
                try:
                    exception = task.exception()
                    status["worker_exception"] = str(exception) if exception else None
                except Exception:
                    status["worker_exception"] = "Unknown"

        if tak_server_id in self.connections:
            connection = self.connections[tak_server_id]
            status["connection_exists"] = True
            # Try to get connection status if possible
            status["connection_closed"] = getattr(connection, "closed", "Unknown")
        else:
            status["connection_exists"] = False

        return status

    async def test_worker_communication(self, tak_server_id: int) -> bool:
        """Test if the worker is actually processing events"""
        if tak_server_id not in self.queues:
            logger.error(f"No queue for TAK server {tak_server_id}")
            return False

        try:
            # Create a test event
            test_event = b"<test>test</test>"

            # Put it in the queue
            queue = self.queues[tak_server_id]
            await queue.put(test_event)

            # Wait a bit to see if it gets processed
            await asyncio.sleep(2)

            # Check queue size
            queue_size = queue.qsize()
            logger.info(f"Test event queue size after 2 seconds: {queue_size}")

            return queue_size == 0  # If queue is empty, event was processed

        except Exception as e:
            logger.error(f"Error testing worker communication: {e}")
            return False

    async def shutdown(self):
        """Shutdown all workers and clean up resources"""
        logger.info("Shutting down persistent COT service...")

        # Stop all workers
        tasks = []
        for tak_server_id in list(self.workers.keys()):
            tasks.append(self.stop_worker(tak_server_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Final cleanup
        self.workers.clear()
        self.queues.clear()
        self.connections.clear()

        logger.info("Persistent COT service shutdown complete.")

    def extract_uid_from_cot_event(self, event: bytes) -> Optional[str]:
        """
        Extract device UID from COT event XML for deduplication.

        Args:
            event: COT event XML as bytes

        Returns:
            Device UID if found, None if extraction fails
        """
        try:
            root = ET.fromstring(event.decode("utf-8"))
            uid = root.get("uid")
            return uid
        except Exception as e:
            logger.warning(f"Failed to extract UID from COT event: {e}")
            return None

    def extract_timestamp_from_cot_event(self, event: bytes) -> Optional[datetime]:
        """
        Extract timestamp from COT event XML for freshness comparison.

        Args:
            event: COT event XML as bytes

        Returns:
            Event timestamp if found, None if extraction fails
        """
        try:
            root = ET.fromstring(event.decode("utf-8"))
            time_str = root.get("time")
            if time_str:
                # Parse ISO format timestamp
                return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            return None
        except Exception as e:
            logger.warning(f"Failed to extract timestamp from COT event: {e}")
            return None

    async def remove_events_by_uid(
        self, tak_server_id: int, uids_to_remove: List[str]
    ) -> int:
        """
        Remove events with specific UIDs from the queue.

        Args:
            tak_server_id: TAK server ID
            uids_to_remove: List of device UIDs to remove from queue

        Returns:
            Number of events removed
        """
        if tak_server_id not in self.queues:
            return 0

        queue = self.queues[tak_server_id]

        # Create new temporary queue to hold non-matching events
        temp_events = []
        removed_count = 0

        # Drain the queue and filter out events with matching UIDs
        while not queue.empty():
            try:
                event = queue.get_nowait()
                uid = self.extract_uid_from_cot_event(event)

                if uid in uids_to_remove:
                    removed_count += 1
                    logger.debug(f"Removing old event for device {uid}")
                else:
                    temp_events.append(event)

            except asyncio.QueueEmpty:
                break

        # Put back the events we want to keep
        for event in temp_events:
            await queue.put(event)

        if removed_count > 0:
            logger.info(
                f"Removed {removed_count} old events from queue for TAK server {tak_server_id}"
            )

        return removed_count

    async def enqueue_with_replacement(
        self, events: List[bytes], tak_server_id: int
    ) -> bool:
        """
        Enqueue events while replacing outdated ones for same devices.

        This implements the core queue management enhancement to prevent event accumulation.
        Events from same device UID replace older events instead of accumulating.

        Args:
            events: List of COT events to enqueue
            tak_server_id: Target TAK server ID

        Returns:
            True if successfully processed, False otherwise
        """
        if tak_server_id not in self.queues:
            available_queues = list(self.queues.keys())
            available_workers = list(self.workers.keys())
            logger.error(
                f"No queue found for TAK server {tak_server_id}. Available queues: {available_queues}, Available workers: {available_workers}"
            )
            return False

        if not events:
            return True

        try:
            queue = self.queues[tak_server_id]
            queue_size_before = queue.qsize()

            # Track statistics
            new_events = 0
            updated_events = 0
            skipped_events = 0

            # Group events by UID and find newest timestamp for each device
            device_events = {}
            uids_to_remove = []

            for event in events:
                uid = self.extract_uid_from_cot_event(event)
                timestamp = self.extract_timestamp_from_cot_event(event)

                if uid is None:
                    logger.warning("Event has no UID, skipping deduplication")
                    await queue.put(event)
                    new_events += 1
                    continue

                if timestamp is None:
                    logger.warning(
                        f"Event {uid} has no timestamp, skipping deduplication"
                    )
                    await queue.put(event)
                    new_events += 1
                    continue

                # Get or create server-specific device state manager (lazy initialization)
                if tak_server_id not in self.device_state_managers:
                    self.device_state_managers[tak_server_id] = DeviceStateManager()

                server_device_manager = self.device_state_managers[tak_server_id]

                # Check if we should update this device
                if server_device_manager.should_update_device(uid, timestamp):
                    # Update device state
                    server_device_manager.update_device_state(
                        uid, {"timestamp": timestamp, "uid": uid}
                    )

                    # Track for old event removal
                    uids_to_remove.append(uid)
                    device_events[uid] = event

                    # Check if this is a new device or an update
                    if uid in server_device_manager.device_states:
                        updated_events += 1
                    else:
                        new_events += 1
                else:
                    # Event is older than current state, skip it
                    skipped_events += 1
                    logger.debug(f"Skipping older event for device {uid}")
                    continue

            # Remove old events for devices we're updating
            if uids_to_remove:
                removed_count = await self.remove_events_by_uid(
                    tak_server_id, uids_to_remove
                )
                logger.debug(
                    f"Removed {removed_count} old events for {len(uids_to_remove)} devices"
                )

            # Add new/updated events to queue
            for uid, event in device_events.items():
                await queue.put(event)

            queue_size_after = queue.qsize()

            # Log replacement statistics
            logger.debug(
                f"Queue replacement statistics for TAK server {tak_server_id}: "
                f"new={new_events}, updated={updated_events}, skipped={skipped_events}, "
                f"queue size: {queue_size_before} → {queue_size_after}"
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to enqueue events with replacement for TAK server {tak_server_id}: {e}"
            )
            return False


# Singleton instance
cot_service = PersistentCOTService()
