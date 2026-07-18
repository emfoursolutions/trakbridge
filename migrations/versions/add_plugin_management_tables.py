"""
ABOUTME: Migration creating installed_plugins and plugin_audit_log tables for the plugin manager.
ABOUTME: Uses safe_create_table so re-runs and pre-existing tables are handled gracefully.

Revision ID: add_plugin_management_tables
Revises: add_must_change_password
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from migrations.migration_utils import safe_create_table, safe_drop_table

revision = "add_plugin_management_tables"
down_revision = "add_must_change_password"
branch_labels = None
depends_on = None


def upgrade():
    safe_create_table(
        "installed_plugins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plugin_id", sa.String(100), nullable=False, unique=True, index=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column("version", sa.String(50)),
        sa.Column("author", sa.String(200)),
        sa.Column("description", sa.Text()),
        sa.Column("plugin_type", sa.String(20)),
        sa.Column(
            "package_format", sa.String(20), nullable=False, server_default="package"
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            index=True,
        ),
        sa.Column(
            "is_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tier", sa.String(20), nullable=False, server_default="community"),
        sa.Column("install_path", sa.Text()),
        sa.Column("installed_by", sa.String(100)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    safe_create_table(
        "plugin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plugin_id", sa.String(100), nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("performed_by", sa.String(100), nullable=False),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    safe_drop_table("plugin_audit_log")
    safe_drop_table("installed_plugins")
