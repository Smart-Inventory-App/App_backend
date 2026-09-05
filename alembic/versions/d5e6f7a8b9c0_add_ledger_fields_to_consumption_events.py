"""Add actor_email/note/reverses_event_id to consumption_events (append-only ledger)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-04 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("consumption_events", sa.Column("actor_email", sa.String(), nullable=True))
    op.add_column("consumption_events", sa.Column("note", sa.String(), nullable=True))
    op.add_column(
        "consumption_events",
        sa.Column(
            "reverses_event_id",
            sa.Integer(),
            sa.ForeignKey("consumption_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("consumption_events", "reverses_event_id")
    op.drop_column("consumption_events", "note")
    op.drop_column("consumption_events", "actor_email")
