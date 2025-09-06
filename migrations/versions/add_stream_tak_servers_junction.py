"""Add stream_tak_servers junction table for multi-server support (Phase 2A)

Revision ID: b1c2d3e4f5g6
Revises: 0a9c5469abc6
Create Date: 2025-09-06 12:00:00.000000

This migration implements Phase 2A: Database Schema Only
- Adds many-to-many relationship between streams and TAK servers
- Maintains backward compatibility with existing single-server relationships
- Migrates existing stream-server relationships to new junction table
- Zero impact on existing functionality
"""

import sqlalchemy as sa
from alembic import op

from migrations.migration_utils import table_exists, column_exists, index_exists

# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5g6"
down_revision = "add_database_performance_indexes"
branch_labels = None
depends_on = None


def upgrade():
    """
    Phase 2A Upgrade: Add multi-server support schema
    
    This migration:
    1. Creates stream_tak_servers junction table
    2. Adds proper foreign key constraints and indexes
    3. Migrates existing stream-server relationships
    4. Maintains backward compatibility
    """
    
    # Create junction table for many-to-many relationship
    if not table_exists('stream_tak_servers'):
        op.create_table(
            'stream_tak_servers',
            sa.Column('stream_id', sa.Integer(), nullable=False),
            sa.Column('tak_server_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['stream_id'], ['streams.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['tak_server_id'], ['tak_servers.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('stream_id', 'tak_server_id')
        )
        
        print("Created stream_tak_servers junction table")
    
    # Add indexes for performance
    if not index_exists('idx_stream_tak_servers_stream_id'):
        op.create_index(
            'idx_stream_tak_servers_stream_id', 
            'stream_tak_servers', 
            ['stream_id']
        )
    
    if not index_exists('idx_stream_tak_servers_tak_server_id'):
        op.create_index(
            'idx_stream_tak_servers_tak_server_id', 
            'stream_tak_servers', 
            ['tak_server_id']
        )
    
    # Migrate existing stream-server relationships to junction table
    # This preserves all existing single-server relationships
    connection = op.get_bind()
    
    # Get all streams that have a TAK server assigned (non-NULL tak_server_id)
    existing_relationships = connection.execute(
        sa.text("""
            SELECT id, tak_server_id 
            FROM streams 
            WHERE tak_server_id IS NOT NULL
        """)
    ).fetchall()
    
    # Insert into junction table
    if existing_relationships:
        junction_data = [
            {'stream_id': row.id, 'tak_server_id': row.tak_server_id}
            for row in existing_relationships
        ]
        
        # Insert relationships into junction table
        op.bulk_insert(
            sa.table(
                'stream_tak_servers',
                sa.column('stream_id', sa.Integer),
                sa.column('tak_server_id', sa.Integer)
            ),
            junction_data
        )
        
        print(f"Migrated {len(junction_data)} existing stream-server relationships to junction table")
    
    # NOTE: We deliberately DO NOT drop the tak_server_id column from streams table
    # This maintains backward compatibility and allows Phase 2A to be non-breaking
    # The legacy column will be used alongside the new many-to-many relationship
    
    print("Phase 2A schema migration completed successfully")
    print("- Junction table created with proper constraints and indexes")
    print("- Existing relationships migrated to new schema")  
    print("- Backward compatibility maintained")


def downgrade():
    """
    Phase 2A Downgrade: Remove multi-server support schema
    
    This rollback:
    1. Removes junction table and indexes
    2. Preserves legacy single-server relationships
    3. No data loss for existing functionality
    """
    
    # Drop indexes first
    if index_exists('idx_stream_tak_servers_tak_server_id'):
        op.drop_index('idx_stream_tak_servers_tak_server_id', table_name='stream_tak_servers')
    
    if index_exists('idx_stream_tak_servers_stream_id'):
        op.drop_index('idx_stream_tak_servers_stream_id', table_name='stream_tak_servers')
    
    # Drop junction table
    if table_exists('stream_tak_servers'):
        op.drop_table('stream_tak_servers')
        print("Dropped stream_tak_servers junction table")
    
    # NOTE: We do not need to restore any data to the streams.tak_server_id column
    # because we never removed it in the upgrade. The legacy relationships remain intact.
    
    print("Phase 2A schema rollback completed successfully")
    print("- Junction table and indexes removed")
    print("- Legacy single-server relationships preserved")