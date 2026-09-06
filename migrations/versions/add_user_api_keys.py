"""
ABOUTME: Migration creating the user_api_keys table for per-user API-key auth.
ABOUTME: Uses safe_create_table so re-runs and pre-existing tables are handled.

Revision ID: add_user_api_keys
Revises: add_plugin_management_tables
Create Date: 2026-08-24
"""

import sqlalchemy as sa

from migrations.migration_utils import (
    safe_create_index,
    safe_create_table,
    safe_drop_index,
    safe_drop_table,
)

revision = "add_user_api_keys"
down_revision = "add_plugin_management_tables"
branch_labels = None
depends_on = None


def upgrade():
    """Create the user_api_keys table and its supporting indexes."""
    safe_create_table(
        "user_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        # tb_pat_ (7) + 12-char preview = 19 chars. Indexed for the
        # request-path prefix lookup.
        sa.Column("token_prefix", sa.String(19), nullable=False, index=True),
        # HMAC-SHA256 hex = 64 chars. Unique because a hash collision
        # would require breaking SHA-256 on a 256-bit random input.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        # Per-key salt (32 hex chars = 16 bytes).
        sa.Column("token_salt", sa.String(32), nullable=False),
        # JSON array of "resource:action" scope strings.
        sa.Column("scopes", sa.Text(), nullable=False, server_default="[]"),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True, index=True
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # Composite index supporting the per-user active-key cap query
    # `WHERE user_id = ? AND is_active = TRUE`.
    safe_create_index(
        "ix_user_api_keys_user_active",
        "user_api_keys",
        ["user_id", "is_active"],
    )


def downgrade():
    safe_drop_index("ix_user_api_keys_user_active", "user_api_keys")
    safe_drop_table("user_api_keys")
