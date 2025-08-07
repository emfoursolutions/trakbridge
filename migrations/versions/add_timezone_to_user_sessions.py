"""Add timezone support to UserSession datetime columns

Revision ID: add_timezone_to_user_sessions
Revises: 3120f5bf60a4
Create Date: 2025-08-03 09:04:29.000000

"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from migrations.migration_utils import table_exists, safe_execute, safe_create_index, safe_drop_table

# revision identifiers, used by Alembic.
revision = "add_timezone_to_user_sessions"
down_revision = "3120f5bf60a4"
branch_labels = None
depends_on = None


def upgrade():
    """Add timezone support to expires_at and last_activity columns in user_sessions table"""
    
    # Check if user_sessions table exists
    if not table_exists("user_sessions"):
        print("WARNING: Table 'user_sessions' does not exist. Skipping timezone migration.")
        return
    
    # Check if the migration has already been applied
    # (Look for timezone support in the table structure)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = inspector.get_columns("user_sessions")
    
    # Check if we already have timezone-aware columns
    for col in columns:
        if col['name'] in ['expires_at', 'last_activity'] and 'TIME ZONE' in str(col['type']):
            print("Timezone support already exists in user_sessions table. Skipping migration.")
            return
    
    # Create new table with timezone-aware columns (PostgreSQL/SQLite compatible)
    conn = op.get_bind()
    dialect = conn.dialect.name
    
    # Use appropriate boolean default for the database
    boolean_default = "TRUE" if dialect == "postgresql" else "1"
    
    success = safe_execute(
        f"""
        CREATE TABLE user_sessions_new (
            id INTEGER NOT NULL PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            ip_address VARCHAR(45),
            user_agent TEXT,
            provider VARCHAR(50) NOT NULL DEFAULT 'local',
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_activity TIMESTAMP WITH TIME ZONE NOT NULL,
            is_active BOOLEAN DEFAULT {boolean_default},
            provider_session_data TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
        """,
        "Create new user_sessions table with timezone support"
    )
    
    if not success:
        print("Failed to create new user_sessions table. Aborting migration.")
        return

    # Copy data from old table to new table, converting naive datetimes to UTC
    safe_execute(
        """
        INSERT INTO user_sessions_new (
            id, session_id, user_id, ip_address, user_agent, provider,
            expires_at, last_activity, is_active, provider_session_data,
            created_at, updated_at
        )
        SELECT 
            id, session_id, user_id, ip_address, user_agent, provider,
            expires_at || '+00:00' as expires_at,
            last_activity || '+00:00' as last_activity,
            is_active, provider_session_data,
            COALESCE(created_at || '+00:00', datetime('now', '+00:00')) as created_at,
            COALESCE(updated_at || '+00:00', datetime('now', '+00:00')) as updated_at
        FROM user_sessions
        """,
        "Copy data to new user_sessions table"
    )

    # Drop old table and rename new one
    safe_drop_table("user_sessions")
    safe_execute(
        "ALTER TABLE user_sessions_new RENAME TO user_sessions",
        "Rename new table to user_sessions"
    )

    # Recreate indexes
    safe_create_index(
        "ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True
    )


def downgrade():
    """Remove timezone support from datetime columns"""
    
    # Check if user_sessions table exists
    if not table_exists("user_sessions"):
        print("WARNING: Table 'user_sessions' does not exist. Cannot downgrade timezone migration.")
        return
    
    # Create table without timezone support (PostgreSQL/SQLite compatible)
    conn = op.get_bind()
    dialect = conn.dialect.name
    
    # Use appropriate boolean default for the database
    boolean_default = "TRUE" if dialect == "postgresql" else "1"
    
    success = safe_execute(
        f"""
        CREATE TABLE user_sessions_old (
            id INTEGER NOT NULL PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            ip_address VARCHAR(45),
            user_agent TEXT,
            provider VARCHAR(50) NOT NULL DEFAULT 'local',
            expires_at DATETIME NOT NULL,
            last_activity DATETIME NOT NULL,
            is_active BOOLEAN DEFAULT {boolean_default},
            provider_session_data TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
        """,
        "Create user_sessions table without timezone support"
    )
    
    if not success:
        print("Failed to create downgrade table. Aborting downgrade.")
        return

    # Copy data back, stripping timezone info
    safe_execute(
        """
        INSERT INTO user_sessions_old (
            id, session_id, user_id, ip_address, user_agent, provider,
            expires_at, last_activity, is_active, provider_session_data,
            created_at, updated_at
        )
        SELECT 
            id, session_id, user_id, ip_address, user_agent, provider,
            REPLACE(expires_at, '+00:00', '') as expires_at,
            REPLACE(last_activity, '+00:00', '') as last_activity,
            is_active, provider_session_data,
            REPLACE(created_at, '+00:00', '') as created_at,
            REPLACE(updated_at, '+00:00', '') as updated_at
        FROM user_sessions
        """,
        "Copy data back without timezone info"
    )

    # Drop new table and rename old one back
    safe_drop_table("user_sessions")
    safe_execute(
        "ALTER TABLE user_sessions_old RENAME TO user_sessions",
        "Rename table back to user_sessions"
    )

    # Recreate indexes
    safe_create_index(
        "ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True
    )
