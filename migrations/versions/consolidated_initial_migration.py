"""Consolidated initial migration - all database setup

Revision ID: consolidated_initial_migration
Revises: 
Create Date: 2025-08-13 01:15:00.000000

This migration consolidates all previous migrations into a single operation:
1. Add cot_type_mode column to streams table
2. Create authentication tables (users, user_sessions) 
3. Add provider field to user_sessions table
4. Add timezone support to UserSession datetime columns

This provides faster deployment and eliminates bootstrap timing issues.
"""

from datetime import datetime, timezone
from enum import Enum

import sqlalchemy as sa
from alembic import op
from migrations.migration_utils import (
    table_exists,
    column_exists, 
    safe_execute,
    safe_create_index,
    get_dialect,
    get_enum_column,
    add_enum_check_constraint,
)

# revision identifiers, used by Alembic.
revision = "consolidated_initial_migration"
down_revision = None
branch_labels = None
depends_on = None


class AuthProvider(Enum):
    """Authentication provider types for migration"""
    LOCAL = "LOCAL"
    OIDC = "OIDC"
    LDAP = "LDAP"


class UserRole(Enum):
    """User role definitions for migration"""
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"  
    VIEWER = "VIEWER"
    USER = "USER"


class AccountStatus(Enum):
    """User account status for migration"""
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"
    PENDING = "PENDING"


