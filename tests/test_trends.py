"""`GET /trends/`: consumo agregado por día y ranking de productos, en UTC."""
from datetime import datetime, time, timedelta, timezone

import pytest

from app.api.trends import _utc_day
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}
OTHER_USER_ID = "22222222-2222-4222-8222-222222222222"


def today_utc():
    return datetime.now(timezone.utc).date()


def at(day, hour=12):
    """Instante de un día UTC (naive, como lo devuelve SQLite)."""
    return datetime.combine(day, time(hour=hour))


def make_product(db, nombre="Leche", user_id=TEST_USER_ID):
    product = Product(user_id=user_id, nombre=nombre, categoria="General", stock=10)
    db.add(product)
    db.commit()
    return product


def add_event(db, product, quantity, day, event_type="consumed", user_id=TEST_USER_ID, **extra):
    event = ConsumptionEvent(
        product_id=product.id, user_id=user_id, quantity=quantity,
        event_type=event_type, consumed_at=at(day), **extra,
    )
    db.add(event)
    db.commit()
    return event


def get_trends(client, **params):
    return client.get("/trends/", params=params, headers=AUTH)


def test_an_empty_history_returns_zeroes_and_one_point_per_day(client, db):
    resp = get_trends(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["period_days"] == 30
    assert body["total_consumido"] == 0
    assert body["total_entradas"] == 0
    assert len(body["consumo_por_dia"]) == 30
    assert all(d["quantity"] == 0 for d in body["consumo_por_dia"])
    assert body["top_productos"] == []
    assert body["productos_menos_usados"] == []


def test_the_series_is_ordered_oldest_first_and_ends_today(client, db):
    resp = get_trends(client, period=7)

    days = [d["day"] for d in resp.json()["consumo_por_dia"]]
    assert len(days) == 7
    assert days == sorted(days)
    assert days[-1] == today_utc().isoformat()
    assert days[0] == (today_utc() - timedelta(days=6)).isoformat()


@pytest.mark.parametrize("period", [0, 366, -1])
def test_a_period_out_of_range_is_rejected(client, db, period):
    assert get_trends(client, period=period).status_code == 422


def test_consumption_is_added_up_per_day_and_in_total(client, db):
    leche = make_product(db)
    add_event(db, leche, 2, today_utc())
    add_event(db, leche, 3, today_utc())
    add_event(db, leche, 4, today_utc() - timedelta(days=2))

    body = get_trends(client, period=7).json()

    assert body["total_consumido"] == 9
    per_day = {d["day"]: d["quantity"] for d in body["consumo_por_dia"]}
    assert per_day[today_utc().isoformat()] == 5
    assert per_day[(today_utc() - timedelta(days=2)).isoformat()] == 4


def test_restocks_count_as_entries_and_not_as_consumption(client, db):
    leche = make_product(db)
    add_event(db, leche, 5, today_utc(), event_type="consumed")
    add_event(db, leche, 20, today_utc(), event_type="restocked")

    body = get_trends(client).json()

    assert body["total_consumido"] == 5
    assert body["total_entradas"] == 20
    assert sum(d["quantity"] for d in body["consumo_por_dia"]) == 5


def test_expired_events_are_in_neither_total(client, db):
    leche = make_product(db)
    add_event(db, leche, 4, today_utc(), event_type="expired")

    body = get_trends(client).json()

    assert body["total_consumido"] == 0
    assert body["total_entradas"] == 0
    assert body["top_productos"] == []


def test_a_reversed_event_and_its_reversal_are_both_left_out(client, db):
    leche = make_product(db)
    add_event(db, leche, 7, today_utc())
    wrong = add_event(db, leche, 9, today_utc())
    add_event(db, leche, 9, today_utc(), event_type="restocked", reverses_event_id=wrong.id)

    body = get_trends(client).json()

    assert body["total_consumido"] == 7
    assert body["total_entradas"] == 0


def test_events_outside_the_window_are_ignored(client, db):
    leche = make_product(db)
    add_event(db, leche, 5, today_utc() - timedelta(days=10))

    assert get_trends(client, period=7).json()["total_consumido"] == 0
    assert get_trends(client, period=30).json()["total_consumido"] == 5


def test_the_first_instant_of_the_window_is_in_and_the_one_before_is_out(client, db):
    leche = make_product(db)
    first_day = today_utc() - timedelta(days=6)
    db.add_all([
        ConsumptionEvent(product_id=leche.id, user_id=TEST_USER_ID, quantity=3,
                         consumed_at=datetime.combine(first_day, time.min)),
        ConsumptionEvent(product_id=leche.id, user_id=TEST_USER_ID, quantity=100,
                         consumed_at=datetime.combine(first_day, time.min) - timedelta(seconds=1)),
    ])
    db.commit()

    assert get_trends(client, period=7).json()["total_consumido"] == 3


def test_other_users_events_are_not_counted(client, db):
    ajena = make_product(db, "Ajena", user_id=OTHER_USER_ID)
    add_event(db, ajena, 50, today_utc(), user_id=OTHER_USER_ID)

    body = get_trends(client).json()

    assert body["total_consumido"] == 0
    assert body["top_productos"] == []


def test_the_ranking_is_ordered_by_quantity_descending(client, db):
    for nombre, qty in [("A", 1), ("B", 5), ("C", 3)]:
        add_event(db, make_product(db, nombre), qty, today_utc())

    body = get_trends(client).json()

    assert [(p["nombre"], p["cantidad"]) for p in body["top_productos"]] == [("B", 5), ("C", 3), ("A", 1)]
    assert body["productos_menos_usados"] == []  # con 5 o menos no hay "menos usados"


def test_with_more_than_five_products_the_top_and_the_least_used_are_split(client, db):
    for i in range(1, 8):
        add_event(db, make_product(db, f"P{i}"), i, today_utc())

    body = get_trends(client).json()

    assert [p["cantidad"] for p in body["top_productos"]] == [7, 6, 5, 4, 3]
    assert [p["cantidad"] for p in body["productos_menos_usados"]] == [1, 2, 3, 4, 5]


def test_a_deleted_product_is_shown_with_a_placeholder_name(client, db):
    leche = make_product(db)
    add_event(db, leche, 4, today_utc())
    product_id = leche.id
    db.query(Product).filter(Product.id == product_id).delete()
    db.commit()

    body = get_trends(client).json()

    assert body["top_productos"][0]["nombre"] == f"Producto #{product_id}"


def test_trends_require_a_token(client, db):
    from app.main import app
    from app.core.security import get_current_user

    override = app.dependency_overrides.pop(get_current_user)
    try:
        assert client.get("/trends/").status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = override


# ── el día se calcula siempre en UTC ──────────────────────────────────────────

def test_an_aware_instant_is_assigned_to_its_utc_day():
    argentina = timezone(timedelta(hours=-3))
    late_evening = datetime(2026, 10, 12, 23, 30, tzinfo=argentina)  # 02:30 UTC del 13

    assert _utc_day(late_evening).isoformat() == "2026-10-13"


def test_a_naive_instant_is_taken_as_utc():
    assert _utc_day(datetime(2026, 10, 12, 23, 30)).isoformat() == "2026-10-12"
