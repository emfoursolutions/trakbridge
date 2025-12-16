"""Add enable_rx field to TAK servers for bidirectional communication control

Revision ID: add_enable_rx_to_tak_servers
Revises: add_cot_messages_table
Create Date: 2025-12-15 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import column_exists


# revision identifiers, used by Alembic.
revision = "add_enable_rx_to_tak_servers"
down_revision = "add_cot_messages_table"
branch_labels = None
depends_on = None


def upgrade():
    """
    Add enable_rx column to tak_servers table.

    This column controls whether the TAK server connection should be bidirectional
    (receiving CoT messages in addition to sending them). Defaults to True for
    backward compatibility - existing deployments will automatically enable RX.
    """
    # Only add the column if it doesn't already exist
    if not column_exists("tak_servers", "enable_rx"):
        with op.batch_alter_table("tak_servers", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "enable_rx",
                    sa.Boolean(),
                    nullable=False,
                    default=True,
                    server_default=sa.true(),
                )
            )
        print("Added enable_rx column to tak_servers table (default: True)")
    else:
        print("enable_rx column already exists in tak_servers table - skipping")


def downgrade():
    """
    Remove enable_rx column from tak_servers table.
    """
    # Only drop the column if it exists
    if column_exists("tak_servers", "enable_rx"):
        with op.batch_alter_table("tak_servers", schema=None) as batch_op:
            batch_op.drop_column("enable_rx")
        print("Dropped enable_rx column from tak_servers table")
    else:
        print("enable_rx column doesn't exist in tak_servers table - skipping")
