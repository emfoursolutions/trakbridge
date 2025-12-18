# ABOUTME: CotArchiver plugin for storing all received CoT messages in database
# ABOUTME: Implements BaseOutputPlugin to provide audit trail and message archive functionality

from plugins.base_plugin import BaseOutputPlugin, PluginConfigField
from defusedxml import ElementTree as DefusedET
from typing import Any, Dict, List
from datetime import datetime


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


class CotArchiver(BaseOutputPlugin):
    """Store all received CoT messages in database for audit trail"""

    @property
    def plugin_name(self) -> str:
        return "cot_archiver"

    @property
    def plugin_metadata(self) -> Dict[str, Any]:
        return {
            "display_name": "CoT Message Archiver",
            "description": "Archive all received CoT messages to database for audit and replay",
            "icon": "fa-archive",
            "category": "output",
            "config_fields": [
                PluginConfigField(
                    name="archive_all",
                    label="Archive All Messages",
                    field_type="select",
                    required=True,
                    default_value="true",
                    options=[
                        {"value": "true", "label": "Yes - Archive everything"},
                        {"value": "false", "label": "No - Filter by type"},
                    ],
                    help_text="Archive all CoT messages or filter by type",
                ),
                PluginConfigField(
                    name="message_types",
                    label="Message Types to Archive",
                    field_type="text",
                    placeholder="b-t-f,b-a-*,a-f-*",
                    help_text="Comma-separated CoT types (only used if Archive All is disabled)",
                ),
                PluginConfigField(
                    name="include_position_updates",
                    label="Include Position Updates",
                    field_type="select",
                    required=True,
                    default_value="false",
                    options=[
                        {"value": "true", "label": "Yes"},
                        {"value": "false", "label": "No"},
                    ],
                    help_text="Archive position updates (a-* types) - can generate large volume",
                ),
                PluginConfigField(
                    name="retention_days",
                    label="Retention Period (days)",
                    field_type="number",
                    required=False,
                    default_value=30,
                    min_value=1,
                    max_value=365,
                    help_text="Number of days to keep archived messages (0 = keep forever)",
                ),
            ],
        }

    async def handle_cot_message(self, cot_xml: bytes, tak_server_id: int) -> None:
        """Archive CoT message to database"""

        config = self.get_decrypted_config()

        try:
            # Parse XML to extract metadata
            root = DefusedET.fromstring(cot_xml)
            cot_type = root.get("type", "unknown")
            uid = root.get("uid", "unknown")
            time_str = root.get("time", "")

            # Apply filters
            if not self._should_archive(cot_type):
                return

            # Extract additional metadata
            callsign = "unknown"
            detail = root.find("detail")
            if detail is not None:
                contact = detail.find("contact")
                if contact is not None:
                    callsign = contact.get("callsign", "unknown")

            # Store in database
            await self._store_message(
                tak_server_id=tak_server_id,
                cot_xml=cot_xml.decode("utf-8"),
                cot_type=cot_type,
                uid=uid,
                callsign=callsign,
                cot_time=time_str,
            )

            logger.debug(
                f"Archived CoT message: type={cot_type}, uid={uid}, callsign={callsign}"
            )

        except Exception as e:
            logger.error(f"CotArchiver failed to process CoT: {e}", exc_info=True)

    def _should_archive(self, cot_type: str) -> bool:
        """Determine if this message should be archived based on config"""
        config = self.get_decrypted_config()

        # Check if archiving everything
        archive_all = config.get("archive_all", "true").lower() == "true"
        if archive_all:
            # Still check position update filter
            include_position = (
                config.get("include_position_updates", "false").lower() == "true"
            )
            if cot_type.startswith("a-") and not include_position:
                return False
            return True

        # Filter by message types
        type_filter = config.get("message_types", "")
        if not type_filter:
            return False

        types = [t.strip() for t in type_filter.split(",")]
        for t in types:
            if t.endswith("*"):
                # Wildcard match
                if cot_type.startswith(t[:-1]):
                    return True
            elif cot_type == t:
                return True

        return False

    async def _store_message(
        self,
        tak_server_id: int,
        cot_xml: str,
        cot_type: str,
        uid: str,
        callsign: str,
        cot_time: str,
    ):
        """Store message in database"""
        try:
            # Import here to avoid circular imports
            from models import db
            from models.cot_message import CotMessage

            # Create new message record
            message = CotMessage(
                tak_server_id=tak_server_id,
                cot_xml=cot_xml,
                cot_type=cot_type,
                uid=uid,
                callsign=callsign,
                cot_time=cot_time,
                received_at=datetime.utcnow(),
            )

            db.session.add(message)
            db.session.commit()

        except Exception as e:
            logger.error(f"Failed to store CoT message in database: {e}", exc_info=True)
            # Don't re-raise - we don't want database issues to crash the handler

    async def test_connection(self) -> Dict[str, Any]:
        """Test database connection and configuration"""
        try:
            # Import here to avoid circular imports
            from models import db

            # Test database connection
            db.session.execute("SELECT 1")

            config = self.get_decrypted_config()
            archive_all = config.get("archive_all", "true").lower() == "true"
            include_position = (
                config.get("include_position_updates", "false").lower() == "true"
            )

            details = []
            if archive_all:
                details.append("Archiving all message types")
                if not include_position:
                    details.append("Position updates excluded")
            else:
                type_filter = config.get("message_types", "none")
                details.append(f"Filtering by types: {type_filter}")

            retention = config.get("retention_days", 30)
            if retention and int(retention) > 0:
                details.append(f"Retention: {retention} days")
            else:
                details.append("Retention: Keep forever")

            return {
                "success": True,
                "message": "Database connection successful. " + " | ".join(details),
            }

        except Exception as e:
            logger.error(f"CotArchiver connection test failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "message": "Database connection test failed",
            }
