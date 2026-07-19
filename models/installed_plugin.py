"""
ABOUTME: Models for the plugin manager — installed external plugins and their audit trail.
ABOUTME: InstalledPlugin mirrors plugin.yaml metadata; PluginAuditLog records admin actions.

Author: Emfour Solutions
Created: 2026-07-14
"""

from database import TimestampMixin, db


class InstalledPlugin(db.Model, TimestampMixin):
    __tablename__ = "installed_plugins"

    id = db.Column(db.Integer, primary_key=True)
    plugin_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200))
    version = db.Column(db.String(50))
    author = db.Column(db.String(200))
    description = db.Column(db.Text)
    plugin_type = db.Column(db.String(20))  # "gps", "inbound", or "output"
    package_format = db.Column(db.String(20), default="package", nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False, index=True)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    tier = db.Column(db.String(20), default="community", nullable=False)
    install_path = db.Column(db.Text)  # relative path under external_plugins/
    installed_by = db.Column(db.String(100))
    metadata_json = db.Column(db.Text)  # full plugin.yaml as JSON

    def __repr__(self):
        return f"<InstalledPlugin {self.plugin_id} v{self.version}>"


class PluginAuditLog(db.Model, TimestampMixin):
    __tablename__ = "plugin_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    plugin_id = db.Column(db.String(100), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    performed_by = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)  # JSON context

    def __repr__(self):
        return f"<PluginAuditLog {self.plugin_id} {self.action}>"
