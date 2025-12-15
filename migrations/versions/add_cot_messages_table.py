"""Add cot_messages table for CoT message archiving

Revision ID: add_cot_messages_table
Revises:
Create Date: 2025-12-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_cot_messages_table"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "cot_messages" not in tables:
        op.create_table(
            "cot_messages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tak_server_id", sa.Integer(), nullable=False),
            sa.Column("cot_xml", sa.Text(), nullable=False),
            sa.Column("cot_type", sa.String(length=100), nullable=False),
            sa.Column("uid", sa.String(length=255), nullable=False),
            sa.Column("callsign", sa.String(length=255), nullable=True),
            sa.Column("cot_time", sa.String(length=50), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["tak_server_id"],
                ["tak_servers.id"],
            ),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        with op.batch_alter_table("cot_messages", schema=None) as batch_op:
            batch_op.create_index(
                "idx_cot_server_time", ["tak_server_id", "received_at"], unique=False
            )
            batch_op.create_index(
                "idx_cot_type_time", ["cot_type", "received_at"], unique=False
            )
            batch_op.create_index(
                "idx_cot_uid_time", ["uid", "received_at"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_cot_messages_callsign"), ["callsign"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_cot_messages_cot_type"), ["cot_type"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_cot_messages_received_at"), ["received_at"], unique=False
            )
            batch_op.create_index(
                batch_op.f("ix_cot_messages_tak_server_id"),
                ["tak_server_id"],
                unique=False,
            )
            batch_op.create_index(
                batch_op.f("ix_cot_messages_uid"), ["uid"], unique=False
            )


def downgrade():
    op.drop_table("cot_messages")
