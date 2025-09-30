"""
ABOUTME: CallsignMapping model for tracker callsign configuration functionality
ABOUTME: Defines database model for per-stream custom tracker callsign assignments with CoT type overrides

File: models/callsign_mapping.py

Description:
    CallsignMapping model that stores custom callsign assignments for individual
    trackers within GPS data streams. Each mapping links a tracker identifier
    (like IMEI, device name, etc.) to a user-defined callsign and optional
    CoT type override, providing operational flexibility for TAK server display.

Author: Emfour Solutions
Created: 2025-08-30
"""

# Local application imports
from database import TimestampMixin, db


class CallsignMapping(db.Model, TimestampMixin):
    """
    Maps tracker identifiers to custom callsigns for individual streams

    Each mapping belongs to a specific stream and maps a tracker identifier
    (extracted from GPS data using the stream's configured field) to a
    user-assigned callsign. Optional per-callsign CoT type overrides are
    supported for advanced operational requirements.
    """

    __tablename__ = "callsign_mappings"

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(
        db.Integer, db.ForeignKey("streams.id"), nullable=False, index=True
    )
    identifier_value = db.Column(
        db.String(255), nullable=False
    )  # Raw identifier (IMEI, device_name, etc.)
    custom_callsign = db.Column(
        db.String(100), nullable=False
    )  # User-assigned callsign
    cot_type = db.Column(db.String(50), nullable=True)  # Per-callsign CoT type override
    enabled = db.Column(
        db.Boolean, nullable=False, default=True
    )  # Enable/disable tracker
    cot_type_override = db.Column(
        db.String(50), nullable=True
    )  # Override for team member CoT type
    team_role = db.Column(
        db.String(50), nullable=True
    )  # Team member role selection
    team_color = db.Column(
        db.String(50), nullable=True
    )  # Team member color selection

    # Relationships
    stream = db.relationship("Stream", back_populates="callsign_mappings")

    # Constraints and Indexes
    __table_args__ = (
        db.UniqueConstraint(
            "stream_id", "identifier_value", name="unique_stream_identifier"
        ),
        db.Index(
            "ix_callsign_mappings_stream_identifier", "stream_id", "identifier_value"
        ),
    )

    def __init__(
        self,
        stream_id: int,
        identifier_value: str,
        custom_callsign: str,
        cot_type: str = None,
        enabled: bool = True,
        cot_type_override: str = None,
        team_role: str = None,
        team_color: str = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.stream_id = stream_id
        self.identifier_value = identifier_value
        self.custom_callsign = custom_callsign
        self.cot_type = cot_type
        self.enabled = enabled
        self.cot_type_override = cot_type_override
        self.team_role = team_role
        self.team_color = team_color

    def __repr__(self):
        return f"<CallsignMapping {self.identifier_value} -> {self.custom_callsign}>"

    def validate_team_member_fields(self):
        """Validate team member configuration fields"""
        valid_roles = [
            "Team Member", "Team Lead", "HQ", "Sniper", "Medic",
            "Forward Observer", "RTO", "K9"
        ]

        valid_colors = [
            "Teal", "Green", "Dark Green", "Brown", "White", "Yellow",
            "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue",
            "Blue", "Cyan"
        ]

        # If cot_type_override is "team_member", both role and color are required
        if self.cot_type_override == "team_member":
            if not self.team_role or not self.team_color:
                raise ValueError("Team member configuration requires both role and color")

            if self.team_role not in valid_roles:
                raise ValueError(f"Invalid team role: {self.team_role}. Must be one of: {', '.join(valid_roles)}")

            if self.team_color not in valid_colors:
                raise ValueError(f"Invalid team color: {self.team_color}. Must be one of: {', '.join(valid_colors)}")

        # If not team_member, role and color can be null - no validation needed

    def to_dict(self):
        """Convert callsign mapping to dictionary for JSON serialization"""
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "identifier_value": self.identifier_value,
            "custom_callsign": self.custom_callsign,
            "cot_type": self.cot_type,
            "enabled": self.enabled,
            "cot_type_override": self.cot_type_override,
            "team_role": self.team_role,
            "team_color": self.team_color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
