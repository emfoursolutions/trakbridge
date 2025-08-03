"""Add timezone support to UserSession datetime columns

Revision ID: add_timezone_to_user_sessions
Revises: 3120f5bf60a4
Create Date: 2025-08-03 09:04:29.000000

"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = "add_timezone_to_user_sessions"
down_revision = "3120f5bf60a4"
branch_labels = None
depends_on = None


def upgrade():
    """Add timezone support to expires_at and last_activity columns in user_sessions table"""
    # For SQLite, we need to recreate the table with timezone-aware columns
    # Create new table with timezone-aware columns
    op.execute(
        """
        CREATE TABLE user_sessions_new (
            id INTEGER NOT NULL PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            ip_address VARCHAR(45),
            user_agent TEXT,
            provider VARCHAR(50) NOT NULL DEFAULT 'local',
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_activity TIMESTAMP WITH TIME ZONE NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            provider_session_data TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """
    )

    # Copy data from old table to new table, converting naive datetimes to UTC
    op.execute(
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
    """
    )

    # Drop old table and rename new one
    op.drop_table("user_sessions")
    op.execute("ALTER TABLE user_sessions_new RENAME TO user_sessions")

    # Recreate indexes
    op.create_index(
        "ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True
    )


def downgrade():
    """Remove timezone support from datetime columns"""
    # Create table without timezone support
    op.execute(
        """
        CREATE TABLE user_sessions_old (
            id INTEGER NOT NULL PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            ip_address VARCHAR(45),
            user_agent TEXT,
            provider VARCHAR(50) NOT NULL DEFAULT 'local',
            expires_at DATETIME NOT NULL,
            last_activity DATETIME NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            provider_session_data TEXT,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users (id)
        )
    """
    )

    # Copy data back, stripping timezone info
    op.execute(
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
    """
    )

    # Drop new table and rename old one back
    op.drop_table("user_sessions")
    op.execute("ALTER TABLE user_sessions_old RENAME TO user_sessions")

    # Recreate indexes
    op.create_index(
        "ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True
    )
