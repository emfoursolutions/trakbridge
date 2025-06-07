# =============================================================================
# models/stream.py - Stream Model
# =============================================================================

from database import db, TimestampMixin  # Import both from database.py
import json


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

    # Relationship to TAK server - using back_populates instead of backref
    tak_server = db.relationship('TakServer', back_populates='streams')

    def __repr__(self):
        return f'<Stream {self.name}>'

    def get_plugin_config(self):
        """Parse plugin configuration from JSON"""
        if not self.plugin_config:
            return {}
        try:
            return json.loads(self.plugin_config)
        except json.JSONDecodeError:
            return {}

    def set_plugin_config(self, config_dict):
        """Store plugin configuration as JSON"""
        self.plugin_config = json.dumps(config_dict) if config_dict else None

    def update_stats(self, messages_sent=0, error=None):
        """Update stream statistics and error state"""
        if messages_sent > 0:
            self.total_messages_sent += messages_sent
        if error:
            self.last_error = str(error)
        else:
            self.last_error = None
        self.last_poll = db.func.now()

    def to_dict(self):
        """Convert stream to dictionary for JSON serialization"""
        return {
            'id': self.id,
            'name': self.name,
            'plugin_type': self.plugin_type,
            'plugin_config': self.get_plugin_config(),
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

    @property
    def status(self):
        """Get current status of the stream"""
        if not self.is_active:
            return 'inactive'
        elif self.last_error:
            return 'error'
        else:
            return 'active'