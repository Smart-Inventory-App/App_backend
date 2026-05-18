"""Add password_recovery_codes table

Revision ID: a1b2c3d4e5f6
Revises: d363a82a2827
Create Date: 2026-05-17 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d363a82a2827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_recovery_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_password_recovery_codes_email", "password_recovery_codes", ["email"])
    op.create_index("ix_password_recovery_codes_id", "password_recovery_codes", ["id"])


def downgrade() -> None:
    op.drop_index("ix_password_recovery_codes_id", table_name="password_recovery_codes")
    op.drop_index("ix_password_recovery_codes_email", table_name="password_recovery_codes")
    op.drop_table("password_recovery_codes")
