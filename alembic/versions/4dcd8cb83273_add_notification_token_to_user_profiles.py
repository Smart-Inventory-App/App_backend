"""Add notification_token to user_profiles

Revision ID: 4dcd8cb83273
Revises: 8fda202eb790
Create Date: 2026-08-22 19:09:08.975726

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4dcd8cb83273'
down_revision: Union[str, None] = '8fda202eb790'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_profiles', sa.Column('notification_token', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_profiles', 'notification_token')
