# ABOUTME: CotMessage model for storing archived CoT messages from TAK servers
# ABOUTME: Provides audit trail and message replay functionality for received CoT events

from models import db
from datetime import datetime
from sqlalchemy import Index


class CotMessage(db.Model):
    """Model for storing received CoT messages for audit and replay"""

    __tablename__ = "cot_messages"

    id = db.Column(db.Integer, primary_key=True)
    tak_server_id = db.Column(
        db.Integer, db.ForeignKey("tak_servers.id"), nullable=False, index=True
    )
    cot_xml = db.Column(db.Text, nullable=False)  # Raw CoT XML
    cot_type = db.Column(db.String(100), nullable=False, index=True)  # e.g., "b-t-f"
    uid = db.Column(db.String(255), nullable=False, index=True)  # Device UID
    callsign = db.Column(db.String(255), nullable=True, index=True)  # Device callsign
    cot_time = db.Column(db.String(50), nullable=True)  # Original CoT timestamp
    received_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    # Relationships
    tak_server = db.relationship(
        "TakServer",
        backref=db.backref("cot_messages", lazy="dynamic", cascade="all, delete-orphan"),
    )

    # Composite indexes for common queries
    __table_args__ = (
        Index("idx_cot_server_time", "tak_server_id", "received_at"),
        Index("idx_cot_type_time", "cot_type", "received_at"),
        Index("idx_cot_uid_time", "uid", "received_at"),
    )

    def __repr__(self):
        return f"<CotMessage {self.id} type={self.cot_type} uid={self.uid} at={self.received_at}>"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "tak_server_id": self.tak_server_id,
            "cot_type": self.cot_type,
            "uid": self.uid,
            "callsign": self.callsign,
            "cot_time": self.cot_time,
            "received_at": (
                self.received_at.isoformat() if self.received_at else None
            ),
            # Note: cot_xml not included by default due to size
        }

    def to_dict_with_xml(self) -> dict:
        """Convert to dictionary including XML content"""
        data = self.to_dict()
        data["cot_xml"] = self.cot_xml
        return data
