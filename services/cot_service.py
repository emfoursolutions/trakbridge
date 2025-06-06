# =============================================================================
# services/cot_service.py - COT Conversion Service
# =============================================================================

from lxml import etree
from datetime import datetime, timedelta
from typing import List, Dict, Any


class COTService:
    """Service for converting GPS data to Cursor-on-Target (COT) format"""

    @staticmethod
    def create_cot_events(locations: List[Dict[str, Any]],
                          cot_type: str = "a-f-G-U-C",
                          stale_time: int = 300) -> List[bytes]:
        """
        Convert location data to COT events

        Args:
            locations: List of location dictionaries
            cot_type: COT type identifier
            stale_time: Time in seconds before the event becomes stale

        Returns:
            List of COT event XML as bytes
        """
        cot_events = []

        for location in locations:
            # Use location timestamp if available, otherwise use current time
            if 'timestamp' in location and location['timestamp']:
                event_time = location['timestamp']
            else:
                event_time = datetime.utcnow()

            time_str = event_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            stale_str = (event_time + timedelta(seconds=stale_time)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Create COT event element
            cot_event = etree.Element("event")
            cot_event.set("version", "2.0")
            cot_event.set("uid", f"GPS-{location['name']}")
            cot_event.set("time", time_str)
            cot_event.set("start", time_str)
            cot_event.set("stale", stale_str)
            cot_event.set("type", cot_type)
            cot_event.set("how", "m-g")

            # Add point element
            point = etree.SubElement(cot_event, "point")
            point.set("lat", str(location["lat"]))
            point.set("lon", str(location["lon"]))
            point.set("ce", "9999999.0")  # Circular Error
            point.set("le", "9999999.0")  # Linear Error
            point.set("hae", str(location.get("altitude", 0)))  # Height Above Ellipsoid

            # Add detail element
            detail = etree.SubElement(cot_event, "detail")
            contact = etree.SubElement(detail, "contact")
            contact.set("callsign", location["name"])

            # Add description if available
            if location.get("description"):
                remarks = etree.SubElement(detail, "remarks")
                remarks.text = location["description"]

            # Add any additional data
            if location.get("additional_data"):
                for key, value in location["additional_data"].items():
                    elem = etree.SubElement(detail, key)
                    elem.text = str(value)

            cot_events.append(etree.tostring(cot_event, pretty_print=True))

        return cot_events
