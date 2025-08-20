"""Merge migration heads - unify consolidated and sequential migrations

Revision ID: merge_heads_migration
Revises: add_timezone_to_user_sessions, consolidated_initial_migration
Create Date: 2025-08-13 01:30:00.000000

This merge migration resolves the multiple heads issue by combining:
1. The original sequential migration chain ending at add_timezone_to_user_sessions
2. The new consolidated_initial_migration

This allows existing deployments to continue using their current migration state
while new deployments can use the faster consolidated migration path.
No actual database operations are performed - this just unifies the migration graph.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "merge_heads_migration"
down_revision = ("add_timezone_to_user_sessions", "consolidated_initial_migration")
branch_labels = None
depends_on = None


def upgrade():
    """
    Merge migration - no operations needed.

    This migration serves only to merge the two migration heads:
    - Sequential migrations: e2f64ceef0b8 -> 0a9c5469abc6 -> 3120f5bf60a4 -> add_timezone_to_user_sessions
    - Consolidated migration: consolidated_initial_migration

    Both paths result in the same database state, so no additional operations are required.
    """
    print("Merge migration: Unifying sequential and consolidated migration heads")
    print("No database operations required - both paths achieve the same end state")


def downgrade():
    """
    Merge migration downgrade - no operations needed.

    Downgrading from this merge will return to having multiple heads,
    which is the expected behavior.
    """
    print("Merge migration downgrade: Returning to multiple heads state")
