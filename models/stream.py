"""
File: models/stream.py

Description:
    stream Model

Author: Emfour Solutions
Created: 2025-07-05
"""

# Standard library imports
import json
import logging

# Local application imports
from database import TimestampMixin, db
from plugins.base_plugin import BaseGPSPlugin
from utils.json_validator import JSONValidationError, safe_json_loads

# Module-level logger
logger = logging.getLogger(__name__)

# Association table for many-to-many relationship between streams and TAK servers
stream_tak_servers = db.Table(
    "stream_tak_servers",
    db.Column(
        "stream_id",
        db.Integer,
        db.ForeignKey("streams.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tak_server_id",
        db.Integer,
        db.ForeignKey("tak_servers.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # Add indexes for performance
    db.Index("idx_stream_tak_servers_stream_id", "stream_id"),
    db.Index("idx_stream_tak_servers_tak_server_id", "tak_server_id"),
)


class Stream(db.Model, TimestampMixin):
    __tablename__ = "streams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plugin_type = db.Column(db.String(50), nullable=False, index=True)
    plugin_config = db.Column(db.Text)  # JSON string of plugin configuration
    tak_server_id = db.Column(
        db.Integer, db.ForeignKey("tak_servers.id"), nullable=True, index=True
    )
    poll_interval = db.Column(db.Integer, default=120)  # seconds
    cot_type = db.Column(db.String(50), default="a-f-G-U-C")  # COT type identifier
    cot_stale_time = db.Column(db.Integer, default=300)  # seconds until stale
    is_active = db.Column(db.Boolean, default=False, index=True)
    last_poll = db.Column(db.DateTime)
    last_error = db.Column(db.Text)  # Last error message
    total_messages_sent = db.Column(db.Integer, default=0)  # Statistics
    cot_type_mode = db.Column(
        db.String(20), default="stream"
    )  # "stream" or "per_point"

    # New minimal fields for callsign mapping functionality
    enable_callsign_mapping = db.Column(db.Boolean, default=False)
    callsign_identifier_field = db.Column(
        db.String(100), nullable=True
    )  # Selected field name
    callsign_error_handling = db.Column(
        db.String(20), default="fallback"
    )  # "fallback" or "skip"
    enable_per_callsign_cot_types = db.Column(
        db.Boolean, default=False
    )  # Feature toggle

    # Relationships
    # Legacy single-server relationship (maintained for backward compatibility)
    tak_server = db.relationship("TakServer", back_populates="streams")

    # New many-to-many relationship with TAK servers
    tak_servers = db.relationship(
        "TakServer",
        secondary=stream_tak_servers,
        back_populates="streams_many",
        lazy="select",  # Allow eager loading with joinedload
    )

    callsign_mappings = db.relationship(
        "CallsignMapping", back_populates="stream", cascade="all, delete-orphan"
    )

    def __init__(
        self,
        name: str,
        plugin_type: str,
        poll_interval: int = 120,
        cot_type: str = "a-f-G-U-C",
        cot_stale_time: int = 300,
        tak_server_id: int = None,
        cot_type_mode: str = "stream",
        enable_callsign_mapping: bool = False,
        callsign_identifier_field: str = None,
        callsign_error_handling: str = "fallback",
        enable_per_callsign_cot_types: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.plugin_type = plugin_type
        self.poll_interval = poll_interval
        self.cot_type = cot_type
        self.cot_stale_time = cot_stale_time
        self.tak_server_id = tak_server_id
        self.cot_type_mode = cot_type_mode
        self.enable_callsign_mapping = enable_callsign_mapping
        self.callsign_identifier_field = callsign_identifier_field
        self.callsign_error_handling = callsign_error_handling
        self.enable_per_callsign_cot_types = enable_per_callsign_cot_types

    def __repr__(self):
        return f"<Stream {self.name}>"

    def get_plugin_config(self):
        """Parse plugin configuration from JSON with decryption for sensitive fields"""
        if not self.plugin_config:
            return {}
        try:
            # Use secure JSON parsing with validation
            config = safe_json_loads(
                self.plugin_config,
                max_size=256 * 1024,  # 256KB limit for database configs
                context=f"stream_{self.id}_plugin_config",
            )
            # Decrypt sensitive fields for use
            return BaseGPSPlugin.decrypt_config_from_storage(self.plugin_type, config)
        except JSONValidationError as e:
            logger.warning(
                f"JSON validation failed for stream {self.id} plugin config: {e}. "
                f"Details: {getattr(e, 'details', {})}"
            )
            return {}
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error for stream {self.id} plugin config: {e}")
            return {}

    def set_plugin_config(self, config_dict):
        """Store plugin configuration as JSON with encryption for sensitive fields"""
        if config_dict:
            try:
                # Validate the config dict structure before encryption
                if not isinstance(config_dict, dict):
                    raise ValueError(
                        f"Plugin config must be a dictionary, got {type(config_dict)}"
                    )

                # Check the serialized size before storage
                test_json = json.dumps(config_dict)
                if len(test_json.encode("utf-8")) > 256 * 1024:  # 256KB limit
                    raise ValueError(
                        "Plugin configuration exceeds maximum size limit (256KB)"
                    )

                # Encrypt sensitive fields before storage
                encrypted_config = BaseGPSPlugin.encrypt_config_for_storage(
                    self.plugin_type, config_dict
                )
                self.plugin_config = json.dumps(encrypted_config)

                logger.debug(
                    f"Set plugin config for stream {self.id}: {len(test_json)} bytes"
                )
                logger.debug(f"Plugin config content: {config_dict}")
                logger.debug(f"Encrypted config content: {encrypted_config}")

            except (ValueError, TypeError) as e:
                logger.error(f"Failed to set plugin config for stream {self.id}: {e}")
                raise ValueError(f"Invalid plugin configuration: {e}")
            except Exception as e:
                logger.error(
                    f"Unexpected error setting plugin config for stream {self.id}: {e}"
                )
                raise
        else:
            self.plugin_config = None

    def get_raw_plugin_config(self):
        """Get raw plugin configuration without decryption (for display purposes)"""
        if not self.plugin_config:
            return {}
        try:
            # Use secure JSON parsing for raw config access
            return safe_json_loads(
                self.plugin_config,
                max_size=256 * 1024,  # 256KB limit for database configs
                context=f"stream_{self.id}_raw_config",
            )
        except JSONValidationError as e:
            logger.warning(
                f"JSON validation failed for stream {self.id} raw config: {e}. "
                f"Details: {getattr(e, 'details', {})}"
            )
            return {}
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error for stream {self.id} raw config: {e}")
            return {}

    def is_field_encrypted(self, field_name):
        """Check if a specific field is encrypted in storage"""
        raw_config = self.get_raw_plugin_config()
        value = raw_config.get(field_name, "")
        return isinstance(value, str) and value.startswith("ENC:")

    def update_stats(self, messages_sent=0, error=None):
        """Update stream statistics and error state"""
        if messages_sent > 0:
            self.total_messages_sent += messages_sent
        if error:
            self.last_error = str(error)
        else:
            self.last_error = None
        self.last_poll = db.func.now()

    def to_dict(self, include_sensitive=False):
        """
        Convert stream to dictionary for JSON serialization

        Args:
            include_sensitive: If True, includes decrypted sensitive data
                              If False, masks sensitive fields for display
        """
        if include_sensitive:
            # For internal use - include decrypted sensitive data
            plugin_config = self.get_plugin_config()
        else:
            # For API/display - mask sensitive fields
            plugin_config = self._get_masked_plugin_config()

        return {
            "id": self.id,
            "name": self.name,
            "plugin_type": self.plugin_type,
            "plugin_config": plugin_config,
            "poll_interval": self.poll_interval,
            "cot_type": self.cot_type,
            "cot_stale_time": self.cot_stale_time,
            "is_active": self.is_active,
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
            "last_error": self.last_error,
            "total_messages_sent": self.total_messages_sent,
            "tak_server_id": self.tak_server_id,
            "tak_server_name": self.tak_server.name if self.tak_server else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def _get_masked_plugin_config(self):
        """Get plugin configuration with sensitive fields masked for display"""
        # Import inside method to avoid circular imports
        from plugins.plugin_manager import get_plugin_manager

        plugin_manager = get_plugin_manager()
        metadata = plugin_manager.get_plugin_metadata(self.plugin_type)

        if not metadata:
            return self.get_raw_plugin_config()

        # Get list of sensitive fields
        sensitive_fields = []
        for field_data in metadata.get("config_fields", []):
            if isinstance(field_data, dict) and field_data.get("sensitive"):
                sensitive_fields.append(field_data["name"])
            elif hasattr(field_data, "sensitive") and field_data.sensitive:
                sensitive_fields.append(field_data.name)

        # Mask sensitive fields
        masked_config = self.get_raw_plugin_config().copy()
        for field_name in sensitive_fields:
            if field_name in masked_config and masked_config[field_name]:
                if self.is_field_encrypted(field_name):
                    masked_config[field_name] = "••••••••"  # Show encrypted
                else:
                    masked_config[field_name] = "••••••••"  # Show masked

        return masked_config

    @property
    def status(self):
        """Get current status of the stream"""
        if not self.is_active:
            return "inactive"
        elif self.last_error:
            return "error"
        else:
            return "active"

    def get_all_tak_servers(self):
        """Get all TAK servers (combines legacy single server and new multiple servers)"""
        servers = []

        # Add legacy single server if it exists and is not already in the many-to-many relationship
        if self.tak_server:
            servers.append(self.tak_server)

        # Add servers from the many-to-many relationship
        many_to_many_servers = self.tak_servers
        for server in many_to_many_servers:
            # Only add if not already in list (avoid duplicates)
            if server not in servers:
                servers.append(server)

        return servers

    def get_tak_server_count(self):
        """Get total count of TAK servers configured for this stream"""
        return len(self.get_all_tak_servers())

    def get_tak_server_display_info(self):
        """Get display information for TAK servers in templates"""
        all_servers = self.get_all_tak_servers()
        server_count = len(all_servers)

        if server_count == 0:
            return {
                "has_servers": False,
                "count": 0,
                "single_server": None,
                "multiple_servers": [],
                "display_text": "Not configured",
            }
        elif server_count == 1:
            server = all_servers[0]
            return {
                "has_servers": True,
                "count": 1,
                "single_server": server,
                "multiple_servers": [],
                "display_text": server.name if server.name else "Unnamed",
            }
        else:
            return {
                "has_servers": True,
                "count": server_count,
                "single_server": None,
                "multiple_servers": all_servers,
                "display_text": f"{server_count} servers",
            }
