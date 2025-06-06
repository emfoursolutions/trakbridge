# =============================================================================
# migrations/add_stream_fields.py - Add missing fields to streams table
# =============================================================================

"""Add missing fields to streams table

Revision ID: add_stream_fields
Revises: (previous_revision)
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_stream_fields'
down_revision = None  # Replace with actual previous revision
branch_labels = None
depends_on = None


def upgrade():
    """Add missing columns to streams table"""

    # Add plugin_config column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('plugin_config', sa.Text(), nullable=True))
    except Exception:
        pass  # Column already exists

    # Add cot_type column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('cot_type', sa.String(50), nullable=False, server_default='a-f-G-U-C'))
    except Exception:
        pass  # Column already exists

    # Add cot_stale_time column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('cot_stale_time', sa.Integer(), nullable=False, server_default='300'))
    except Exception:
        pass  # Column already exists

    # Add last_error column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('last_error', sa.Text(), nullable=True))
    except Exception:
        pass  # Column already exists

    # Add last_poll column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('last_poll', sa.DateTime(), nullable=True))
    except Exception:
        pass  # Column already exists

    # Add total_messages_sent column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('total_messages_sent', sa.Integer(), nullable=False, server_default='0'))
    except Exception:
        pass  # Column already exists

    # Add is_active column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false'))
    except Exception:
        pass  # Column already exists

    # Add poll_interval column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('poll_interval', sa.Integer(), nullable=False, server_default='120'))
    except Exception:
        pass  # Column already exists

    # Add tak_server_id foreign key column if it doesn't exist
    try:
        op.add_column('streams', sa.Column('tak_server_id', sa.Integer(), nullable=True))
    except Exception:
        pass  # Column already exists

    # Add foreign key constraint if it doesn't exist
    try:
        op.create_foreign_key(
            'fk_streams_tak_server_id',
            'streams', 'tak_servers',
            ['tak_server_id'], ['id']
        )
    except Exception:
        pass  # Foreign key already exists

    # Ensure basic required columns exist (in case this is a fresh migration)
    try:
        op.add_column('streams', sa.Column('name', sa.String(100), nullable=False))
    except Exception:
        pass  # Column already exists

    try:
        op.add_column('streams', sa.Column('plugin_type', sa.String(50), nullable=False))
    except Exception:
        pass  # Column already exists


def downgrade():
    """Remove the added columns"""

    # Drop foreign key constraint first
    try:
        op.drop_constraint('fk_streams_tak_server_id', 'streams', type_='foreignkey')
    except Exception:
        pass

    # Drop columns in reverse order
    columns_to_drop = [
        'plugin_config',
        'cot_type',
        'cot_stale_time',
        'last_error',
        'last_poll',
        'total_messages_sent',
        'is_active',
        'poll_interval',
        'tak_server_id'
    ]

    for column in columns_to_drop:
        try:
            op.drop_column('streams', column)
        except Exception:
            pass  # Column might not exist or might be referenced elsewhere