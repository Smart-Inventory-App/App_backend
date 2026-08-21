"""Add consumption_events table

Revision ID: 1a2b3c4d5e6f
Revises: f5a6b7c8d9e0
Create Date: 2026-07-25 00:00:00.000000

Nota: esta migración originalmente compartía el revision id "f5a6b7c8d9e0" con
"f5a6b7c8d9e0_add_user_profile_defaults.py" (colisión accidental al elegir el
próximo id a mano). Como esa otra migración ya se había aplicado en la base
compartida y esta no, se le asignó un id nuevo y se la encadenó después.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consumption_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_consumption_events_product_id", "consumption_events", ["product_id"])
    op.create_index("ix_consumption_events_user_id", "consumption_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_consumption_events_user_id", table_name="consumption_events")
    op.drop_index("ix_consumption_events_product_id", table_name="consumption_events")
    op.drop_table("consumption_events")
