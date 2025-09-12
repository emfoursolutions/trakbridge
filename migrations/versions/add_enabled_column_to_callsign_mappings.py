"""Add enabled column to callsign mappings for tracker control

Revision ID: add_enabled_column_to_callsign_mappings
Revises: c530e1fd8e8d
Create Date: 2025-09-12 15:13:00.000000

"""
from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import column_exists, safe_add_column, safe_drop_column, get_boolean_column


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'c530e1fd8e8d'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add 'enabled' column to callsign_mappings table.
    
    This column allows users to enable/disable individual trackers in callsign mapping,
    controlling which trackers send CoT data to TAK servers while preserving configuration.
    """
    # Use safe column addition with existence check
    enabled_column = get_boolean_column('enabled', nullable=False, default=True)
    
    if safe_add_column('callsign_mappings', 'enabled', enabled_column):
        # Set all existing records to enabled (True) as default
        op.execute(sa.text("UPDATE callsign_mappings SET enabled = 1"))
        print("Set all existing callsign mappings to enabled=True")
    

def downgrade():
    """
    Remove 'enabled' column from callsign_mappings table.
    
    Safe rollback that only drops the column if it exists.
    """
    safe_drop_column('callsign_mappings', 'enabled')