"""add event_type to consumption_events

Revision ID: a2b3c4d5e6f7
Revises: f5a6b7c8d9e0
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "2b3c4d5e6f70"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "consumption_events",
        sa.Column("event_type", sa.String(), nullable=False, server_default="consumed"),
    )


def downgrade():
    op.drop_column("consumption_events", "event_type")
