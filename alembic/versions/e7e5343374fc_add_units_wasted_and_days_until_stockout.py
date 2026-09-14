"""add units_wasted and days_until_stockout to alerts

Revision ID: e7e5343374fc
Revises: 8fda202eb790
Create Date: 2026-09-10 19:37:06.606161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7e5343374fc'
down_revision: Union[str, None] = '8fda202eb790'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('units_wasted', sa.Integer(), nullable=True))
    op.add_column('alerts', sa.Column('days_until_stockout', sa.Integer(), nullable=True))

def downgrade() -> None:
    op.drop_column('alerts', 'units_wasted')
    op.drop_column('alerts', 'days_until_stockout')
