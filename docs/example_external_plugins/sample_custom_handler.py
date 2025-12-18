# ABOUTME: Sample external handler plugin demonstrating CoT message processing and integration patterns
# ABOUTME: Shows best practices for filtering, parsing, formatting, and sending alerts to external systems

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
from typing import Any, Dict, List, Optional
import asyncio
import time
import re


# Lazy import to avoid circular dependency
_logger_instance = None


def get_logger():
    """Get the module logger, initializing lazily to avoid circular imports"""
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


class SampleCustomHandler(BaseOutputPlugin):
    """
    Sample custom handler plugin demonstrating CoT message processing.

    This plugin shows:
    - Configuration management with sensitive fields
    - CoT XML parsing with defusedxml
    - Multi-level filtering (type, UID, geographic, time-based)
    - Template-based message formatting
    - Connection lifecycle management
    - Deduplication to prevent duplicate messages
    - Error handling and timeout protection
    - Batch processing for efficiency

    Use this as a template for building your own handler plugins.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        # Connection state tracking
        self._connected: bool = False
        self._connection_lock = asyncio.Lock()

        # Deduplication: track recently seen messages to avoid duplicates from TAK server
        # Key format: "{uid}:{cot_type}" (don't include timestamp as TAK may update it)
        self._seen_messages: Dict[str, float] = {}
        self._dedup_ttl_seconds: float = 5.0  # Ignore duplicates within 5 seconds

        # Batch processing for efficiency (optional optimization)
        self._message_queue: List[Dict[str, Any]] = []
        self._batch_task: Optional[asyncio.Task] = None
        self._batch_size: int = 10  # Send when we have 10 messages
        self._batch_interval: float = 5.0  # Or after 5 seconds

        # Performance metrics (optional monitoring)
        self._metrics = {
            'messages_received': 0,
            'messages_processed': 0,
            'messages_filtered': 0,
            'errors': 0,
        }

    @property
    def plugin_name(self) -> str:
        """
        Unique identifier for this plugin.
        Must match the module name for external plugins.
        """
        return "sample_custom_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        """
        Plugin metadata for UI generation and configuration.

        This defines:
        - Display information (name, description, icon)
        - Category (output, bidirectional, etc.)
        - Configuration fields with types and validation
        - Help documentation shown in UI
        """
        return {
            "display_name": "Sample Custom Handler",
            "description": "Example handler showing best practices for CoT message processing",
            "icon": "fa-bell",  # FontAwesome icon class
            "category": "output",  # output, bidirectional, or input
            "help_sections": [
                {
                    "title": "What This Handler Does",
                    "content": [
                        "Receives CoT messages from TAK servers",
                        "Filters messages by type, UID pattern, and location",
                        "Formats messages using customizable templates",
                        "Sends alerts to external webhook endpoint",
                        "Demonstrates deduplication and batch processing",
                    ],
                },
                {
                    "title": "Template Variables Available",
                    "content": [
                        "Basic: {type}, {uid}, {time}, {stale}, {callsign}, {remarks}",
                        "Location: {lat}, {lon}, {hae}",
                        "Group: {group_name}, {group_role}",
                        "Device: {battery}, {platform}, {device}",
                        "Example: \"[ALERT] {callsign} at {lat},{lon} - {remarks}\"",
                    ],
                },
                {
                    "title": "CoT Type Filtering Examples",
                    "content": [
                        "Chat messages: b-t-f",
                        "All emergencies: b-a-* (wildcard)",
                        "Friendly positions: a-f-*",
                        "Multiple types: b-t-f,b-a-*,a-f-* (comma-separated)",
                    ],
                },
                {
                    "title": "UID Filter Pattern Examples",
                    "content": [
                        "Android devices only: ^ANDROID-.*",
                        "Specific team: ^TEAM1-.*",
                        "Multiple teams: ^(TEAM1|TEAM2)-",
                        "Leaders only: .*-LEADER$",
                    ],
                },
            ],
            "config_fields": [
                # Required fields
                PluginConfigField(
                    name="webhook_url",
                    label="Webhook URL",
                    field_type="url",
                    required=True,
                    placeholder="https://example.com/webhook",
                    help_text="Endpoint to send formatted alerts to",
                ),
                PluginConfigField(
                    name="api_key",
                    label="API Key",
                    field_type="password",
                    required=True,
                    sensitive=True,  # Automatically encrypted in database
                    help_text="Authentication key for webhook endpoint",
                ),

                # Filtering configuration
                PluginConfigField(
                    name="message_types",
                    label="CoT Types to Handle",
                    field_type="text",
                    placeholder="b-t-f,b-a-*",
                    help_text="Comma-separated CoT types (use * for wildcard)",
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="UID Filter (regex)",
                    field_type="text",
                    placeholder="^ANDROID-.*",
                    help_text="Regular expression to filter by UID (optional)",
                ),

                # Message formatting
                PluginConfigField(
                    name="message_template",
                    label="Message Template",
                    field_type="text",
                    default_value="[{type}] {callsign}: {remarks}",
                    help_text="Template for formatting messages (see help for variables)",
                ),

                # Performance tuning (optional)
                PluginConfigField(
                    name="batch_enabled",
                    label="Enable Batch Processing",
                    field_type="select",
                    default_value="false",
                    options=[
                        {"value": "true", "label": "Yes"},
                        {"value": "false", "label": "No"},
                    ],
                    help_text="Batch multiple messages for efficiency",
                ),
                PluginConfigField(
                    name="timeout_seconds",
                    label="Request Timeout (seconds)",
                    field_type="number",
                    default_value=10,
                    min_value=1,
                    max_value=30,
                    help_text="Timeout for webhook requests",
                ),
            ],
        }

    async def start(self):
        """
        Initialize handler when stream starts.

        Called by framework when stream is enabled. Use this for:
        - Establishing persistent connections
        - Authentication/handshake
        - Starting background tasks
        - Initial setup
        """
        logger.info(f"{self.plugin_name} starting up...")

        # For this example, we don't have a persistent connection to maintain
        # But if you were connecting to IRC, MQTT, WebSocket, etc., you would
        # establish the connection here

        # Example of what you might do for persistent connections:
        # success = await self._ensure_connected()
        # if success:
        #     logger.info(f"{self.plugin_name} started successfully")
        # else:
        #     logger.error(f"{self.plugin_name} failed to start")

        logger.info(f"{self.plugin_name} started successfully")

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """
        Handle received CoT message from TAK server.

        This is the core method called for every CoT message received.

        CRITICAL: NEVER raise exceptions from this method!
        - The RX worker will timeout after 10 seconds
        - Raising exceptions can crash the RX worker
        - Always catch, log, and return gracefully

        Args:
            cot_xml: Raw CoT XML bytes from TAK server
            tak_server_id: ID of TAK server that sent this message
        """
        self._metrics['messages_received'] += 1

        try:
            # Step 1: Parse XML safely using defusedxml (NEVER use standard xml.etree)
            root = DefusedET.fromstring(cot_xml)

            # Step 2: Extract basic CoT fields
            cot_type = root.get("type", "")
            uid = root.get("uid", "")

            logger.debug(f"Received CoT: type={cot_type}, uid={uid}")

            # Step 3: Apply filters
            if not self._should_handle(cot_type, uid, root):
                self._metrics['messages_filtered'] += 1
                logger.debug(f"Filtered out: type={cot_type}, uid={uid}")
                return

            # Step 4: Check for duplicates
            if self._is_duplicate(uid, cot_type):
                logger.debug(f"Duplicate message ignored: {uid}:{cot_type}")
                return

            # Step 5: Extract template variables from CoT
            variables = self._extract_template_variables(root)

            # Step 6: Format message using configured template
            config = self.get_decrypted_config()
            template = config.get("message_template", "[{type}] {callsign}")
            formatted_message = self._format_message(template, variables)

            # Step 7: Send to external system (or batch if enabled)
            if config.get("batch_enabled", "false").lower() == "true":
                await self._enqueue_for_batch(formatted_message, variables)
            else:
                await self._send_to_webhook(formatted_message, variables)

            self._metrics['messages_processed'] += 1
            logger.info(f"Processed CoT message: {formatted_message}")

        except DefusedET.ParseError as e:
            # XML parsing failed - log and continue (don't crash!)
            self._metrics['errors'] += 1
            logger.error(f"Failed to parse CoT XML: {e}")
            return

        except Exception as e:
            # Unexpected error - log with stack trace and continue
            self._metrics['errors'] += 1
            logger.error(f"Handler failed to process CoT message: {e}", exc_info=True)
            return

    def _should_handle(self, cot_type: str, uid: str, root) -> bool:
        """
        Multi-level filtering to determine if we should process this message.

        Applies filters in order:
        1. CoT type matching (with wildcard support)
        2. UID regex filtering
        3. Geographic filtering (optional)
        4. Time-based filtering (optional)

        Args:
            cot_type: CoT event type (e.g., "b-t-f", "a-f-G-E-V-C")
            uid: Unique identifier of the CoT sender
            root: Parsed XML root element

        Returns:
            True if message should be processed, False to filter out
        """
        config = self.get_decrypted_config()

        # Filter 1: CoT type filtering
        type_filter = config.get("message_types", "")
        if type_filter:
            types = [t.strip() for t in type_filter.split(",")]
            matches = False

            for t in types:
                if t.endswith("*"):
                    # Wildcard match: "b-a-*" matches "b-a-o-tfc"
                    if cot_type.startswith(t[:-1]):
                        matches = True
                        break
                elif cot_type == t:
                    # Exact match
                    matches = True
                    break

            if not matches:
                logger.debug(f"Type filter rejected: {cot_type} not in {types}")
                return False

        # Filter 2: UID regex filtering
        uid_pattern = config.get("uid_filter", "")
        if uid_pattern:
            try:
                if not re.match(uid_pattern, uid):
                    logger.debug(f"UID filter rejected: {uid} doesn't match {uid_pattern}")
                    return False
            except re.error as e:
                logger.error(f"Invalid UID regex pattern: {uid_pattern}: {e}")
                # Fail open - accept message if regex is invalid
                pass

        # Filter 3: Geographic filtering (optional - uncomment to enable)
        # point = root.find("point")
        # if point is not None:
        #     lat = float(point.get("lat"))
        #     lon = float(point.get("lon"))
        #
        #     # Example: only accept messages within bounding box
        #     min_lat = float(config.get("min_lat", -90))
        #     max_lat = float(config.get("max_lat", 90))
        #     min_lon = float(config.get("min_lon", -180))
        #     max_lon = float(config.get("max_lon", 180))
        #
        #     if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        #         logger.debug(f"Geographic filter rejected: {lat},{lon}")
        #         return False

        # Filter 4: Time-based filtering (optional - uncomment to enable)
        # from datetime import datetime
        # current_hour = datetime.now().hour
        # start_hour = int(config.get("start_hour", 0))
        # end_hour = int(config.get("end_hour", 24))
        #
        # if not (start_hour <= current_hour < end_hour):
        #     logger.debug(f"Time filter rejected: hour={current_hour}")
        #     return False

        # All filters passed
        return True

    def _is_duplicate(self, uid: str, cot_type: str) -> bool:
        """
        Check if we've seen this message recently (deduplication).

        TAK servers may rebroadcast messages, so we track recent messages
        and ignore duplicates within the TTL window.

        Note: We use UID + type as the key, NOT timestamp, because TAK
        may update the timestamp on rebroadcast.

        Args:
            uid: Message UID
            cot_type: Message type

        Returns:
            True if duplicate, False if new message
        """
        dedup_key = f"{uid}:{cot_type}"
        now = time.time()

        # Clean up old entries to prevent memory leak
        self._seen_messages = {
            k: v
            for k, v in self._seen_messages.items()
            if now - v < self._dedup_ttl_seconds
        }

        # Check if we've seen this recently
        if dedup_key in self._seen_messages:
            time_since_last = now - self._seen_messages[dedup_key]
            logger.debug(f"Duplicate detected: {dedup_key} (seen {time_since_last:.2f}s ago)")
            return True

        # Mark as seen
        self._seen_messages[dedup_key] = now
        return False

    def _extract_template_variables(self, root) -> Dict[str, str]:
        """
        Extract all available template variables from CoT XML.

        These variables can be used in message templates configured by users.

        Args:
            root: Parsed XML root element

        Returns:
            Dictionary of template variable names to values
        """
        # Initialize all variables with defaults (prevents KeyError in templates)
        variables = {
            # Basic CoT fields
            "type": root.get("type", ""),
            "uid": root.get("uid", ""),
            "time": root.get("time", ""),
            "stale": root.get("stale", ""),
            "how": root.get("how", ""),

            # Location fields
            "callsign": "Unknown",
            "lat": "",
            "lon": "",
            "hae": "",
            "ce": "",
            "le": "",

            # Detail fields
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
        }

        # Extract point data (coordinates)
        point = root.find("point")
        if point is not None:
            variables["lat"] = point.get("lat", "")
            variables["lon"] = point.get("lon", "")
            variables["hae"] = point.get("hae", "")  # Height above ellipsoid
            variables["ce"] = point.get("ce", "")    # Circular error
            variables["le"] = point.get("le", "")    # Linear error

        # Extract detail elements
        detail = root.find("detail")
        if detail is not None:
            # Contact information (callsign, endpoint, etc.)
            contact = detail.find("contact")
            if contact is not None:
                variables["callsign"] = contact.get("callsign", "Unknown")

            # Remarks (chat messages, descriptions, etc.)
            remarks = detail.find("remarks")
            if remarks is not None and remarks.text:
                variables["remarks"] = remarks.text

            # Group data (__group element)
            group = detail.find("__group")
            if group is not None:
                variables["group_name"] = group.get("name", "")
                variables["group_role"] = group.get("role", "")

            # Battery status
            status = detail.find("status")
            if status is not None:
                variables["battery"] = status.get("battery", "")

            # Device information (ATAK version, platform, etc.)
            takv = detail.find("takv")
            if takv is not None:
                variables["device"] = takv.get("device", "")
                variables["platform"] = takv.get("platform", "")
                variables["os"] = takv.get("os", "")
                variables["version"] = takv.get("version", "")

            # Track data (speed, course/heading)
            track = detail.find("track")
            if track is not None:
                variables["speed"] = track.get("speed", "")
                variables["course"] = track.get("course", "")

        return variables

    def _format_message(self, template: str, variables: Dict[str, str]) -> str:
        """
        Format message using template and extracted variables.

        Uses Python string formatting with named placeholders.
        Example: "[{type}] {callsign}: {remarks}" -> "[b-t-f] Team1: Hello"

        Args:
            template: Message template with {variable} placeholders
            variables: Dictionary of variable values

        Returns:
            Formatted message string
        """
        try:
            return template.format(**variables)
        except KeyError as e:
            # Missing variable in template
            logger.warning(f"Template variable missing: {e}")
            return f"{template} [ERROR: missing variable {e}]"
        except Exception as e:
            # Other formatting error
            logger.error(f"Template formatting error: {e}")
            return f"{template} [ERROR: {e}]"

    async def _send_to_webhook(self, message: str, variables: Dict[str, str]):
        """
        Send formatted message to webhook endpoint.

        Demonstrates:
        - Timeout protection
        - Error handling
        - Authentication with API key
        - Retry logic (optional)

        Args:
            message: Formatted message string
            variables: Template variables (for additional context)
        """
        import aiohttp

        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")
        api_key = config.get("api_key")  # Already decrypted
        timeout_seconds = int(config.get("timeout_seconds", 10))

        if not webhook_url:
            logger.warning("No webhook URL configured, skipping send")
            return

        # Prepare payload (customize based on your webhook's expected format)
        payload = {
            "message": message,
            "cot_type": variables.get("type"),
            "uid": variables.get("uid"),
            "callsign": variables.get("callsign"),
            "timestamp": variables.get("time"),
            "location": {
                "lat": variables.get("lat"),
                "lon": variables.get("lon"),
            } if variables.get("lat") and variables.get("lon") else None,
        }

        headers = {
            "Content-Type": "application/json",
        }

        # Add authentication header if API key is configured
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            # Use asyncio.timeout for timeout protection
            async with asyncio.timeout(timeout_seconds):
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook_url,
                        json=payload,
                        headers=headers
                    ) as resp:
                        if resp.status == 200:
                            logger.info(f"Successfully sent to webhook: {message}")
                        else:
                            error_text = await resp.text()
                            logger.error(
                                f"Webhook returned {resp.status}: {error_text}"
                            )

        except asyncio.TimeoutError:
            logger.warning(f"Webhook request timed out after {timeout_seconds}s")
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error sending to webhook: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending to webhook: {e}")

    async def _enqueue_for_batch(self, message: str, variables: Dict[str, str]):
        """
        Add message to batch queue for efficient bulk sending.

        Instead of sending each message individually, we can batch them
        and send multiple at once to reduce API calls and improve performance.

        Args:
            message: Formatted message
            variables: Template variables
        """
        # Add to queue
        self._message_queue.append({
            "message": message,
            "variables": variables,
            "timestamp": time.time(),
        })

        config = self.get_decrypted_config()
        batch_size = int(config.get("batch_size", 10))

        # Send batch if we've hit the size limit
        if len(self._message_queue) >= batch_size:
            await self._send_batch()

        # Start background task to send batch after interval
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._batch_timer())

    async def _batch_timer(self):
        """Background task to send batches after configured interval."""
        await asyncio.sleep(self._batch_interval)

        if self._message_queue:
            await self._send_batch()

    async def _send_batch(self):
        """Send accumulated messages as a batch."""
        if not self._message_queue:
            return

        import aiohttp

        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")
        api_key = config.get("api_key")

        # Get current batch and clear queue
        batch = self._message_queue[:]
        self._message_queue.clear()

        # Prepare batch payload
        payload = {
            "messages": [item["message"] for item in batch],
            "count": len(batch),
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=30
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Sent batch of {len(batch)} messages")
                    else:
                        logger.error(f"Batch send failed: {resp.status}")

        except Exception as e:
            logger.error(f"Failed to send batch: {e}")

    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to webhook endpoint.

        Called by the "Test Connection" button in the UI.
        Should verify configuration and connectivity.

        Returns:
            Dictionary with:
            - success: bool
            - message: str (user-friendly message)
            - error: str (optional error details)
        """
        config = self.get_decrypted_config()

        # Validate required fields
        webhook_url = config.get("webhook_url")
        api_key = config.get("api_key")

        if not webhook_url:
            return {
                "success": False,
                "error": "Missing webhook URL",
                "message": "Please configure a webhook URL",
            }

        if not api_key:
            return {
                "success": False,
                "error": "Missing API key",
                "message": "Please configure an API key",
            }

        try:
            import aiohttp

            # Send test message
            test_payload = {
                "message": "[TrakBridge] Connection test successful",
                "test": True,
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=test_payload,
                    headers=headers,
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        return {
                            "success": True,
                            "message": f"Successfully connected to webhook at {webhook_url}",
                        }
                    else:
                        error_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}",
                            "message": f"Webhook returned error: {error_text[:100]}",
                        }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Timeout",
                "message": "Connection to webhook timed out",
            }
        except Exception as e:
            logger.error(f"Connection test failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed",
            }

    async def cleanup(self):
        """
        Cleanup resources when stream stops.

        Called by framework when stream is disabled or deleted.
        Use this to:
        - Close persistent connections
        - Cancel background tasks
        - Flush queues
        - Release resources
        """
        logger.info(f"{self.plugin_name} cleaning up...")

        # Cancel batch processing task
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        # Send any remaining batched messages
        if self._message_queue:
            logger.info(f"Flushing {len(self._message_queue)} remaining messages")
            await self._send_batch()

        # Log final metrics
        logger.info(
            f"{self.plugin_name} metrics: "
            f"received={self._metrics['messages_received']}, "
            f"processed={self._metrics['messages_processed']}, "
            f"filtered={self._metrics['messages_filtered']}, "
            f"errors={self._metrics['errors']}"
        )

        logger.info(f"{self.plugin_name} cleanup complete")
