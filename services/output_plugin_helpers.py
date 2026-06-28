# ABOUTME: Shared helpers for outbound plugins — message extraction, formatting,
# ABOUTME: filtering, geofence, payload building, dedup and rate-limit utilities.

import base64
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, Optional

import mgrs
from defusedxml import ElementTree as DefusedET

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CoT variable extraction
# ---------------------------------------------------------------------------


def extract_cot_variables(cot_xml: bytes) -> dict:
    """Parse CoT XML bytes and return a flat dict of template variables.

    Returns a dict with sensible defaults for all expected fields.
    Returns an empty dict if the XML cannot be parsed.
    """
    try:
        root = DefusedET.fromstring(cot_xml)
    except Exception as exc:
        logger.warning("output_plugin_helpers: failed to parse CoT XML: %s", exc)
        return {}

    variables: Dict[str, str] = {
        "type": root.get("type", ""),
        "uid": root.get("uid", ""),
        "time": root.get("time", ""),
        "stale": root.get("stale", ""),
        "callsign": "Unknown",
        "lat": "", "lon": "", "hae": "", "mgrs": "",
        "remarks": "",
        "group_name": "", "group_role": "",
        "battery": "",
        "device": "", "platform": "", "os": "", "version": "",
        "speed": "", "course": "",
        "xmpp_username": "",
    }

    point = root.find("point")
    if point is not None:
        variables["lat"] = point.get("lat", "")
        variables["lon"] = point.get("lon", "")
        variables["hae"] = point.get("hae", "")

        if variables["lat"] and variables["lon"]:
            try:
                m = mgrs.MGRS()
                variables["mgrs"] = m.toMGRS(
                    float(variables["lat"]), float(variables["lon"])
                )
            except Exception:
                variables["mgrs"] = ""

    detail = root.find("detail")
    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            variables["callsign"] = contact.get("callsign", "Unknown")
            variables["xmpp_username"] = contact.get("xmppUsername", "")

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            variables["remarks"] = remarks.text

        group = detail.find("__group")
        if group is not None:
            variables["group_name"] = group.get("name", "")
            variables["group_role"] = group.get("role", "")

        status = detail.find("status")
        if status is not None:
            variables["battery"] = status.get("battery", "")

        takv = detail.find("takv")
        if takv is not None:
            variables["device"] = takv.get("device", "")
            variables["platform"] = takv.get("platform", "")
            variables["os"] = takv.get("os", "")
            variables["version"] = takv.get("version", "")

        track = detail.find("track")
        if track is not None:
            variables["speed"] = track.get("speed", "")
            variables["course"] = track.get("course", "")

    return variables


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def format_message(template: str, variables: dict) -> str:
    """Render a format-string template against a variables dict.

    Missing keys produce a descriptive error suffix rather than raising.
    Any other formatting exception returns the raw template unchanged.
    """
    try:
        return template.format(**variables)
    except KeyError as exc:
        logger.warning("Template variable missing: %s", exc)
        return f"{template} [ERROR: missing variable {exc}]"
    except Exception as exc:
        logger.error("Template formatting error: %s", exc)
        return template


# ---------------------------------------------------------------------------
# CoT type pattern matching
# ---------------------------------------------------------------------------


def matches_cot_pattern(cot_type: str, pattern: str) -> bool:
    """Return True if cot_type matches pattern.

    Pattern may end with '*' for prefix matching; otherwise exact match.
    An empty pattern never matches.
    """
    if not pattern:
        return False
    if pattern.endswith("*"):
        return cot_type.startswith(pattern[:-1])
    return cot_type == pattern


# ---------------------------------------------------------------------------
# Geofence check
# ---------------------------------------------------------------------------


