"""
Migration utilities for safe database operations.
Provides helper functions to check existence of tables, columns, and indexes
before attempting to create, alter, or drop them.
"""

import sqlalchemy as sa
from alembic import op


def get_dialect():
    """Get the current database dialect name."""
    conn = op.get_bind()
    return conn.dialect.name


def get_enum_column(enum_class, column_name, nullable=True, default=None):
    """
    Get database-appropriate enum column definition.

    Safely handles both proper Python Enum classes with .value attributes
    and legacy string-based enum definitions used in migrations.

    Args:
        enum_class: Python Enum class or enum-like class
        column_name: Column name
        nullable: Whether column is nullable
        default: Default value

    Returns:
        SQLAlchemy Column object appropriate for the database
    """
    dialect = get_dialect()

    # Safely extract enum values - handle both .value and direct string access
    try:
        # Try proper Enum with .value attribute first (modern approach)
        enum_values = [member.value for member in enum_class]
        # Test if this actually works by accessing the first value
        if enum_values:
            _ = enum_values[0]  # This will fail if .value doesn't exist
    except (AttributeError, IndexError):
        # Fallback to direct string access for legacy enum definitions
        enum_values = [str(member) for member in enum_class]

    if dialect == "postgresql":
        # PostgreSQL supports native ENUMs
        return sa.Column(
            column_name,
            sa.Enum(*enum_values, name=f"{column_name}_enum"),
            nullable=nullable,
            default=default,
        )
    else:
        # MySQL and SQLite use VARCHAR with CHECK constraints
        max_length = max(len(value) for value in enum_values)
        return sa.Column(
            column_name,
            sa.String(length=max_length),
            nullable=nullable,
            default=default.value if hasattr(default, "value") else default,
        )


def get_datetime_column(column_name, nullable=True, default=None, timezone_aware=False):
    """
    Get database-appropriate datetime column definition.

    Args:
        column_name: Column name
        nullable: Whether column is nullable
        default: Default value
        timezone_aware: Whether to store timezone information

    Returns:
        SQLAlchemy Column object appropriate for the database
    """
    dialect = get_dialect()

    if dialect == "postgresql" and timezone_aware:
        # PostgreSQL supports TIMESTAMP WITH TIME ZONE
        return sa.Column(
            column_name, sa.DateTime(timezone=True), nullable=nullable, default=default
        )
    elif dialect == "mysql" and timezone_aware:
        # MySQL TIMESTAMP is timezone-aware by default
        return sa.Column(column_name, sa.TIMESTAMP, nullable=nullable, default=default)
    elif timezone_aware:
        # SQLite - store as TEXT with timezone suffix
        return sa.Column(column_name, sa.Text, nullable=nullable, default=default)
    else:
        # Standard datetime without timezone
        return sa.Column(column_name, sa.DateTime, nullable=nullable, default=default)


def get_boolean_column(column_name, nullable=True, default=None):
    """
    Get database-appropriate boolean column definition.

    Args:
        column_name: Column name
        nullable: Whether column is nullable
        default: Default value (True/False)

    Returns:
        SQLAlchemy Column object appropriate for the database
    """
    dialect = get_dialect()

    if dialect == "sqlite":
        # SQLite uses INTEGER for boolean
        return sa.Column(column_name, sa.Boolean, nullable=nullable, default=default)
    else:
        # PostgreSQL and MySQL support native BOOLEAN
        return sa.Column(column_name, sa.Boolean, nullable=nullable, default=default)


def add_enum_check_constraint(table_name, column_name, enum_class):
    """
    Add CHECK constraint for enum values on MySQL/SQLite.

    Args:
        table_name: Table name
        column_name: Column name
        enum_class: Python Enum class
    """
    dialect = get_dialect()

    if dialect != "postgresql":
        enum_values = [f"'{member.value}'" for member in enum_class]
        constraint_name = f"check_{table_name}_{column_name}_values"

        safe_execute(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} "
            f"CHECK ({column_name} IN ({', '.join(enum_values)}))",
            f"Add CHECK constraint for {column_name} enum values",
        )


