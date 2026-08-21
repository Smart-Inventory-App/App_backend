"""Add stock_minimo/dias_alerta_vencimiento rules to user_profiles

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-08-21 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2b3c4d5e6f70"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("stock_minimo", sa.Integer(), nullable=True))
    op.add_column("user_profiles", sa.Column("dias_alerta_vencimiento", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "dias_alerta_vencimiento")
    op.drop_column("user_profiles", "stock_minimo")
