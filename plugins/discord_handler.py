# ABOUTME: DiscordHandler plugin for receiving CoT messages from TAK
# ABOUTME: Implements BaseOutputPlugin to handle chat, emergency, and
# ABOUTME: custom CoT message types

from plugins.base_plugin import (
    BaseOutputPlugin,
    PluginConfigField,
    PluginCustomComponent,
)
from defusedxml import ElementTree as DefusedET
import aiohttp
import certifi
import ssl
import time
from typing import Any, Dict
import re
import mgrs
from datetime import datetime, timezone


# Lazy import to avoid circular dependency
_logger_instance = None


def get_logger():
    """Get module logger, initializing lazily to avoid circular imports"""
    global _logger_instance
    if _logger_instance is None:
        from services.logging_service import get_module_logger

        _logger_instance = get_module_logger(__name__)
    return _logger_instance


# For backwards compatibility - provide logger as module attribute
class _LoggerProxy:
    """Proxy that forwards all attribute access to the lazy logger"""

    def __getattr__(self, name):
        return getattr(get_logger(), name)


logger = _LoggerProxy()


class DiscordHandler(BaseOutputPlugin):
    """Handle CoT messages and send to Discord"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Deduplication: track recently seen messages to avoid duplicates
        self._seen_messages: Dict[str, float] = {}
        self._dedup_ttl_seconds: float = 5.0

    @property
    def plugin_name(self) -> str:
        return "discord_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Discord CoT Handler",
            "description": "Receive CoT messages from TAK and post to Discord",
            "icon": "fa-discord",
            "category": "notification",
            "help_sections": [
                {
                    "title": "Template Variables",
                    "content": [
                        (
                            "Basic: {type}, {uid}, {time}, {stale}, "
                            "{callsign}, {remarks}"
                        ),
                        "Location: {lat}, {lon}, {hae}, {mgrs}",
                        "Group: {group_name}, {group_role}",
                        (
                            "Device: {device}, {platform}, {os}, "
                            "{version}, {battery}"
                        ),
                        "Track: {speed}, {course}, {xmpp_username}",
                    ],
                },
                {
                    "title": "Common CoT Types & Example Templates",
                    "content": [
                        'Chat (b-t-f): "[CHAT] {callsign}: {remarks}"',
                        (
                            'Emergency (b-a-o-tbl): '
                            '"[EMERGENCY] {callsign} at {mgrs}"'
                        ),
                        (
                            'Geofence Alert (b-a-o-can): '
                            '"[ALERT] {callsign} {remarks} at {lat},{lon}"'
                        ),
                        (
                            'Friendly Position (a-f-G-E-V): '
                            '"[{group_name}] {callsign} ({group_role}) - '
                            'Battery: {battery}%"'
                        ),
                        'Hostile (a-h-*): "[HOSTILE] {type} at {mgrs}"',
                        (
                            'Ring of Fire (b-a-o-opn): '
                            '"[ROF] {callsign}: {remarks}"'
                        ),
                    ],
                },
                {
                    "title": "UID Filtering",
                    "content": [
                        (
                            "Global UID Filter: Applied before message "
                            "rules (legacy, optional)"
                        ),
                        (
                            "Per-Rule UID Filter: Each rule can have its "
                            "own UID filter (recommended)"
                        ),
                        'Example: "^ANDROID-.*" matches only Android devices',
                        (
                            'Example: "^.*-Team[1-3]$" matches Team 1-3 '
                            'devices'
                        ),
                        (
                            "Rules are evaluated in order; first matching "
                            "rule wins"
                        ),
                    ],
                },
                {
                    "title": "Important Notes",
                    "content": [
                        (
                            "At least one message rule is required for "
                            "messages to be sent"
                        ),
                        (
                            "Use wildcards (*) in CoT type patterns for "
                            "broader matching"
                        ),
                        (
                            "Messages are deduplicated within 5 seconds to "
                            "avoid duplicates"
                        ),
                        (
                            "Discord embeds support rich formatting with "
                            "colors and fields"
                        ),
                    ],
                },
            ],
            "config_fields": [
                PluginConfigField(
                    name="webhook_url",
                    label="Discord Webhook URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    help_text="Webhook URL from Discord channel settings",
                ),
                PluginConfigField(
                    name="webhook_username",
                    label="Bot Username",
                    field_type="text",
                    placeholder="TrakBridge",
                    help_text=(
                        "Custom username to display (overrides webhook "
                        "default)"
                    ),
                ),
                PluginConfigField(
                    name="webhook_avatar_url",
                    label="Bot Avatar URL",
                    field_type="url",
                    placeholder="https://example.com/avatar.png",
                    help_text=(
                        "Custom avatar image URL (overrides webhook default)"
                    ),
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="Global UID Filter (regex)",
                    field_type="text",
                    placeholder="^ANDROID-.*",
                    help_text=(
                        "Global pre-filter applied before message rules "
                        "(optional). See Help section for details and "
                        "examples."
                    ),
                ),
                PluginConfigField(
                    name="use_embeds",
                    label="Message Format",
                    field_type="select",
                    options=[
                        {"value": "false", "label": "Simple Text"},
                        {"value": "true", "label": "Rich Embeds"},
                    ],
                    default_value="false",
                    help_text=(
                        "Use Discord embeds for rich formatting (title, "
                        "color, fields)"
                    ),
                ),
            ],
            "custom_components": [
                PluginCustomComponent(
                    type="message_rules",
                    field_name="message_rules",
                    title="Message Rules",
                    icon="fa-filter",
                    help_text=(
                        "Define rules to filter and format CoT messages "
                        "before sending to Discord. Rules are evaluated in "
                        "order; first matching rule wins."
                    ),
                    config={
                        "template_variables": [
                            "{type}",
                            "{uid}",
                            "{time}",
                            "{stale}",
                            "{callsign}",
                            "{remarks}",
                            "{lat}",
                            "{lon}",
                            "{hae}",
                            "{mgrs}",
                            "{group_name}",
                            "{group_role}",
                            "{device}",
                            "{platform}",
                            "{os}",
                            "{version}",
                            "{battery}",
                            "{speed}",
                            "{course}",
                            "{xmpp_username}",
                        ],
                        "rule_fields": [
                            {
                                "name": "cot_type_pattern",
                                "label": "CoT Type Pattern",
                                "type": "text",
                                "required": True,
                                "placeholder": (
                                    "b-t-f or a-f-* (wildcards supported)"
                                ),
                                "help": (
                                    "Pattern to match CoT types (e.g., "
                                    "b-t-f for chat, a-f-* for all friendly)"
                                ),
                            },
                            {
                                "name": "uid_filter",
                                "label": "UID Filter (regex)",
                                "type": "text",
                                "required": False,
                                "placeholder": "^ANDROID-.*",
                                "help": (
                                    "Optional regex to filter by UID (e.g., "
                                    "^ANDROID-.* for Android devices)"
                                ),
                            },
                            {
                                "name": "format_template",
                                "label": "Format Template",
                                "type": "textarea",
                                "required": True,
                                "placeholder": (
                                    "[CHAT] {callsign}: {remarks}"
                                ),
                                "help": (
                                    "Message format using template variables "
                                    "above"
                                ),
                            },
                        ],
                    }
                ),
                PluginCustomComponent(
                    type="geofence",
                    field_name="global_geofence",
                    title="Geofence",
                    icon="fa-map-marked-alt",
                    help_text=(
                        "Filter messages by geographic bounds. Only messages "
                        "within the defined area will be sent to Discord."
                    ),
                    config={
                        "default_center": [40.7, -74.0],
                        "default_zoom": 10,
                        "enable_checkbox_label": "Enable Geofence Filtering",
                    },
                ),
            ],
        }

    async def handle_cot_message(
        self, cot_xml: bytes, tak_server_id: int
    ) -> None:
        """Parse CoT and send to Discord if it matches our filters"""

        logger.debug(
            f"DiscordHandler received CoT message from TAK server "
            f"{tak_server_id}, size: {len(cot_xml)} bytes"
        )
        logger.debug(f"CoT XML preview: {cot_xml}")

        try:
            # Parse XML securely
            root = DefusedET.fromstring(cot_xml)

            # Extract fields
            cot_type = root.get("type", "")
            uid = root.get("uid", "")

            logger.debug(f"Parsed CoT: type={cot_type}, uid={uid}")

            # Extract lat/lon for geofence filtering
            point = root.find("point")
            lat = ""
            lon = ""
            if point is not None:
                lat = point.get("lat", "")
                lon = point.get("lon", "")

            # Apply plugin's own filters and get template
            should_handle, template = self._should_handle(
                cot_type, uid, lat, lon
            )
            if not should_handle:
                logger.debug(
                    f"Filtered out: type={cot_type}, uid={uid} "
                    f"(does not match any rules)"
                )
                return

            logger.info(
                f"CoT passed filters, processing: type={cot_type}, uid={uid}"
            )

            # Deduplication: check if we've seen this UID+type combo recently
            # Don't include time in key since TAK server may update timestamp
            dedup_key = f"{uid}:{cot_type}"
            now = time.time()

            # Clean up old entries
            self._seen_messages = {
                k: v
                for k, v in self._seen_messages.items()
                if now - v < self._dedup_ttl_seconds
            }

            if dedup_key in self._seen_messages:
                time_since_last = now - self._seen_messages[dedup_key]
                logger.debug(
                    f"Duplicate message ignored: {dedup_key} "
                    f"(seen {time_since_last:.2f}s ago)"
                )
                return

            self._seen_messages[dedup_key] = now
            logger.debug(f"New message accepted: {dedup_key}")

            # Extract template variables
            variables = self._extract_template_variables(root)

            # Format message using template
            if template:
                msg = self._format_message(template, variables)
            else:
                # Fallback to default format if no template
                msg = f"[{cot_type}] {variables['callsign']}"

            logger.info(f"Sending formatted message to Discord: {msg}")
            await self._send_to_discord(msg, variables)

        except Exception as e:
            logger.error(f"DiscordHandler failed to process CoT: {e}")

    def _matches_cot_pattern(self, cot_type: str, pattern: str) -> bool:
        """Check if CoT type matches pattern (supports wildcards)"""
        if pattern.endswith("*"):
            # Wildcard match
            return cot_type.startswith(pattern[:-1])
        else:
            # Exact match
            return cot_type == pattern

    def _extract_template_variables(self, root) -> Dict[str, str]:
        """Extract template variables from CoT XML"""
        variables = {
            "type": root.get("type", ""),
            "uid": root.get("uid", ""),
            "time": root.get("time", ""),
            "stale": root.get("stale", ""),
            "callsign": "Unknown",
            "lat": "",
            "lon": "",
            "hae": "",
            "mgrs": "",
            "remarks": "",
            "group_name": "",
            "group_role": "",
            "battery": "",
            "device": "",
            "platform": "",
            "os": "",
            "version": "",
            "speed": "",
            "course": "",
            "xmpp_username": "",
        }

        # Extract point data
        point = root.find("point")
        if point is not None:
            variables["lat"] = point.get("lat", "")
            variables["lon"] = point.get("lon", "")
            variables["hae"] = point.get("hae", "")
            logger.debug(
                f"Extracted point data: lat={variables['lat']}, "
                f"lon={variables['lon']}, hae={variables['hae']}"
            )

            # Convert to MGRS if we have valid coordinates
            if variables["lat"] and variables["lon"]:
                try:
                    lat_float = float(variables["lat"])
                    lon_float = float(variables["lon"])
                    m = mgrs.MGRS()
                    variables["mgrs"] = m.toMGRS(lat_float, lon_float)
                    logger.debug(f"Converted to MGRS: {variables['mgrs']}")
                except (ValueError, Exception) as e:
                    logger.warning(
                        f"Failed to convert lat/lon to MGRS: {e}"
                    )
                    variables["mgrs"] = ""
            else:
                variables["mgrs"] = ""
        else:
            logger.debug("No point element found in CoT XML")
            variables["mgrs"] = ""

        # Extract detail data
        detail = root.find("detail")
        if detail is not None:
            contact = detail.find("contact")
            if contact is not None:
                variables["callsign"] = contact.get("callsign", "Unknown")
                variables["xmpp_username"] = contact.get("xmppUsername", "")

            remarks = detail.find("remarks")
            if remarks is not None and remarks.text:
                variables["remarks"] = remarks.text

            # Extract group data from __group element
            group = detail.find("__group")
            if group is not None:
                variables["group_name"] = group.get("name", "")
                variables["group_role"] = group.get("role", "")

            # Extract battery from status element
            status = detail.find("status")
            if status is not None:
                variables["battery"] = status.get("battery", "")

            # Extract device info from takv element
            takv = detail.find("takv")
            if takv is not None:
                variables["device"] = takv.get("device", "")
                variables["platform"] = takv.get("platform", "")
                variables["os"] = takv.get("os", "")
                variables["version"] = takv.get("version", "")

            # Extract track data from track element
            track = detail.find("track")
            if track is not None:
                variables["speed"] = track.get("speed", "")
                variables["course"] = track.get("course", "")

        return variables

    def _format_message(self, template: str, variables: Dict[str, str]) -> str:
        """Format message using template and variables"""
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Template variable missing: {e}")
            return f"{template} [ERROR: missing variable {e}]"
        except Exception as e:
            logger.error(f"Template formatting error: {e}")
            return f"{template} [ERROR: {e}]"

    def _is_within_geofence(
        self, lat: str, lon: str, bounds: dict
    ) -> bool:
        """Check if coordinates are within bounding box"""
        try:
            lat_float = float(lat)
            lon_float = float(lon)

            north = float(bounds.get("north", 90))
            south = float(bounds.get("south", -90))
            east = float(bounds.get("east", 180))
            west = float(bounds.get("west", -180))

            # Simple bounding box check
            lat_ok = south <= lat_float <= north
            lon_ok = west <= lon_float <= east

            logger.debug(
                f"Geofence check: lat={lat_float} in [{south}, {north}]? "
                f"{lat_ok}, lon={lon_float} in [{west}, {east}]? {lon_ok}"
            )

            return lat_ok and lon_ok

        except (ValueError, TypeError) as e:
            logger.warning(
                f"Invalid coordinates or bounds for geofence check: {e}"
            )
            return True  # Fail open - don't filter if we can't validate

    def _should_handle(
        self, cot_type: str, uid: str, lat: str = "", lon: str = ""
    ) -> tuple[bool, str]:
        """Filtering logic - returns (should_handle, template)"""
        config = self.get_decrypted_config()

        logger.debug(
            f"_should_handle called with cot_type={cot_type}, uid={uid}, "
            f"lat={lat}, lon={lon}"
        )

        # Global UID filter (optional pre-filter, for backwards compatibility)
        global_uid_filter = config.get("uid_filter", "")
        if global_uid_filter:
            logger.debug(
                f"Global UID filter configured: '{global_uid_filter}'"
            )
            try:
                if not re.match(global_uid_filter, uid):
                    logger.debug(
                        f"UID '{uid}' does not match global filter "
                        f"'{global_uid_filter}'"
                    )
                    return (False, "")
                logger.debug(
                    f"UID '{uid}' matches global filter "
                    f"'{global_uid_filter}'"
                )
            except re.error:
                logger.error(
                    f"Invalid global UID filter regex: {global_uid_filter}"
                )
                return (False, "")

        # Check geofence before matching rules
        global_geofence_enabled = (
            config.get("global_geofence_enabled", "false") == "true"
        )
        global_geofence_bounds = config.get("global_geofence_bounds", {})

        if global_geofence_enabled and global_geofence_bounds and lat and lon:
            if not self._is_within_geofence(lat, lon, global_geofence_bounds):
                logger.debug(
                    f"Filtered out by geofence: lat={lat}, lon={lon}"
                )
                return (False, "")
            logger.debug("Passed geofence check")

        # Check message rules
        message_rules = config.get("message_rules", [])
        logger.debug(f"Message rules configured: {message_rules}")
        if not message_rules:
            # No rules configured - don't handle any messages
            logger.debug("No message rules configured - rejecting")
            return (False, "")

        # Find first matching rule
        for rule in message_rules:
            logger.debug(f"Checking rule: {rule}")
            if not rule.get("enabled", True):
                logger.debug("Rule is disabled, skipping")
                continue

            # Check rule-level UID filter first (if specified)
            rule_uid_filter = rule.get("uid_filter", "")
            if rule_uid_filter:
                try:
                    if not re.match(rule_uid_filter, uid):
                        logger.debug(
                            f"UID '{uid}' does not match rule filter "
                            f"'{rule_uid_filter}'"
                        )
                        continue  # Try next rule
                    logger.debug(
                        f"UID '{uid}' matches rule filter "
                        f"'{rule_uid_filter}'"
                    )
                except re.error:
                    logger.error(
                        f"Invalid rule UID filter regex: {rule_uid_filter}"
                    )
                    continue  # Try next rule

            pattern = rule.get("cot_type_pattern", "")
            logger.debug(
                f"Checking pattern '{pattern}' against cot_type '{cot_type}'"
            )
            if pattern and self._matches_cot_pattern(cot_type, pattern):
                template = rule.get("format_template", "")
                logger.debug(f"Pattern matched! Using template: {template}")
                return (True, template)

        # No matching rule
        return (False, "")

    def _get_embed_color_for_cot_type(self, cot_type: str) -> int:
        """Map CoT type to Discord embed color (decimal format)"""
        # Emergency/Alert types → RED (15548997)
        if cot_type.startswith("b-a-"):
            return 15548997

        # Friendly positions → GREEN (5763719)
        if cot_type.startswith("a-f-"):
            return 5763719

        # Hostile → RED (15548997)
        if cot_type.startswith("a-h-"):
            return 15548997

        # Neutral → YELLOW (16705372)
        if cot_type.startswith("a-n-"):
            return 16705372

        # Unknown → GREY (10070709)
        if cot_type.startswith("a-u-"):
            return 10070709

        # Chat → BLURPLE (5793266)
        if cot_type.startswith("b-t-f"):
            return 5793266

        # Default → WHITE (16777215)
        return 16777215

    def _get_embed_title(
        self, cot_type: str, variables: Dict[str, str]
    ) -> str:
        """Generate contextual title based on CoT type"""
        if cot_type.startswith("b-a-"):
            return "🚨 Emergency Alert"
        if cot_type.startswith("b-t-f"):
            return "💬 Chat Message"
        if cot_type.startswith("a-f-"):
            return "🟢 Friendly Position"
        if cot_type.startswith("a-h-"):
            return "🔴 Hostile Contact"
        return "📡 TAK Update"

    def _build_rich_embed(
        self, cot_type: str, variables: Dict[str, str]
    ) -> dict:
        """Build Discord embed with structured fields"""
        fields = []

        # Add location field (MGRS, inline)
        if variables.get("mgrs"):
            fields.append({
                "name": "📍 Location",
                "value": variables["mgrs"],
                "inline": True
            })

        # Add battery field (percentage, inline)
        if variables.get("battery"):
            fields.append({
                "name": "🔋 Battery",
                "value": f"{variables['battery']}%",
                "inline": True
            })

        # Add group field (name + role, inline)
        if variables.get("group_name"):
            group_text = variables["group_name"]
            if variables.get("group_role"):
                group_text += f" ({variables['group_role']})"
            fields.append({
                "name": "👥 Group",
                "value": group_text,
                "inline": True
            })

        # Add remarks field (non-inline for long text)
        if variables.get("remarks"):
            fields.append({
                "name": "💬 Message",
                "value": variables["remarks"],
                "inline": False
            })

        # Add device info if available
        if variables.get("device"):
            device_text = variables["device"]
            if variables.get("platform"):
                device_text += f" ({variables['platform']})"
            fields.append({
                "name": "📱 Device",
                "value": device_text,
                "inline": True
            })

        return {
            "title": self._get_embed_title(cot_type, variables),
            "description": f"**{variables['callsign']}**",
            "color": self._get_embed_color_for_cot_type(cot_type),
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def _send_to_discord(
        self, text: str, variables: Dict[str, str] = None
    ):
        """Send message to Discord webhook"""
        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            return

        use_embeds = config.get("use_embeds", "false") == "true"

        # Build payload based on embed mode
        if use_embeds and variables:
            # Rich embed mode
            embed = self._build_rich_embed(
                variables.get("type", ""), variables
            )
            payload = {
                "embeds": [embed]
            }
        else:
            # Simple text mode
            content = text[:2000]
            payload = {
                "content": content,
            }

        # Add optional username override
        webhook_username = config.get("webhook_username")
        if webhook_username:
            payload["username"] = webhook_username

        # Add optional avatar URL override
        webhook_avatar_url = config.get("webhook_avatar_url")
        if webhook_avatar_url:
            payload["avatar_url"] = webhook_avatar_url

        # Create SSL context with certifi CA bundle
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url, json=payload, ssl=ssl_context
                ) as resp:
                    if resp.status != 204:
                        logger.error(
                            f"Discord webhook failed: {resp.status}"
                        )
        except ssl.SSLError as ssl_err:
            # T4.3 — never retry a webhook post with certificate
            # validation disabled. The webhook URL is itself the
            # bearer credential; re-sending it over an unverified
            # channel exposes it to any MITM presenting a bad cert.
            logger.error(
                f"SSL verification failed sending to Discord; "
                f"refusing to retry without verification: {ssl_err}"
            )
        except Exception as e:
            logger.error(f"Failed to send to Discord: {e}")

    async def test_connection(self) -> Dict[str, Any]:
        """Test Discord webhook connection"""
        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            return {
                "success": False,
                "error": "Missing webhook URL",
                "message": "Please configure a Discord webhook URL",
            }

        try:
            # Send test message to Discord
            test_payload = {
                "content": (
                    "🔧 TrakBridge Connection Test\n"
                    "Your Discord handler is configured correctly!"
                ),
            }

            # Add optional username override
            webhook_username = config.get("webhook_username")
            if webhook_username:
                test_payload["username"] = webhook_username

            # Add optional avatar URL override
            webhook_avatar_url = config.get("webhook_avatar_url")
            if webhook_avatar_url:
                test_payload["avatar_url"] = webhook_avatar_url

            # Create SSL context with certifi CA bundle
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook_url,
                        json=test_payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                        ssl=ssl_context,
                    ) as resp:
                        if resp.status == 204:
                            return {
                                "success": True,
                                "message": (
                                    "Successfully sent test message to "
                                    "Discord"
                                ),
                            }
                        else:
                            resp_text = await resp.text()
                            return {
                                "success": False,
                                "error": f"HTTP {resp.status}",
                                "message": (
                                    f"Discord webhook returned error: "
                                    f"{resp_text}"
                                ),
                            }
            except ssl.SSLError as ssl_err:
                # T4.3 — do not retry the test with certificate
                # validation disabled. Report the SSL failure as the
                # test result so the operator sees the real issue.
                logger.error(
                    f"SSL verification failed testing Discord "
                    f"connection; refusing to retry without "
                    f"verification: {ssl_err}"
                )
                return {
                    "success": False,
                    "error": "SSL verification failed",
                    "message": (
                        f"Certificate validation failed reaching "
                        f"Discord: {ssl_err}"
                    ),
                }

        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": "Connection failed",
                "message": f"Failed to connect to Discord: {str(e)}",
            }
        except Exception as e:
            logger.error(
                f"DiscordHandler connection test failed: {e}", exc_info=True
            )
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed",
            }
