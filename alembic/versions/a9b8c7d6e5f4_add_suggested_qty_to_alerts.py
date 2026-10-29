"""add suggested_qty to alerts

Revision ID: a9b8c7d6e5f4
Revises: 5158761f3be2
Create Date: 2026-10-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "5158761f3be2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cantidad que sugiere una alerta de reposición. Puede que la columna ya exista: el arranque de la app la agrega
    # si falta (app/core/schema_guard.py)
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("alerts")}
    if "suggested_qty" not in columns:
        op.add_column("alerts", sa.Column("suggested_qty", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "suggested_qty")
