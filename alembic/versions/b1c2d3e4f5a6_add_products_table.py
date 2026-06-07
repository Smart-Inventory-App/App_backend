"""Add products table

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-06-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("marca", sa.String(), nullable=True),
        sa.Column("categoria", sa.String(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("vencimiento", sa.Date(), nullable=True),
        sa.Column("descripcion", sa.String(), nullable=True),
        sa.Column("imagen_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_id", "products", ["id"], unique=False)
    op.create_index("ix_products_user_id", "products", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_products_user_id", table_name="products")
    op.drop_index("ix_products_id", table_name="products")
    op.drop_table("products")
