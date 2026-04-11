"""
ABOUTME: HTTP endpoint for receiving push data from external devices, converting
ABOUTME: to CoT XML via inbound plugins, and distributing to TAK servers.
"""

import asyncio
import ipaddress
import json
import logging
from typing import Dict, List

from flask import Blueprint, jsonify, request

from database import db
from models.stream import Stream
from plugins.plugin_manager import get_plugin_manager

logger = logging.getLogger(__name__)

bp = Blueprint("inbound", __name__)

# Limits
MAX_PAYLOAD_BYTES = 1_048_576  # 1 MB
MAX_LOCATIONS_PER_REQUEST = 100

# Anti-enumeration: identical response for not-found, auth-fail, inactive, wrong mode
_NOT_FOUND_RESPONSE = {"error": "Not found"}, 404


def _mask_api_key(key: str) -> str:
    """Mask API key for safe logging, showing only last 4 chars."""
    if not key or len(key) <= 4:
        return "****"
    return f"****{key[-4:]}"


def _check_ip_allowlist(allowlist_json: str, remote_addr: str) -> bool:
    """
    Check if remote_addr is in the allowlist CIDRs.

    Args:
        allowlist_json: JSON string of CIDR list, or None to allow all
        remote_addr: Client IP address

    Returns:
        True if allowed, False if blocked
    """
    if not allowlist_json:
        return True

    try:
        cidrs = json.loads(allowlist_json)
        client_ip = ipaddress.ip_address(remote_addr)
        return any(client_ip in ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Invalid IP allowlist config: {e}")
        # Fail closed — if allowlist is configured but malformed, deny
        return False


def _validate_coordinates(locations: List[Dict]) -> str | None:
    """
    Validate coordinate bounds for all locations.

    Returns:
        Error message string if invalid, None if all valid
    """
    for loc in locations:
        lat = loc.get("lat")
        lon = loc.get("lon")
        if lat is not None and (lat < -90 or lat > 90):
            return f"Invalid coordinate: latitude {lat} outside ±90 range"
        if lon is not None and (lon < -180 or lon > 180):
            return f"Invalid coordinate: longitude {lon} outside ±180 range"
    return None


def _process_inbound_async(locations, stream) -> Dict:
    """
    Run the async InboundCOTService from a sync Flask context.

    Returns:
        Result dict from InboundCOTService.process_inbound_locations
    """
    from services.inbound_cot_service import InboundCOTService

    service = InboundCOTService()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an already-running loop (e.g., Hypercorn) — use a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    service.process_inbound_locations(locations, stream),
                )
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(
                service.process_inbound_locations(locations, stream)
            )
    except RuntimeError:
        # No event loop — create one
        return asyncio.run(service.process_inbound_locations(locations, stream))


@bp.route("/<int:stream_id>/data", methods=["POST"])
def receive_inbound_data(stream_id: int):
    """
    Receive push data from an external device or system.

    Flow:
        1. Validate stream exists, is active, and is inbound mode
        2. Check IP allowlist
        3. Instantiate plugin and validate auth
        4. Validate Content-Type against plugin's accepted types
        5. Parse payload via plugin.transform_payload()
        6. Validate coordinates and location count
        7. Create CoT events and distribute to TAK servers
        8. Return per-server delivery status
    """
    # --- Payload size check (before any DB lookup) ---
    content_length = request.content_length or 0
    if content_length > MAX_PAYLOAD_BYTES:
        return jsonify({"error": "Payload too large"}), 413

    raw_body = request.get_data()
    if len(raw_body) > MAX_PAYLOAD_BYTES:
        return jsonify({"error": "Payload too large"}), 413

    # --- Stream lookup and validation ---
    stream = db.session.get(Stream, stream_id)

    if not stream or not stream.is_active or stream.stream_mode != "inbound":
        logger.debug(
            f"Inbound request rejected for stream {stream_id}: "
            f"{'not found' if not stream else 'inactive' if not stream.is_active else 'wrong mode'}"
        )
        return jsonify(_NOT_FOUND_RESPONSE[0]), _NOT_FOUND_RESPONSE[1]

    # --- IP allowlist ---
    if not _check_ip_allowlist(stream.inbound_ip_allowlist, request.remote_addr):
        logger.warning(
            f"Inbound request blocked by IP allowlist for stream {stream_id} "
            f"from {request.remote_addr}"
        )
        return jsonify(_NOT_FOUND_RESPONSE[0]), _NOT_FOUND_RESPONSE[1]

    # --- Plugin instantiation ---
    plugin_manager = get_plugin_manager()
    plugin_class = plugin_manager.get_plugin_class(stream.plugin_type)
    if not plugin_class:
        logger.error(f"Plugin type '{stream.plugin_type}' not found for stream {stream_id}")
        return jsonify(_NOT_FOUND_RESPONSE[0]), _NOT_FOUND_RESPONSE[1]

    plugin = plugin_class(stream.get_plugin_config())
    plugin.stream = stream

    # --- Authentication ---
    headers = dict(request.headers)
    is_valid, auth_error = plugin.validate_inbound_request(headers)
    if not is_valid:
        masked_key = _mask_api_key(headers.get("Authorization", "")[7:] if "Bearer" in headers.get("Authorization", "") else "")
        logger.warning(
            f"Inbound auth failed for stream {stream_id} "
            f"from {request.remote_addr} (key: {masked_key})"
        )
        return jsonify(_NOT_FOUND_RESPONSE[0]), _NOT_FOUND_RESPONSE[1]

    # --- Content-Type validation ---
    content_type = request.content_type or ""
    # Strip parameters (e.g., "application/json; charset=utf-8" → "application/json")
    base_content_type = content_type.split(";")[0].strip().lower()
    accepted = [ct.lower() for ct in plugin.get_accepted_content_types()]
    if base_content_type not in accepted:
        return jsonify({
            "error": f"Unsupported Content-Type: {content_type}. "
                     f"Accepted: {', '.join(accepted)}"
        }), 415

    # --- Payload transformation ---
    try:
        locations = plugin.transform_payload(raw_body, content_type, headers)
    except (ValueError, Exception) as e:
        logger.warning(
            f"Inbound transform failed for stream {stream_id}: {e}"
        )
        return jsonify({"error": f"Payload transform failed: {e}"}), 400

    if not locations:
        return jsonify({"error": "No locations extracted from payload"}), 400

    # --- Location count limit ---
    if len(locations) > MAX_LOCATIONS_PER_REQUEST:
        return jsonify({
            "error": f"Too many locations: {len(locations)} "
                     f"(max {MAX_LOCATIONS_PER_REQUEST})"
        }), 400

    # --- Coordinate validation ---
    coord_error = _validate_coordinates(locations)
    if coord_error:
        return jsonify({"error": coord_error}), 400

    # --- Process and distribute ---
    result = _process_inbound_async(locations, stream)

    if not result.get("success"):
        error_msg = result.get("error", "Internal processing error")
        logger.error(f"Inbound processing failed for stream {stream_id}: {error_msg}")
        stream.update_stats(error=error_msg)
        db.session.commit()
        return jsonify({"error": error_msg}), 500

    # --- Update stream stats ---
    events_created = result.get("events_created", 0)
    stream.update_stats(messages_sent=events_created)
    db.session.commit()

    logger.info(
        f"Inbound: stream {stream_id} received {len(locations)} locations, "
        f"created {events_created} CoT events from {request.remote_addr}"
    )

    return jsonify({
        "status": "accepted",
        "locations_received": len(locations),
        "events_created": events_created,
        "servers": result.get("servers", {}),
    }), 202
