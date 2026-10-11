"""Add codigo_barras to products

El identificador global del producto. Entra por tres caminos —el usuario lo
escribe, el OCR lo decodifica de una foto, o llega en una carga por archivo— y en
los tres se guarda normalizado a 13 dígitos, así que el mismo envase se encuentra
a sí mismo sin importar por dónde entró.

Va indexado y **no** único: dos usuarios distintos pueden tener el mismo producto,
y la unicidad que importa es por usuario. El índice es lo que hace barata la
búsqueda "qué producto tengo con este código", que es la operación central del
alta y de la salida por código de barras.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("codigo_barras", sa.String(length=14), nullable=True))
    op.create_index("ix_products_codigo_barras", "products", ["codigo_barras"])


def downgrade() -> None:
    op.drop_index("ix_products_codigo_barras", table_name="products")
    op.drop_column("products", "codigo_barras")
