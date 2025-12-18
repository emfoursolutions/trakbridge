# ABOUTME: SlackHandler plugin for receiving CoT messages from TAK and posting to Slack
# ABOUTME: Implements BaseOutputPlugin to handle chat, emergency, and custom CoT message types

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
import aiohttp
from typing import Any, Dict, List
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


class SlackHandler(BaseOutputPlugin):
    """Handle CoT messages and send to Slack"""

    @property
    def plugin_name(self) -> str:
        return "slack_handler"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "Slack CoT Handler",
            "description": "Receive CoT messages from TAK and post to Slack",
            "icon": "fa-slack",
            "category": "output",  # "input", "output", or "bidirectional"
            "config_fields": [
                PluginConfigField(
                    name="webhook_url",
                    label="Slack Webhook URL",
                    field_type="url",
                    required=True,
                    sensitive=True,
                    help_text="Incoming webhook URL from Slack app",
                ),
                PluginConfigField(
                    name="message_types",
                    label="Message Types to Handle",
                    field_type="text",
                    placeholder="b-t-f,b-a-*",
                    help_text="Comma-separated CoT types (e.g., b-t-f for chat, b-a-* for emergencies)",
                ),
                PluginConfigField(
                    name="uid_filter",
                    label="UID Filter (regex)",
                    field_type="text",
                    placeholder="^ANDROID-.*",
                    help_text="Only handle messages from matching UIDs (optional regex pattern)",
                ),
            ],
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Parse CoT and send to Slack if it matches our filters"""

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

            # Determine message type and send to Slack
            if cot_type.startswith("b-t-f"):
                # Chat message
                await self._send_to_slack(
                    f"💬 **{callsign}**: {message_text}", cot_type
                )
            elif cot_type.startswith("b-a"):
                # Emergency
                await self._send_to_slack(
                    f"🚨 **EMERGENCY**: {callsign}", cot_type, urgent=True
                )
            elif cot_type.startswith("a-"):
                # Position update - you might skip these to avoid spam
                # Uncomment below to enable position updates to Slack
                # await self._send_to_slack(
                #     f"📍 **{callsign}** position update",
                #     cot_type
                # )
                pass
            else:
                # Unknown/custom type - log it
                await self._send_to_slack(f"📡 **{callsign}**: {cot_type}", cot_type)

        except Exception as e:
            logger.error(f"SlackHandler failed to process CoT: {e}")

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

    async def _send_to_slack(self, text: str, cot_type: str, urgent: bool = False):
        """Send message to Slack webhook"""
        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            return

        payload = {
            "text": text,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": text},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"CoT Type: `{cot_type}`",
                        }
                    ],
                },
            ],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Slack webhook failed: {resp.status}")
        except Exception as e:
            logger.error(f"Failed to send to Slack: {e}")

    async def test_connection(self) -> Dict[str, Any]:
        """Test Slack webhook connection"""
        config = self.get_decrypted_config()
        webhook_url = config.get("webhook_url")

        if not webhook_url:
            return {
                "success": False,
                "error": "Missing webhook URL",
                "message": "Please configure a Slack webhook URL",
            }

        try:
            # Send test message to Slack
            test_payload = {
                "text": "🔧 TrakBridge connection test",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "🔧 **TrakBridge Connection Test**\nYour Slack handler is configured correctly!",
                        },
                    }
                ],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=test_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return {
                            "success": True,
                            "message": "Successfully sent test message to Slack",
                        }
                    else:
                        resp_text = await resp.text()
                        return {
                            "success": False,
                            "error": f"HTTP {resp.status}",
                            "message": f"Slack webhook returned error: {resp_text}",
                        }

        except aiohttp.ClientError as e:
            return {
                "success": False,
                "error": "Connection failed",
                "message": f"Failed to connect to Slack: {str(e)}",
            }
        except Exception as e:
            logger.error(f"SlackHandler connection test failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Connection test failed",
            }
