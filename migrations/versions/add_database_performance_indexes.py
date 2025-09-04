"""Add database performance indexes

Revision ID: add_database_performance_indexes
Revises: consolidated_initial_migration
Create Date: 2025-09-04 12:00:00.000000

This migration adds performance indexes for frequently queried fields
and foreign key relationships to optimize database query performance.

Phase 4: Database Model Optimization - Performance Indexes
"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import (
    table_exists,
    column_exists,
    index_exists,
    safe_create_index,
)

# revision identifiers, used by Alembic.
revision = 'add_database_performance_indexes'
down_revision = 'add_callsign_mapping_tables'
branch_labels = None
depends_on = None


def upgrade():
    """Add performance indexes for frequently queried fields."""
    
    # Stream table indexes
    if table_exists('streams'):
        # Index on tak_server_id (foreign key)
        if not index_exists('ix_streams_tak_server_id'):
            safe_create_index('ix_streams_tak_server_id', 'streams', ['tak_server_id'])
        
        # Index on is_active (frequently filtered)
        if not index_exists('ix_streams_is_active'):
            safe_create_index('ix_streams_is_active', 'streams', ['is_active'])
        
        # Index on plugin_type (frequently filtered)
        if not index_exists('ix_streams_plugin_type'):
            safe_create_index('ix_streams_plugin_type', 'streams', ['plugin_type'])

    # User table indexes  
    if table_exists('users'):
        # Index on username (already exists as unique, but ensure it's there)
        if not index_exists('ix_users_username'):
            safe_create_index('ix_users_username', 'users', ['username'])
        
        # Index on email (already exists as unique, but ensure it's there)
        if not index_exists('ix_users_email'):
            safe_create_index('ix_users_email', 'users', ['email'])
        
        # Index on auth_provider (frequently filtered for provider queries)
        if not index_exists('ix_users_auth_provider'):
            safe_create_index('ix_users_auth_provider', 'users', ['auth_provider'])
        
        # Index on status (frequently filtered for active user queries)
        if not index_exists('ix_users_status'):
            safe_create_index('ix_users_status', 'users', ['status'])

    # UserSession table indexes
    if table_exists('user_sessions'):
        # Index on user_id (foreign key)
        if not index_exists('ix_user_sessions_user_id'):
            safe_create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
        
        # Index on session_id (already exists as unique, but ensure it's there)
        if not index_exists('ix_user_sessions_session_id'):
            safe_create_index('ix_user_sessions_session_id', 'user_sessions', ['session_id'])
        
        # Index on expires_at (for session cleanup queries)
        if not index_exists('ix_user_sessions_expires_at'):
            safe_create_index('ix_user_sessions_expires_at', 'user_sessions', ['expires_at'])
        
        # Index on is_active (frequently filtered)
        if not index_exists('ix_user_sessions_is_active'):
            safe_create_index('ix_user_sessions_is_active', 'user_sessions', ['is_active'])

    # TakServer table indexes
    if table_exists('tak_servers'):
        # Index on name (already exists as unique, but ensure it's there)
        if not index_exists('ix_tak_servers_name'):
            safe_create_index('ix_tak_servers_name', 'tak_servers', ['name'])
        
        # Index on protocol (for protocol-specific queries)
        if not index_exists('ix_tak_servers_protocol'):
            safe_create_index('ix_tak_servers_protocol', 'tak_servers', ['protocol'])

    # CallsignMapping table indexes
    if table_exists('callsign_mappings'):
        # Compound index on (stream_id, identifier_value) for efficient lookups
        if not index_exists('ix_callsign_mappings_stream_identifier'):
            safe_create_index(
                'ix_callsign_mappings_stream_identifier', 
                'callsign_mappings', 
                ['stream_id', 'identifier_value']
            )
        
        # Index on stream_id (foreign key)
        if not index_exists('ix_callsign_mappings_stream_id'):
            safe_create_index('ix_callsign_mappings_stream_id', 'callsign_mappings', ['stream_id'])


def downgrade():
    """Remove performance indexes."""
    
    # Drop indexes in reverse order
    
    # CallsignMapping indexes
    if table_exists('callsign_mappings'):
        if index_exists('ix_callsign_mappings_stream_id'):
            op.drop_index('ix_callsign_mappings_stream_id', table_name='callsign_mappings')
        
        if index_exists('ix_callsign_mappings_stream_identifier'):
            op.drop_index('ix_callsign_mappings_stream_identifier', table_name='callsign_mappings')

    # TakServer indexes
    if table_exists('tak_servers'):
        if index_exists('ix_tak_servers_protocol'):
            op.drop_index('ix_tak_servers_protocol', table_name='tak_servers')
        
        if index_exists('ix_tak_servers_name'):
            op.drop_index('ix_tak_servers_name', table_name='tak_servers')

    # UserSession indexes
    if table_exists('user_sessions'):
        if index_exists('ix_user_sessions_is_active'):
            op.drop_index('ix_user_sessions_is_active', table_name='user_sessions')
        
        if index_exists('ix_user_sessions_expires_at'):
            op.drop_index('ix_user_sessions_expires_at', table_name='user_sessions')
        
        if index_exists('ix_user_sessions_session_id'):
            op.drop_index('ix_user_sessions_session_id', table_name='user_sessions')
        
        if index_exists('ix_user_sessions_user_id'):
            op.drop_index('ix_user_sessions_user_id', table_name='user_sessions')

    # User indexes
    if table_exists('users'):
        if index_exists('ix_users_status'):
            op.drop_index('ix_users_status', table_name='users')
        
        if index_exists('ix_users_auth_provider'):
            op.drop_index('ix_users_auth_provider', table_name='users')
        
        if index_exists('ix_users_email'):
            op.drop_index('ix_users_email', table_name='users')
        
        if index_exists('ix_users_username'):
            op.drop_index('ix_users_username', table_name='users')

    # Stream indexes
    if table_exists('streams'):
        if index_exists('ix_streams_plugin_type'):
            op.drop_index('ix_streams_plugin_type', table_name='streams')
        
        if index_exists('ix_streams_is_active'):
            op.drop_index('ix_streams_is_active', table_name='streams')
        
        if index_exists('ix_streams_tak_server_id'):
            op.drop_index('ix_streams_tak_server_id', table_name='streams')