"""Add config_version field to streams table for Redis worker coordination

Revision ID: consolidated_config_version_migration
Revises: f085153337e8
Create Date: 2025-09-19 04:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

# revision identifiers, used by Alembic.
revision = 'consolidated_config_version_migration'
down_revision = 'f085153337e8'
branch_labels = None
depends_on = None


def upgrade():
    """Add config_version column to streams table for multi-worker coordination

    This consolidated migration replaces multiple conflicting migrations that
    attempted to add the same field. It handles the addition safely with proper
    defaults and null handling across SQLite, PostgreSQL, and MariaDB.
    """
    # Check if the column already exists (for databases that applied earlier versions)
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Get database dialect for database-specific handling
    dialect_name = connection.dialect.name.lower()

    # Check for existing columns (case-insensitive for compatibility)
    columns = [col['name'].lower() for col in inspector.get_columns('streams')]

    if 'config_version' not in columns:
        # Add the config_version column with timezone-aware datetime
        # Use TIMESTAMP for PostgreSQL/MariaDB for better timezone support
        if dialect_name == 'postgresql':
            column_type = sa.TIMESTAMP(timezone=True)
        elif dialect_name in ['mysql', 'mariadb']:
            # MariaDB 11+ supports TIMESTAMP(6) for microseconds
            column_type = sa.TIMESTAMP()
        else:
            # SQLite fallback
            column_type = sa.DateTime()

        op.add_column('streams', sa.Column('config_version', column_type, nullable=True))

        # Update existing records with database-specific current timestamp function
        if dialect_name == 'postgresql':
            # PostgreSQL: Use NOW() with timezone
            update_sql = "UPDATE streams SET config_version = NOW() WHERE config_version IS NULL"
        elif dialect_name in ['mysql', 'mariadb']:
            # MariaDB 11: Use NOW() function
            update_sql = "UPDATE streams SET config_version = NOW() WHERE config_version IS NULL"
        else:
            # SQLite: Use parameterized query with Python datetime
            current_time = datetime.now(timezone.utc)
            connection.execute(
                sa.text("UPDATE streams SET config_version = :current_time WHERE config_version IS NULL"),
                {"current_time": current_time}
            )
            update_sql = None

        if update_sql:
            connection.execute(sa.text(update_sql))
    else:
        # Column exists, ensure any NULL values are updated with database-specific functions
        if dialect_name == 'postgresql':
            update_sql = "UPDATE streams SET config_version = NOW() WHERE config_version IS NULL"
        elif dialect_name in ['mysql', 'mariadb']:
            update_sql = "UPDATE streams SET config_version = NOW() WHERE config_version IS NULL"
        else:
            # SQLite fallback with Python datetime
            current_time = datetime.now(timezone.utc)
            connection.execute(
                sa.text("UPDATE streams SET config_version = :current_time WHERE config_version IS NULL"),
                {"current_time": current_time}
            )
            update_sql = None

        if update_sql:
            connection.execute(sa.text(update_sql))

    # Handle any callsign mapping index cleanup that was part of the conflicting migrations
    # Use database-specific index handling
    try:
        # Check if callsign_mappings table exists
        table_names = [table.lower() for table in inspector.get_table_names()]
        if 'callsign_mappings' in table_names:
            existing_indexes = [idx['name'] for idx in inspector.get_indexes('callsign_mappings')]

            # Drop specific indexes if they exist (database-agnostic approach)
            indexes_to_drop = ['ix_callsign_mappings_enabled', 'ix_callsign_mappings_stream_enabled']

            for index_name in indexes_to_drop:
                if index_name in existing_indexes:
                    try:
                        if dialect_name == 'sqlite':
                            # SQLite requires batch operations for index drops
                            with op.batch_alter_table('callsign_mappings', schema=None) as batch_op:
                                batch_op.drop_index(index_name)
                        else:
                            # PostgreSQL and MariaDB can drop indexes directly
                            op.drop_index(index_name, table_name='callsign_mappings')
                    except Exception as e:
                        # Continue if index doesn't exist or can't be dropped
                        pass
    except Exception:
        # Continue if table inspection fails
        pass


def downgrade():
    """Remove config_version column from streams table"""
    # Get database dialect for database-specific handling
    connection = op.get_bind()
    dialect_name = connection.dialect.name.lower()
    inspector = sa.inspect(connection)

    # Restore any indexes we may have dropped (database-specific approach)
    try:
        table_names = [table.lower() for table in inspector.get_table_names()]
        if 'callsign_mappings' in table_names:
            existing_indexes = [idx['name'] for idx in inspector.get_indexes('callsign_mappings')]

            # Create indexes that may have been dropped
            indexes_to_create = [
                ('ix_callsign_mappings_stream_enabled', ['stream_id', 'enabled']),
                ('ix_callsign_mappings_enabled', ['enabled'])
            ]

            for index_name, columns in indexes_to_create:
                if index_name not in existing_indexes:
                    try:
                        if dialect_name == 'sqlite':
                            # SQLite requires batch operations for index creation
                            with op.batch_alter_table('callsign_mappings', schema=None) as batch_op:
                                batch_op.create_index(index_name, columns, unique=False)
                        else:
                            # PostgreSQL and MariaDB can create indexes directly
                            op.create_index(index_name, 'callsign_mappings', columns, unique=False)
                    except Exception:
                        # Continue if index can't be created
                        pass
    except Exception:
        # Continue if table inspection fails
        pass

    # Remove the config_version column (database-agnostic)
    if dialect_name == 'sqlite':
        # SQLite requires batch operations for column drops
        with op.batch_alter_table('streams', schema=None) as batch_op:
            batch_op.drop_column('config_version')
    else:
        # PostgreSQL and MariaDB can drop columns directly
        op.drop_column('streams', 'config_version')