"""add_ca_cert_to_streams

Revision ID: 54faa293e582
Revises: add_inbound_stream_fields
Create Date: 2026-05-02 09:56:12.684326

"""
import sqlalchemy as sa

from migrations.migration_utils import safe_add_column, safe_drop_column


# revision identifiers, used by Alembic.
revision = '54faa293e582'
down_revision = 'add_inbound_stream_fields'
branch_labels = None
depends_on = None


def upgrade():
    safe_add_column(
        'streams',
        'ca_cert',
        sa.Column('ca_cert', sa.LargeBinary(), nullable=True),
    )
    safe_add_column(
        'streams',
        'ca_cert_filename',
        sa.Column('ca_cert_filename', sa.String(length=255), nullable=True),
    )


def downgrade():
    safe_drop_column('streams', 'ca_cert_filename')
    safe_drop_column('streams', 'ca_cert')