def drop_enum_check_constraint(table_name, column_name):
    """
    Drop CHECK constraint for enum values on MySQL/SQLite.

    Args:
        table_name: Table name
        column_name: Column name
    """
    dialect = get_dialect()

    if dialect != "postgresql":
        constraint_name = f"check_{table_name}_{column_name}_values"
        safe_execute(
            f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}",
            f"Drop CHECK constraint for {column_name} enum values",
        )


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    if not table_exists(table_name):
        return False

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(index_name: str) -> bool:
    """Check if an index exists in the database."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Get all indexes from all tables
    all_indexes = []
    for table_name in inspector.get_table_names():
        indexes = inspector.get_indexes(table_name)
        all_indexes.extend([idx["name"] for idx in indexes if idx["name"]])

    return index_name in all_indexes


def foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a foreign key constraint exists."""
    if not table_exists(table_name):
        return False

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    foreign_keys = inspector.get_foreign_keys(table_name)
    return constraint_name in [fk["name"] for fk in foreign_keys if fk["name"]]


def safe_add_column(table_name: str, column_name: str, column_def, **kwargs):
    """Safely add a column to a table if it doesn't already exist."""
    if not table_exists(table_name):
        print(f"WARNING: Table '{table_name}' does not exist. Cannot add column '{column_name}'.")
        return False

    if column_exists(table_name, column_name):
        print(
            f"Column '{column_name}' already exists in table '{table_name}'. Skipping add_column."
        )
        return False

    with op.batch_alter_table(table_name, **kwargs) as batch_op:
        batch_op.add_column(column_def)
    print(f"Successfully added column '{column_name}' to table '{table_name}'.")
    return True


def safe_drop_column(table_name: str, column_name: str, **kwargs):
    """Safely drop a column from a table if it exists."""
    if not table_exists(table_name):
        print(f"WARNING: Table '{table_name}' does not exist. Cannot drop column '{column_name}'.")
        return False

    if not column_exists(table_name, column_name):
        print(
            f"Column '{column_name}' does not exist in table '{table_name}'. Skipping drop_column."
        )
        return False

    with op.batch_alter_table(table_name, **kwargs) as batch_op:
        batch_op.drop_column(column_name)
    print(f"Successfully dropped column '{column_name}' from table '{table_name}'.")
    return True


def safe_alter_column(table_name: str, column_name: str, **kwargs):
    """Safely alter a column if the table and column exist."""
    if not table_exists(table_name):
        print(f"WARNING: Table '{table_name}' does not exist. Cannot alter column '{column_name}'.")
        return False

    if not column_exists(table_name, column_name):
        print(
            f"WARNING: Column '{column_name}' does not exist in table '{table_name}'. Cannot alter column."
        )
        return False

    batch_kwargs = {k: v for k, v in kwargs.items() if k in ["schema"]}
    alter_kwargs = {k: v for k, v in kwargs.items() if k not in ["schema"]}

    with op.batch_alter_table(table_name, **batch_kwargs) as batch_op:
        batch_op.alter_column(column_name, **alter_kwargs)
    print(f"Successfully altered column '{column_name}' in table '{table_name}'.")
    return True


def safe_create_table(table_name: str, *columns, **kwargs):
    """Safely create a table if it doesn't already exist."""
    if table_exists(table_name):
        print(f"Table '{table_name}' already exists. Skipping create_table.")
        return False

    op.create_table(table_name, *columns, **kwargs)
    print(f"Successfully created table '{table_name}'.")
    return True


def safe_drop_table(table_name: str):
    """Safely drop a table if it exists."""
    if not table_exists(table_name):
        print(f"Table '{table_name}' does not exist. Skipping drop_table.")
        return False

    op.drop_table(table_name)
    print(f"Successfully dropped table '{table_name}'.")
    return True


def safe_create_index(index_name: str, table_name: str, columns: list, **kwargs):
    """Safely create an index if it doesn't already exist."""
    if not table_exists(table_name):
        print(f"WARNING: Table '{table_name}' does not exist. Cannot create index '{index_name}'.")
        return False

    if index_exists(index_name):
        print(f"Index '{index_name}' already exists. Skipping create_index.")
        return False

    op.create_index(index_name, table_name, columns, **kwargs)
    print(f"Successfully created index '{index_name}' on table '{table_name}'.")
    return True


def safe_drop_index(index_name: str, table_name: str = None):
    """Safely drop an index if it exists."""
    if not index_exists(index_name):
        print(f"Index '{index_name}' does not exist. Skipping drop_index.")
        return False

    op.drop_index(index_name, table_name=table_name)
    print(f"Successfully dropped index '{index_name}'.")
    return True


def safe_execute(sql: str, description: str = "SQL operation"):
    """Safely execute SQL with error handling and logging."""
    try:
        op.execute(sa.text(sql))
        print(f"Successfully executed: {description}")
        return True
    except Exception as e:
        print(f"Failed to execute {description}: {e}")
        return False
