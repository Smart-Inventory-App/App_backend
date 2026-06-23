"""Add auth_users table

Revision ID: d3e3f4a5b6c7
Revises: c2d3e4f5a6b7
Create Date: 2026-06-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e3f4a5b6c7"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "auth_users", ["email"], unique=True)
    op.create_index("ix_users_id", "auth_users", ["id"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_users_id", table_name="auth_users")
    op.drop_index("ix_users_email", table_name="auth_users")
    op.drop_table("auth_users")