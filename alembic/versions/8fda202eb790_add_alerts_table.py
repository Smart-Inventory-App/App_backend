"""Add alerts table

Revision ID: 8fda202eb790
Revises: 2b3c4d5e6f70
Create Date: 2026-08-22 15:40:58.820845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8fda202eb790'
down_revision: Union[str, None] = '2b3c4d5e6f70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
   op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
           "product_id",
           sa.Integer(),
           sa.ForeignKey("products.id", ondelete="CASCADE"),
           nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("critic", sa.Boolean(), nullable=False, default=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
   )
   op.create_index("ix_alerts_user_id", "alerts", ["user_id"])
   op.create_index("ix_alerts_product_id", "alerts", ["product_id"])

def downgrade() -> None:
    op.drop_index("ix_alerts_product_id", table_name="alerts")
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")