def is_within_geofence(lat: float, lon: float, bounds: dict) -> bool:
    """Return True if (lat, lon) falls within the bounding box in bounds.

    Bounds keys: north, south, east, west (numeric or string).
    Fails open (returns True) on conversion errors so events are not silently
    dropped due to bad configuration.
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        north = float(bounds.get("north", 90))
        south = float(bounds.get("south", -90))
        east = float(bounds.get("east", 180))
        west = float(bounds.get("west", -180))
        return south <= lat_f <= north and west <= lon_f <= east
    except (ValueError, TypeError):
        # Fail open: bad config should not silently drop events
        return True


# ---------------------------------------------------------------------------
# Filtering — decides whether an event should be forwarded
# ---------------------------------------------------------------------------


def should_handle(
    cot_xml: bytes,
    uid_filter: str,
    geofence: dict,
    message_rules: list,
) -> tuple:
    """Determine whether a CoT event should be forwarded.

    Applies filters in order: global UID regex → geofence → message rules.
    Returns (True, template_str) when the event matches a rule, otherwise
    (False, "").

    Args:
        cot_xml:       Raw CoT XML bytes to inspect.
        uid_filter:    Optional regex string applied to the event UID.
                       Empty string means no UID filter.
        geofence:      Dict with keys 'enabled' (bool-like) and 'bounds'
                       (dict with north/south/east/west).  Empty dict means
                       no geofence restriction.
        message_rules: List of rule dicts with keys: enabled, cot_type_pattern,
                       format_template, and optionally uid_filter.
    """
    try:
        root = DefusedET.fromstring(cot_xml)
    except Exception as exc:
        logger.warning("should_handle: failed to parse CoT XML: %s", exc)
        return (False, "")

    cot_type = root.get("type", "")
    uid = root.get("uid", "")

    point = root.find("point")
    lat = point.get("lat", "") if point is not None else ""
    lon = point.get("lon", "") if point is not None else ""

    # Global UID filter
    if uid_filter:
        try:
            if not re.match(uid_filter, uid):
                return (False, "")
        except re.error:
            return (False, "")

    # Geofence
    if geofence.get("enabled", False):
        bounds = geofence.get("bounds", {})
        if bounds and lat and lon:
            if not is_within_geofence(lat, lon, bounds):
                return (False, "")

    # Message rules — first matching rule wins
    if not message_rules:
        return (False, "")

    for rule in message_rules:
        if not rule.get("enabled", True):
            continue

        # Per-rule UID filter
        rule_uid_filter = rule.get("uid_filter", "")
        if rule_uid_filter:
            try:
                if not re.match(rule_uid_filter, uid):
                    continue
            except re.error:
                continue

        pattern = rule.get("cot_type_pattern", "")
        if pattern and matches_cot_pattern(cot_type, pattern):
            return (True, rule.get("format_template", ""))

    return (False, "")


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


def build_payload(
    variables: dict,
    output_format: str,
    custom_template: str,
    include_raw_xml: bool,
    raw_xml: bytes,
) -> str:
    """Construct the output payload from pre-extracted variables.

    Args:
        variables:       Output of extract_cot_variables().
        output_format:   One of "json", "xml", or "custom_template".
        custom_template: Template string used when output_format is "custom_template".
        include_raw_xml: When True and output_format is "json", embed the raw XML
                         as a base64-encoded field.
        raw_xml:         The original CoT XML bytes (used for "xml" passthrough
                         and for include_raw_xml encoding).

    Returns the payload as a string (JSON string for "json", raw bytes for "xml",
    or formatted string for "custom_template").
    """
    if output_format == "xml":
        # Raw CoT passthrough — return bytes unchanged
        return raw_xml

    if output_format == "custom_template":
        return format_message(custom_template, variables)

    # Default: structured JSON
    payload = {
        "source": "trakbridge",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cot": {
            "type": variables.get("type", ""),
            "uid": variables.get("uid", ""),
            "time": variables.get("time", ""),
            "stale": variables.get("stale", ""),
        },
        "contact": {
            "callsign": variables.get("callsign", "Unknown"),
        },
        "position": {
            "lat": variables.get("lat", ""),
            "lon": variables.get("lon", ""),
            "hae": variables.get("hae", ""),
            "mgrs": variables.get("mgrs", ""),
            "speed": variables.get("speed", ""),
            "course": variables.get("course", ""),
        },
        "group": {
            "name": variables.get("group_name", ""),
            "role": variables.get("group_role", ""),
        },
        "device": {
            "device": variables.get("device", ""),
            "platform": variables.get("platform", ""),
            "os": variables.get("os", ""),
            "version": variables.get("version", ""),
            "battery": variables.get("battery", ""),
        },
        "remarks": variables.get("remarks", ""),
    }

    if include_raw_xml:
        payload["raw_xml"] = base64.b64encode(raw_xml).decode("ascii")

    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Custom HTTP headers parsing
# ---------------------------------------------------------------------------


def parse_custom_headers(headers_text: str) -> Dict[str, str]:
    """Parse newline-separated 'Header-Name: value' lines into a dict.

    Blank lines and lines without ':' are skipped.  Leading/trailing
    whitespace is stripped from both key and value.  Values may contain
    additional ':' characters (e.g. Bearer tokens).
    """
    headers: Dict[str, str] = {}
    if not headers_text:
        return headers
    for line in headers_text.strip().split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip()] = value.strip()
    return headers


# ---------------------------------------------------------------------------
# Deduplicator
# ---------------------------------------------------------------------------


class Deduplicator:
    """Tracks recently-seen message keys with a TTL to suppress duplicates.

    check(key) returns True when the key is NEW (caller should proceed) and
    False when the key is a DUPLICATE within the TTL window (caller should
    drop the event).  This matches the expected caller contract: True = go,
    False = skip.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        # Maps key → timestamp of first-seen
        self._seen: Dict[str, float] = {}

    def check(self, key: str) -> bool:
        """Return True if key is new; False if it is a duplicate within TTL."""
        now = time.time()
        # Prune before checking so expired entries don't block new events
        self._seen = {k: v for k, v in self._seen.items() if now - v < self._ttl}

        if key in self._seen:
            return False  # duplicate

        self._seen[key] = now
        return True  # new

    def prune(self) -> None:
        """Remove all expired entries from the seen-message store."""
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if now - v < self._ttl}


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """Enforces a maximum event throughput using a token-bucket-style interval check.

    check() returns True when the event is within the allowed rate (proceed)
    and False when the rate is exceeded (drop).

    max_rate_per_sec=None or 0 means unlimited — check() always returns True.
    """

    def __init__(self, max_rate_per_sec: Optional[float]) -> None:
        self._max_rate = max_rate_per_sec
        # None means "never been called" — avoids confusion with real time value 0.0
        self._last_event_time: Optional[float] = None

    def check(self) -> bool:
        """Return True if the event is within the allowed rate; False if over limit."""
        if not self._max_rate:
            return True

        now = time.time()
        min_interval = 1.0 / self._max_rate

        if self._last_event_time is None or (now - self._last_event_time) >= min_interval:
            self._last_event_time = now
            return True

        return False
