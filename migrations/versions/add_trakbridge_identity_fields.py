"""Add TrakBridge identity fields to TAK servers

Revision ID: add_trakbridge_identity_fields
Revises: add_enable_rx_to_tak_servers
Create Date: 2025-12-20

"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import safe_add_column, safe_drop_column

# revision identifiers, used by Alembic.
revision = "add_trakbridge_identity_fields"
down_revision = "add_enable_rx_to_tak_servers"
branch_labels = None
depends_on = None


def upgrade():
    """Add TrakBridge identity configuration fields to tak_servers table"""

    safe_add_column(
        "tak_servers",
        "identity_callsign",
        sa.Column("identity_callsign", sa.String(100), nullable=True),
    )

    safe_add_column(
        "tak_servers",
        "identity_role",
        sa.Column("identity_role", sa.String(50), nullable=True),
    )

    safe_add_column(
        "tak_servers",
        "identity_team_color",
        sa.Column("identity_team_color", sa.String(50), nullable=True),
    )

    safe_add_column(
        "tak_servers",
        "identity_location_mgrs",
        sa.Column("identity_location_mgrs", sa.String(50), nullable=True),
    )

    safe_add_column(
        "tak_servers",
        "identity_uid_suffix",
        sa.Column("identity_uid_suffix", sa.String(20), nullable=True),
    )

    print("Added TrakBridge identity fields to tak_servers")


def downgrade():
    """Remove TrakBridge identity fields from tak_servers table"""

    safe_drop_column("tak_servers", "identity_uid_suffix")
    safe_drop_column("tak_servers", "identity_location_mgrs")
    safe_drop_column("tak_servers", "identity_team_color")
    safe_drop_column("tak_servers", "identity_role")
    safe_drop_column("tak_servers", "identity_callsign")

    print("Removed TrakBridge identity fields from tak_servers")
