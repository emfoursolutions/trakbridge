"""
File: models/stream.py

Description:
    stream Model

Author: {{AUTHOR}}
Created: 2025-07-05
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import json

# Local application imports
from database import db, TimestampMixin
from plugins.base_plugin import BaseGPSPlugin


class Stream(db.Model, TimestampMixin):
    __tablename__ = 'streams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    plugin_type = db.Column(db.String(50), nullable=False)
    plugin_config = db.Column(db.Text)  # JSON string of plugin configuration
    tak_server_id = db.Column(db.Integer, db.ForeignKey('tak_servers.id'), nullable=True)
    poll_interval = db.Column(db.Integer, default=120)  # seconds
    cot_type = db.Column(db.String(50), default='a-f-G-U-C')  # COT type identifier
    cot_stale_time = db.Column(db.Integer, default=300)  # seconds until stale
    is_active = db.Column(db.Boolean, default=False)
    last_poll = db.Column(db.DateTime)
    last_error = db.Column(db.Text)  # Last error message
    total_messages_sent = db.Column(db.Integer, default=0)  # Statistics

    # Relationship to TAK server
    tak_server = db.relationship('TakServer', back_populates='streams')

    def __init__(
        self,
        name: str,
        plugin_type: str,
        poll_interval: int = 120,
        cot_type: str = 'a-f-G-U-C',
        cot_stale_time: int = 300,
        tak_server_id: int = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.name = name
        self.plugin_type = plugin_type
        self.poll_interval = poll_interval
        self.cot_type = cot_type
        self.cot_stale_time = cot_stale_time
        self.tak_server_id = tak_server_id

    def __repr__(self):
        return f'<Stream {self.name}>'

    def get_plugin_config(self):
        """Parse plugin configuration from JSON with decryption for sensitive fields"""
        if not self.plugin_config:
            return {}
        try:
            config = json.loads(self.plugin_config)
            # Decrypt sensitive fields for use
            return BaseGPSPlugin.decrypt_config_from_storage(self.plugin_type, config)
        except json.JSONDecodeError:
            return {}

    def set_plugin_config(self, config_dict):
        """Store plugin configuration as JSON with encryption for sensitive fields"""
        if config_dict:
            # Encrypt sensitive fields before storage
            encrypted_config = BaseGPSPlugin.encrypt_config_for_storage(self.plugin_type, config_dict)
            self.plugin_config = json.dumps(encrypted_config)
        else:
            self.plugin_config = None

    def get_raw_plugin_config(self):
        """Get raw plugin configuration without decryption (for display purposes)"""
        if not self.plugin_config:
            return {}
        try:
            return json.loads(self.plugin_config)
        except json.JSONDecodeError:
            return {}

    def is_field_encrypted(self, field_name):
        """Check if a specific field is encrypted in storage"""
        raw_config = self.get_raw_plugin_config()
        value = raw_config.get(field_name, '')
        return isinstance(value, str) and value.startswith('ENC:')

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
            'id': self.id,
            'name': self.name,
            'plugin_type': self.plugin_type,
            'plugin_config': plugin_config,
            'poll_interval': self.poll_interval,
            'cot_type': self.cot_type,
            'cot_stale_time': self.cot_stale_time,
            'is_active': self.is_active,
            'last_poll': self.last_poll.isoformat() if self.last_poll else None,
            'last_error': self.last_error,
            'total_messages_sent': self.total_messages_sent,
            'tak_server_id': self.tak_server_id,
            'tak_server_name': self.tak_server.name if self.tak_server else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
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
            elif hasattr(field_data, 'sensitive') and field_data.sensitive:
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
            return 'inactive'
        elif self.last_error:
            return 'error'
        else:
            return 'active'
