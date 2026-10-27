"""El arranque agrega las columnas nuevas que le faltan a una base anterior, sin romper una que ya las tiene."""
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.alerts import alerts_of_user
from app.core import schema_guard
from app.core.database import Base
from app.core.schema_guard import ensure_columns


def new_engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def columns(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


@pytest.fixture
def old_database():
    """Una base como la que quedó antes de la migración: la tabla de alertas sin `suggested_qty`."""
    engine = new_engine()
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE alerts DROP COLUMN suggested_qty"))
    return engine


def test_without_the_column_reading_the_alerts_fails(old_database):
    db = sessionmaker(bind=old_database)()
    with pytest.raises(Exception, match="suggested_qty"):
        alerts_of_user(db, str(uuid.uuid4()))


def test_it_adds_the_missing_column_and_the_alerts_can_be_read_again(old_database):
    assert ensure_columns(old_database) == ["alerts.suggested_qty"]

    assert "suggested_qty" in columns(old_database, "alerts")
    assert alerts_of_user(sessionmaker(bind=old_database)(), str(uuid.uuid4())) == []


def test_it_does_nothing_when_the_column_is_already_there():
    engine = new_engine()
    Base.metadata.create_all(bind=engine)

    assert ensure_columns(engine) == []
    assert ensure_columns(engine) == []


def test_running_it_twice_only_adds_the_column_once(old_database):
    assert ensure_columns(old_database) == ["alerts.suggested_qty"]
    assert ensure_columns(old_database) == []


def test_a_table_that_does_not_exist_yet_is_left_to_create_all():
    assert ensure_columns(new_engine()) == []


def test_it_keeps_the_alerts_that_were_already_saved(old_database):
    with old_database.begin() as connection:
        connection.execute(text(
            "INSERT INTO alerts (user_id, product_id, type, level) VALUES (:u, 1, 'expiry', 'warning')"
        ), {"u": "1" * 32})

    ensure_columns(old_database)

    with old_database.connect() as connection:
        row = connection.execute(text("SELECT type, level, suggested_qty FROM alerts")).one()
    assert tuple(row) == ("expiry", "warning", None)


def test_the_list_covers_the_column_the_alerts_need():
    assert ("alerts", "suggested_qty", "INTEGER") in schema_guard.REQUIRED_COLUMNS
