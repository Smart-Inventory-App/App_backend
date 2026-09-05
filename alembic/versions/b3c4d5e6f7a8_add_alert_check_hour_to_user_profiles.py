"""add alert_check_hour to user_profiles

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-26

"""
from alembic import op
import sqlalchemy as sa

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_profiles",
        sa.Column("alert_check_hour", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("user_profiles", "alert_check_hour")
