"""Add last_categoria/last_ubicacion defaults to user_profiles

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-20 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("last_categoria", sa.String(), nullable=True))
    op.add_column("user_profiles", sa.Column("last_ubicacion", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "last_ubicacion")
    op.drop_column("user_profiles", "last_categoria")
