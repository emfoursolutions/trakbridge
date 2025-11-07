"""Add team member fields to callsign mappings for team CoT functionality

Revision ID: add_team_member_fields_to_callsign_mappings
Revises: d1e2f3a4b5c6
Create Date: 2025-09-30 18:20:00.000000

"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import (
    column_exists,
    safe_add_column,
    safe_drop_column,
)


# revision identifiers, used by Alembic.
revision = "team_member_cot_mapping"
down_revision = "f085153337e8"
branch_labels = None
depends_on = None


def upgrade():
    """
    Add team member fields to callsign_mappings table.

    Adds three new nullable columns:
    - cot_type_override: String override for team member CoT type
    - team_role: Team member role selection (Sniper, Medic, etc.)
    - team_color: Team member color selection (Green, Red, etc.)

    These fields enable individual trackers to be displayed as ATAK team members
    rather than standard mil2525 points when cot_type_override is "team_member".
    """
    # Add cot_type_override column
    cot_type_override_column = sa.Column(
        "cot_type_override",
        sa.String(50),
        nullable=True,
        comment="Override for team member CoT type"
    )

    if safe_add_column("callsign_mappings", "cot_type_override", cot_type_override_column):
        print("Added cot_type_override column to callsign_mappings")

    # Add team_role column
    team_role_column = sa.Column(
        "team_role",
        sa.String(50),
        nullable=True,
        comment="Team member role selection"
    )

    if safe_add_column("callsign_mappings", "team_role", team_role_column):
        print("Added team_role column to callsign_mappings")

    # Add team_color column
    team_color_column = sa.Column(
        "team_color",
        sa.String(50),
        nullable=True,
        comment="Team member color selection"
    )

    if safe_add_column("callsign_mappings", "team_color", team_color_column):
        print("Added team_color column to callsign_mappings")


def downgrade():
    """
    Remove team member fields from callsign_mappings table.

    Safe rollback that only drops the columns if they exist.
    Preserves existing callsign mapping functionality.
    """
    # Drop columns in reverse order
    safe_drop_column("callsign_mappings", "team_color")
    safe_drop_column("callsign_mappings", "team_role")
    safe_drop_column("callsign_mappings", "cot_type_override")
    print("Removed team member fields from callsign_mappings")