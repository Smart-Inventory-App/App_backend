"""Columnas que el código usa y que una base ya creada puede no tener todavía.

`Base.metadata.create_all` crea las tablas que faltan pero nunca agrega columnas a una tabla que ya existe. Si una base
quedó de antes de un cambio de esquema y nadie corrió la migración de Alembic, cada consulta que nombra la columna
nueva falla con un 500. Al arrancar se agregan acá las que faltan, de forma idempotente: si la migración ya se corrió
(o se corre después), no pasa nada.
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (tabla, columna, tipo SQL) de las columnas agregadas después de la versión inicial que la app necesita
REQUIRED_COLUMNS = [
    ("alerts", "suggested_qty", "INTEGER"),
]


def ensure_columns(engine: Engine) -> list[str]:
    """Agrega las columnas de `REQUIRED_COLUMNS` que falten y devuelve las que agregó (`tabla.columna`)."""
    added: list[str] = []
    inspector = inspect(engine)
    for table, column, sql_type in REQUIRED_COLUMNS:
        if not inspector.has_table(table):
            continue  # la tabla se crea completa con create_all
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
        logger.warning("Se agregó la columna %s.%s que faltaba en la base", table, column)
        added.append(f"{table}.{column}")
    return added
