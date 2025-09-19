"""Add config_version field to Stream model for worker coordination

Revision ID: add_stream_config_version
Revises: 
Create Date: 2023-08-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'add_stream_config_version'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add config_version column to streams table"""
    # Add the config_version column with a default value
    op.add_column('streams', sa.Column('config_version', sa.DateTime(), nullable=True))
    
    # Update existing records to have the current timestamp as config_version
    # This ensures existing streams have a valid version timestamp
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE streams SET config_version = :current_time WHERE config_version IS NULL"),
        current_time=datetime.utcnow()
    )
    
    # Make the column non-nullable now that all records have values
    op.alter_column('streams', 'config_version', nullable=False)


def downgrade():
    """Remove config_version column from streams table"""
    op.drop_column('streams', 'config_version')