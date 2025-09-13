"""Add cot_type_mode column to streams table

Revision ID: e2f64ceef0b8
Revises: 
Create Date: 2025-07-19 18:39:34.629492

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2f64ceef0b8"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists to avoid duplicate column error
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("streams")]

    if "cot_type_mode" not in columns:
        with op.batch_alter_table("streams", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("cot_type_mode", sa.String(length=20), nullable=True)
            )

        # Set default value for existing rows
        op.execute(
            sa.text(
                "UPDATE streams SET cot_type_mode = 'stream' WHERE cot_type_mode IS NULL"
            )
        )

        # (Optional) Make the column non-nullable
        with op.batch_alter_table("streams", schema=None) as batch_op:
            batch_op.alter_column("cot_type_mode", nullable=False)
    else:
        # Column already exists, just ensure it has the correct default values
        op.execute(
            sa.text(
                "UPDATE streams SET cot_type_mode = 'stream' WHERE cot_type_mode IS NULL"
            )
        )


def downgrade():
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.drop_column("cot_type_mode")

    # ### end Alembic commands ###
