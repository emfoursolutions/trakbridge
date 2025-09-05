"""Add callsign mapping tables and stream fields

Revision ID: add_callsign_mapping_tables
Revises: merge_heads_migration
Create Date: 2025-08-30 08:00:00.000000

This migration adds:
1. callsign_mappings table - stores custom callsign assignments for tracker identifiers
2. New columns to streams table for callsign mapping configuration:
   - enable_callsign_mapping (Boolean, default False)
   - callsign_identifier_field (String, nullable)
   - callsign_error_handling (String, default 'fallback')  
   - enable_per_callsign_cot_types (Boolean, default False)

Cross-database compatible with MySQL, PostgreSQL, and SQLite.
"""

import sqlalchemy as sa
from alembic import op

from migrations.migration_utils import (
    column_exists,
    safe_add_column,
    safe_create_index,
    safe_create_table,
    safe_drop_column,
    safe_drop_table,
    table_exists,
)

# revision identifiers, used by Alembic.
revision = "add_callsign_mapping_tables"
down_revision = "merge_heads_migration"
branch_labels = None
depends_on = None


def upgrade():
    """Add callsign mapping tables and stream configuration fields"""

    # 1. Create callsign_mappings table if it doesn't exist
    if not table_exists("callsign_mappings"):
        safe_create_table(
            "callsign_mappings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("stream_id", sa.Integer(), nullable=False),
            sa.Column("identifier_value", sa.String(255), nullable=False),
            sa.Column("custom_callsign", sa.String(100), nullable=False),
            sa.Column("cot_type", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "stream_id", "identifier_value", name="unique_stream_identifier"
            ),
        )
        print("Created callsign_mappings table")
    else:
        print("Table 'callsign_mappings' already exists")

    # 2. Add new columns to streams table
    if table_exists("streams"):
        # Add enable_callsign_mapping column
        if not column_exists("streams", "enable_callsign_mapping"):
            # Use explicit server_default for SQLite compatibility when adding NOT NULL columns
            enable_mapping_col = sa.Column(
                "enable_callsign_mapping",
                sa.Boolean,
                nullable=False,
                server_default="0",  # SQLite-compatible default for False
            )
            safe_add_column("streams", "enable_callsign_mapping", enable_mapping_col)
        else:
            print("Column 'enable_callsign_mapping' already exists in streams table")

        # Add callsign_identifier_field column
        if not column_exists("streams", "callsign_identifier_field"):
            identifier_field_col = sa.Column(
                "callsign_identifier_field", sa.String(100), nullable=True
            )
            safe_add_column(
                "streams", "callsign_identifier_field", identifier_field_col
            )
        else:
            print("Column 'callsign_identifier_field' already exists in streams table")

        # Add callsign_error_handling column
        if not column_exists("streams", "callsign_error_handling"):
            # Use explicit server_default for SQLite compatibility when adding NOT NULL columns
            error_handling_col = sa.Column(
                "callsign_error_handling",
                sa.String(20),
                nullable=False,
                server_default="fallback",  # SQLite-compatible server-side default
            )
            safe_add_column("streams", "callsign_error_handling", error_handling_col)
            # Set default value for existing rows
            op.execute(
                "UPDATE streams SET callsign_error_handling = 'fallback' WHERE callsign_error_handling IS NULL"
            )
        else:
            print("Column 'callsign_error_handling' already exists in streams table")

        # Add enable_per_callsign_cot_types column
        if not column_exists("streams", "enable_per_callsign_cot_types"):
            # Use explicit server_default for SQLite compatibility when adding NOT NULL columns
            per_cot_types_col = sa.Column(
                "enable_per_callsign_cot_types",
                sa.Boolean,
                nullable=False,
                server_default="0",  # SQLite-compatible default for False
            )
            safe_add_column(
                "streams", "enable_per_callsign_cot_types", per_cot_types_col
            )
        else:
            print(
                "Column 'enable_per_callsign_cot_types' already exists in streams table"
            )

        print("Added callsign mapping columns to streams table")
    else:
        print("WARNING: Table 'streams' does not exist. Cannot add callsign columns.")

    print("Callsign mapping migration completed successfully")


def downgrade():
    """Remove callsign mapping tables and stream configuration fields"""

    # 1. Drop callsign_mappings table
    safe_drop_table("callsign_mappings")

    # 2. Remove columns from streams table if they exist
    if table_exists("streams"):
        safe_drop_column("streams", "enable_per_callsign_cot_types")
        safe_drop_column("streams", "callsign_error_handling")
        safe_drop_column("streams", "callsign_identifier_field")
        safe_drop_column("streams", "enable_callsign_mapping")
        print("Removed callsign mapping columns from streams table")

    print("Callsign mapping migration rollback completed successfully")
