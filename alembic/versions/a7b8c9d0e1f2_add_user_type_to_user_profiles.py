"""add user_type to user_profiles

Revision ID: a7b8c9d0e1f2
Revises: e7e5343374fc
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "e7e5343374fc"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_profiles",
        sa.Column("user_type", sa.String(), nullable=True),
    )
    op.execute("UPDATE user_profiles SET user_type = 'individuo' WHERE user_type IS NULL")


def downgrade():
    op.drop_column("user_profiles", "user_type")
