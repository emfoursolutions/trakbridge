"""
ABOUTME: Alembic migration adding inbound stream columns and missing performance indexes.
ABOUTME: Supports push-based data ingestion from external devices via HTTP.

Add inbound stream fields and missing indexes

Revision ID: add_inbound_stream_fields
Revises: add_trakbridge_identity_fields
Create Date: 2026-04-08

"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import safe_add_column, safe_create_index

# revision identifiers, used by Alembic.
revision = "add_inbound_stream_fields"
down_revision = "add_trakbridge_identity_fields"
branch_labels = None
depends_on = None


def upgrade():
    """
    Add inbound stream columns and performance indexes.

    New columns enable push-based data ingestion where external devices POST
    data to TrakBridge rather than TrakBridge polling for it.
    """
    # Inbound stream columns
    safe_add_column(
        "streams",
        "stream_mode",
        sa.Column(
            "stream_mode",
            sa.String(20),
            nullable=False,
            server_default="poll",
        ),
    )
    safe_add_column(
        "streams",
        "inbound_api_key",
        sa.Column("inbound_api_key", sa.String(500), nullable=True),
    )
    safe_add_column(
        "streams",
        "inbound_rate_limit",
        sa.Column(
            "inbound_rate_limit",
            sa.Integer,
            nullable=True,
            server_default="60",
        ),
    )
    safe_add_column(
        "streams",
        "inbound_ip_allowlist",
        sa.Column("inbound_ip_allowlist", sa.Text, nullable=True),
    )
    safe_add_column(
        "streams",
        "inbound_preview_mode",
        sa.Column(
            "inbound_preview_mode",
            sa.Boolean,
            nullable=False,
            server_default="1",
        ),
    )

    # Indexes for inbound columns
    safe_create_index("idx_streams_stream_mode", "streams", ["stream_mode"])

    # Missing performance indexes (Phase 0.5)
    safe_create_index("idx_streams_last_poll", "streams", ["last_poll"])
    safe_create_index("idx_streams_created_at", "streams", ["created_at"])
    safe_create_index(
        "idx_streams_active_last_poll", "streams", ["is_active", "last_poll"]
    )


def downgrade():
    """Remove inbound stream columns and indexes."""
    from migrations.migration_utils import safe_drop_column, safe_drop_index

    # Drop indexes
    safe_drop_index("idx_streams_active_last_poll", "streams")
    safe_drop_index("idx_streams_created_at", "streams")
    safe_drop_index("idx_streams_last_poll", "streams")
    safe_drop_index("idx_streams_stream_mode", "streams")

    # Drop columns
    safe_drop_column("streams", "inbound_preview_mode")
    safe_drop_column("streams", "inbound_ip_allowlist")
    safe_drop_column("streams", "inbound_rate_limit")
    safe_drop_column("streams", "inbound_api_key")
    safe_drop_column("streams", "stream_mode")
