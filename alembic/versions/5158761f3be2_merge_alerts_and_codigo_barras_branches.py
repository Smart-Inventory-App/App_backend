"""merge alerts and codigo_barras branches

Revision ID: 5158761f3be2
Revises: a7b8c9d0e1f2, e6f7a8b9c0d1
Create Date: 2026-09-27 19:34:36.737966

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5158761f3be2'
down_revision: Union[str, None] = ('a7b8c9d0e1f2', 'e6f7a8b9c0d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
