# ABOUTME: IRCHandler plugin for receiving CoT messages from TAK and posting to IRC
# ABOUTME: Implements BaseOutputPlugin to handle chat messages and route them to IRC channels

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
import asyncio
from typing import Any, Dict, List, Optional
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


class IRCHandler(BaseOutputPlugin):
    """Handle CoT messages and send to IRC"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected: bool = False
        self._connection_lock = asyncio.Lock()

    @property
    def plugin_name(self) -> str:
        return "irc_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "IRC CoT Handler",
            "description": "Receive CoT messages from TAK and post to IRC",
            "icon": "fa-comments",
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="server",
                    label="IRC Server",
                    field_type="text",
                    required=True,
                    placeholder="irc.libera.chat",
                    help_text="IRC server hostname",
                ),
                PluginConfigField(
                    name="port",
                    label="IRC Port",
                    field_type="number",
                    required=True,
                    default_value=6667,
                    min_value=1,
                    max_value=65535,
                    help_text="IRC server port (6667 for plain, 6697 for SSL)",
                ),
                PluginConfigField(
                    name="use_ssl",
                    label="Use SSL/TLS",
                    field_type="select",
                    required=True,
                    default_value="false",
                    options=[
                        {"value": "true", "label": "Yes"},
                        {"value": "false", "label": "No"},
                    ],
                    help_text="Enable SSL/TLS encryption",
                ),
                PluginConfigField(
                    name="nickname",
                    label="Nickname",
                    field_type="text",
                    required=True,
                    placeholder="TrakBridge",
                    help_text="IRC bot nickname",
                ),
                PluginConfigField(
                    name="channel",
                    label="Channel",
                    field_type="text",
                    required=True,
                    placeholder="#tak-alerts",
                    help_text="IRC channel to join (include #)",
                ),
                PluginConfigField(
                    name="password",
                    label="Server Password (optional)",
                    field_type="password",
                    required=False,
                    sensitive=True,
                    help_text="IRC server password (if required)",
                ),
                PluginConfigField(
                    name="message_types",
                    label="Message Types to Handle",
                    field_type="text",
                    placeholder="b-t-f,b-a-*",
                    help_text="Comma-separated CoT types (e.g., b-t-f for chat)",
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="UID Filter (regex)",
                    field_type="text",
                    placeholder="^ANDROID-.*",
                    help_text="Only handle messages from matching UIDs (optional)",
                ),
            ],
        }

    async def _ensure_connected(self) -> bool:
        """Ensure IRC connection is established"""
        async with self._connection_lock:
            if self._connected and self._writer and not self._writer.is_closing():
                return True

            try:
                config = self.get_decrypted_config()
                server = config.get("server")
                port = int(config.get("port", 6667))
                use_ssl = config.get("use_ssl", "false").lower() == "true"
                nickname = config.get("nickname", "TrakBridge")
                password = config.get("password")
                channel = config.get("channel")

                if not server or not channel:
                    logger.error("IRC server or channel not configured")
                    return False

                # Connect to IRC server
                if use_ssl:
                    import ssl

                    ssl_context = ssl.create_default_context()
                    self._reader, self._writer = await asyncio.open_connection(
                        server, port, ssl=ssl_context
                    )
                else:
                    self._reader, self._writer = await asyncio.open_connection(
                        server, port
                    )

                logger.info(f"Connected to IRC server {server}:{port}")

                # Perform IRC handshake
                if password:
                    self._writer.write(f"PASS {password}\r\n".encode())
                    await self._writer.drain()

                self._writer.write(f"NICK {nickname}\r\n".encode())
                self._writer.write(f"USER {nickname} 0 * :TrakBridge Bot\r\n".encode())
                await self._writer.drain()

                # Wait for welcome message or error
                await asyncio.sleep(2)  # Give server time to respond

                # Join channel
                self._writer.write(f"JOIN {channel}\r\n".encode())
                await self._writer.drain()

                self._connected = True
                logger.info(f"Joined IRC channel {channel}")
                return True

            except Exception as e:
                logger.error(f"Failed to connect to IRC: {e}")
                self._connected = False
                if self._writer:
                    self._writer.close()
                    await self._writer.wait_closed()
                return False

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Parse CoT and send to IRC if it matches our filters"""

        config = self.get_decrypted_config()

        try:
            # Parse XML securely
            root = DefusedET.fromstring(cot_xml)

            # Extract fields
            cot_type = root.get("type", "")
            uid = root.get("uid", "")

            # Apply plugin's own filters
            if not self._should_handle(cot_type, uid):
                return

            # Extract message details
            detail = root.find("detail")
            callsign = "Unknown"
            message_text = ""

            if detail is not None:
                contact = detail.find("contact")
                if contact is not None:
                    callsign = contact.get("callsign", "Unknown")

                remarks = detail.find("remarks")
                if remarks is not None and remarks.text:
                    message_text = remarks.text

            # Determine message type and send to IRC
            if cot_type.startswith("b-t-f"):
                # Chat message
                await self._send_to_irc(f"[CHAT] {callsign}: {message_text}")
            elif cot_type.startswith("b-a"):
                # Emergency
                await self._send_to_irc(f"[EMERGENCY] {callsign}")
            elif cot_type.startswith("a-"):
                # Position update - skip to avoid spam
                pass
            else:
                # Unknown/custom type - log it
                await self._send_to_irc(f"[{cot_type}] {callsign}")

        except Exception as e:
            logger.error(f"IRCHandler failed to process CoT: {e}")

    def _should_handle(self, cot_type: str, uid: str) -> bool:
        """Plugin-specific filtering logic"""
        config = self.get_decrypted_config()

        # Filter by message type
        type_filter = config.get("message_types", "")
        if type_filter:
            types = [t.strip() for t in type_filter.split(",")]
            matches = False
            for t in types:
                if t.endswith("*"):
                    # Wildcard match
                    if cot_type.startswith(t[:-1]):
                        matches = True
                        break
                elif cot_type == t:
                    matches = True
                    break

            if not matches:
                return False

        # Filter by UID regex
        uid_filter = config.get("uid_filter", "")
        if uid_filter:
            try:
                if not re.match(uid_filter, uid):
                    return False
            except re.error:
                logger.error(f"Invalid UID filter regex: {uid_filter}")

        return True

    async def _send_to_irc(self, message: str):
        """Send message to IRC channel"""
        config = self.get_decrypted_config()
        channel = config.get("channel")

        if not channel:
            return

        try:
            # Ensure connection is established
            if not await self._ensure_connected():
                logger.error("Cannot send to IRC: not connected")
                return

            # Send message (split long messages if needed)
            max_length = 400  # IRC message length limit
            for i in range(0, len(message), max_length):
                chunk = message[i : i + max_length]
                self._writer.write(f"PRIVMSG {channel} :{chunk}\r\n".encode())
                await self._writer.drain()

        except Exception as e:
            logger.error(f"Failed to send to IRC: {e}")
            self._connected = False

    async def test_connection(self) -> Dict[str, Any]:
        """Test IRC connection"""
        config = self.get_decrypted_config()

        # Validate required fields
        required_fields = ["server", "port", "nickname", "channel"]
        for field in required_fields:
            if not config.get(field):
                return {
                    "success": False,
                    "error": f"Missing required field: {field}",
                    "message": f"Please configure {field}",
                }

        try:
            # Attempt to connect
            if await self._ensure_connected():
                # Send test message
                await self._send_to_irc("[TrakBridge] Connection test successful")

                return {
                    "success": True,
                    "message": f"Successfully connected to {config.get('server')} and joined {config.get('channel')}",
                }
            else:
                return {
                    "success": False,
                    "error": "Connection failed",
                    "message": "Failed to connect to IRC server or join channel",
                }

        except Exception as e:
            logger.error(f"IRCHandler connection test failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed",
            }

    async def cleanup(self):
        """Cleanup IRC connection"""
        if self._writer and not self._writer.is_closing():
            try:
                config = self.get_decrypted_config()
                channel = config.get("channel")
                if channel:
                    self._writer.write(f"PART {channel}\r\n".encode())
                    await self._writer.drain()
                self._writer.write(b"QUIT :TrakBridge shutting down\r\n")
                await self._writer.drain()
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.error(f"Error cleaning up IRC connection: {e}")
        self._connected = False
