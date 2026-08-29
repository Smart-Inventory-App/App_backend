"""Add per-product stock_minimo/dias_alerta_vencimiento overrides

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-22 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("stock_minimo", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("dias_alerta_vencimiento", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "dias_alerta_vencimiento")
    op.drop_column("products", "stock_minimo")
