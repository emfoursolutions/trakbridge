"""Add cot_type_mode column to streams table

Revision ID: e2f64ceef0b8
Revises: 
Create Date: 2025-07-19 18:39:34.629492

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e2f64ceef0b8"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("cot_type_mode", sa.String(length=20), nullable=True)
        )

    # Set default value for existing rows
    op.execute(
        "UPDATE streams SET cot_type_mode = 'stream' WHERE cot_type_mode IS NULL"
    )

    # (Optional) Make the column non-nullable
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.alter_column("cot_type_mode", nullable=False)


def downgrade():
    with op.batch_alter_table("streams", schema=None) as batch_op:
        batch_op.drop_column("cot_type_mode")

    # ### end Alembic commands ###
