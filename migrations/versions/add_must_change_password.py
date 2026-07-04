"""
ABOUTME: Alembic migration adding must_change_password flag to the user table.
ABOUTME: Enables admin-initiated forced password change without nulling
ABOUTME: password_changed_at.

Add must_change_password flag to users

Revision ID: add_must_change_password
Revises: 54faa293e582
Create Date: 2026-07-03

"""

from alembic import op
import sqlalchemy as sa
from migrations.migration_utils import safe_add_column

# revision identifiers, used by Alembic.
revision = "add_must_change_password"
down_revision = "54faa293e582"
branch_labels = None
depends_on = None


def upgrade():
    """
    Add must_change_password boolean column to the user table.

    Allows admins to force a password change on the user's next login without
    setting password_changed_at to None, which previously caused the password-
    expiry check to treat the account as immediately expired.
    """
    safe_add_column(
        "users",
        "must_change_password",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("must_change_password")
