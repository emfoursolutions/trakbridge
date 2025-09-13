"""Add indexes for enabled column in callsign_mappings for filtering performance

Revision ID: add_enabled_column_indexes
Revises: merge_heads_migration
Create Date: 2025-01-12 23:10:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "add_enabled_column_indexes"
down_revision = "merge_heads_migration"
branch_labels = None
depends_on = None


def index_exists(connection, table_name, index_name):
    """Check if index exists in table"""
    inspector = inspect(connection)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade():
    """Add index for enabled column for Phase 5 filtering performance"""
    connection = op.get_bind()

    # Check if index already exists
    if not index_exists(
        connection, "callsign_mappings", "ix_callsign_mappings_enabled"
    ):
        # Create index on enabled column for efficient filtering
        op.create_index(
            "ix_callsign_mappings_enabled",
            "callsign_mappings",
            ["enabled"],
            unique=False,
        )
        print("Created index ix_callsign_mappings_enabled for filtering performance")
    else:
        print("Index ix_callsign_mappings_enabled already exists, skipping")

    # Also create composite index for stream_id + enabled for optimal performance
    if not index_exists(
        connection, "callsign_mappings", "ix_callsign_mappings_stream_enabled"
    ):
        op.create_index(
            "ix_callsign_mappings_stream_enabled",
            "callsign_mappings",
            ["stream_id", "enabled"],
            unique=False,
        )
        print(
            "Created composite index ix_callsign_mappings_stream_enabled for optimized filtering"
        )
    else:
        print("Index ix_callsign_mappings_stream_enabled already exists, skipping")


def downgrade():
    """Remove indexes for enabled column"""
    connection = op.get_bind()

    # Drop composite index
    if index_exists(
        connection, "callsign_mappings", "ix_callsign_mappings_stream_enabled"
    ):
        op.drop_index(
            "ix_callsign_mappings_stream_enabled", table_name="callsign_mappings"
        )
        print("Dropped composite index ix_callsign_mappings_stream_enabled")

    # Drop enabled-only index
    if index_exists(connection, "callsign_mappings", "ix_callsign_mappings_enabled"):
        op.drop_index("ix_callsign_mappings_enabled", table_name="callsign_mappings")
        print("Dropped index ix_callsign_mappings_enabled")