def upgrade():
    """Consolidated upgrade - create all tables and columns in one operation"""
    
    # 1. Handle streams table cot_type_mode column
    if table_exists("streams"):
        # Table exists, add cot_type_mode column if it doesn't exist
        if not column_exists("streams", "cot_type_mode"):
            with op.batch_alter_table("streams", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column("cot_type_mode", sa.String(length=20), nullable=True)
                )
            
            # Set default value for existing rows
            op.execute(
                "UPDATE streams SET cot_type_mode = 'stream' WHERE cot_type_mode IS NULL"
            )
            
            # Make the column non-nullable
            with op.batch_alter_table("streams", schema=None) as batch_op:
                batch_op.alter_column("cot_type_mode", nullable=False)
        else:
            print("Column 'cot_type_mode' already exists in streams table")
    else:
        print("WARNING: Table 'streams' does not exist. Skipping cot_type_mode column addition.")

    # 2. Create users table if it doesn't exist
    if not table_exists("users"):
        # Get appropriate enum column type for the database dialect
        auth_provider_column = get_enum_column("auth_provider", AuthProvider, "LOCAL")
        user_role_column = get_enum_column("role", UserRole, "USER") 
        account_status_column = get_enum_column("status", AccountStatus, "ACTIVE")
        
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("full_name", sa.String(length=255), nullable=True),
            auth_provider_column,
            sa.Column("provider_user_id", sa.String(length=255), nullable=True),
            sa.Column("provider_metadata", sa.Text(), nullable=True),
            sa.Column("password_hash", sa.String(length=255), nullable=True),
            user_role_column,
            account_status_column,
            sa.Column("last_login", sa.DateTime(), nullable=True),
            sa.Column("failed_login_attempts", sa.Integer(), nullable=True),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("password_changed_at", sa.DateTime(), nullable=True),
            sa.Column("timezone", sa.String(length=50), nullable=True),
            sa.Column("language", sa.String(length=10), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id")
        )
        
        # Create indexes
        safe_create_index("ix_users_username", "users", ["username"], unique=True)
        safe_create_index("ix_users_email", "users", ["email"], unique=True)
        safe_create_index("ix_users_provider_user_id", "users", ["provider_user_id"], unique=False)
        
        # Add check constraints for PostgreSQL
        if get_dialect() == "postgresql":
            add_enum_check_constraint("users", "auth_provider", AuthProvider)
            add_enum_check_constraint("users", "role", UserRole)
            add_enum_check_constraint("users", "status", AccountStatus)
            
        print("Created users table with all columns and constraints")
    else:
        print("Table 'users' already exists")

    # 3. Create user_sessions table if it doesn't exist
    if not table_exists("user_sessions"):
        # Get appropriate enum column type for auth provider
        session_auth_provider_column = get_enum_column("provider", AuthProvider, "LOCAL")
        
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.String(length=255), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            session_auth_provider_column,
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("provider_session_data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id")
        )
        
        # Create indexes
        safe_create_index("ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True)
        
        # Add check constraint for PostgreSQL
        if get_dialect() == "postgresql":
            add_enum_check_constraint("user_sessions", "provider", AuthProvider)
            
        print("Created user_sessions table with timezone support and provider field")
    else:
        # Table exists, check if we need to add missing columns
        needs_provider = not column_exists("user_sessions", "provider")
        needs_timezone_fix = False
        
        if needs_provider:
            print("Adding provider column to existing user_sessions table")
            provider_column = get_enum_column("provider", AuthProvider, "LOCAL", nullable=True)
            
            with op.batch_alter_table("user_sessions", schema=None) as batch_op:
                # Add the provider column
                if get_dialect() == "postgresql":
                    batch_op.add_column(sa.Column("provider", sa.String(length=10), nullable=True))
                else:
                    batch_op.add_column(provider_column)
            
            # Set default values for existing sessions
            safe_execute("UPDATE user_sessions SET provider = 'LOCAL' WHERE provider IS NULL")
            
            # Add check constraint for PostgreSQL
            if get_dialect() == "postgresql":
                add_enum_check_constraint("user_sessions", "provider", AuthProvider)
        
        # Check if timezone support needs to be added to datetime columns
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = {col["name"]: col for col in inspector.get_columns("user_sessions")}
        
        # Check if expires_at and last_activity have timezone support
        expires_at_col = columns.get("expires_at")
        last_activity_col = columns.get("last_activity")
        
        if expires_at_col and not getattr(expires_at_col["type"], "timezone", False):
            needs_timezone_fix = True
        if last_activity_col and not getattr(last_activity_col["type"], "timezone", False):
            needs_timezone_fix = True
            
        if needs_timezone_fix:
            print("Adding timezone support to user_sessions datetime columns")
            
            # Create new table with timezone support
            temp_table_name = "user_sessions_new"
            session_auth_provider_column = get_enum_column("provider", AuthProvider, "LOCAL")
            
            op.create_table(
                temp_table_name,
                sa.Column("id", sa.Integer(), nullable=False),
                sa.Column("session_id", sa.String(length=255), nullable=False),
                sa.Column("user_id", sa.Integer(), nullable=False),
                sa.Column("ip_address", sa.String(length=45), nullable=True),
                sa.Column("user_agent", sa.Text(), nullable=True),
                session_auth_provider_column,
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False),
                sa.Column("is_active", sa.Boolean(), nullable=True),
                sa.Column("provider_session_data", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
                sa.PrimaryKeyConstraint("id")
            )
            
            # Copy data with timezone conversion
            copy_sql = f"""
                INSERT INTO {temp_table_name} 
                (id, session_id, user_id, ip_address, user_agent, provider, expires_at, last_activity, is_active, provider_session_data, created_at, updated_at)
                SELECT 
                    id, session_id, user_id, ip_address, user_agent, 
                    COALESCE(provider, 'LOCAL') as provider,
                    expires_at, last_activity, is_active, provider_session_data, created_at, updated_at
                FROM user_sessions
            """
            safe_execute(copy_sql)
            
            # Drop old table and rename new one
            op.drop_table("user_sessions")
            op.rename_table(temp_table_name, "user_sessions")
            
            # Recreate indexes
            safe_create_index("ix_user_sessions_session_id", "user_sessions", ["session_id"], unique=True)
            
            # Add check constraint for PostgreSQL
            if get_dialect() == "postgresql":
                add_enum_check_constraint("user_sessions", "provider", AuthProvider)
                
            print("Successfully updated user_sessions with timezone support")

    print("Consolidated migration completed successfully")


def downgrade():
    """Consolidated downgrade - remove all changes"""
    
    # Drop user_sessions table
    if table_exists("user_sessions"):
        op.drop_table("user_sessions")
        
    # Drop users table  
    if table_exists("users"):
        op.drop_table("users")
        
    # Remove cot_type_mode column from streams table
    if table_exists("streams") and column_exists("streams", "cot_type_mode"):
        with op.batch_alter_table("streams", schema=None) as batch_op:
            batch_op.drop_column("cot_type_mode")
            
    print("Consolidated migration downgrade completed")