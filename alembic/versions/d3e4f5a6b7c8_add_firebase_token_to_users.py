"""Add firebase_token to auth_users

Revision ID: d3e4f5a6b7c8
Revises: d3e3f4a5b6c7
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "d3e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("auth_users", sa.Column("firebase_token", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_users", "firebase_token")
