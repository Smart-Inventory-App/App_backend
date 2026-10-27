"""Endpoints de lectura de alertas (`/alerts/*`).

Primero con alertas sembradas directo en la base (qué devuelve cada endpoint y con qué nivel) y después de punta a
punta: las alertas nacen de editar productos y se leen por la API.

Los niveles no son los que quedaron guardados: se calculan al leer con las reglas vigentes (el límite del producto o,
si no tiene, el del perfil), así la lista, los filtros y el resumen siempre coinciden.
"""
from datetime import date, timedelta
from uuid import UUID

import httpx
from freezegun import freeze_time

from app.models.alert import Alert
from app.models.product import Product
from app.models.profile import UserProfile
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def days_from_now(days):
    return date.today() + timedelta(days=days)


def add_product_with_alert(db, alert_type="expiry", level="warning", expiry_in=3, **alert_overrides):
    """Un producto en un estado coherente con la alerta (un vencimiento cercano, o un stock que se agota)."""
    expiry = {"expiry": expiry_in, "slow_pace": 20}.get(alert_type)
    product = Product(
        user_id=TEST_USER_ID, nombre="Yogur", categoria="Lacteo", stock=5,
        vencimiento=days_from_now(expiry) if expiry is not None else None,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    if alert_type == "stock_low_coverage":
        alert_overrides.setdefault("days_until_stockout", 2)
    if alert_type == "slow_pace":
        alert_overrides.setdefault("units_wasted", 2)
    alert = Alert(user_id=UUID(TEST_USER_ID), product_id=product.id, type=alert_type, level=level, **alert_overrides)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return product, alert


def alerts(client, path="/alerts/"):
    return client.get(path, headers=AUTH).json()


def set_profile(db, **fields):
    db.add(UserProfile(user_id=TEST_USER_ID, **fields))
    db.commit()


# ── qué devuelve cada endpoint ────────────────────────────────────────────────

def test_get_alerts_lists_own_alerts_with_product_info(client, db):
    add_product_with_alert(db)

    body = alerts(client)

    assert len(body) == 1
    assert body[0]["product_name"] == "Yogur"
    assert body[0]["product_stock"] == 5


def test_alerts_include_the_category_and_brand_of_the_product(client, db):
    product, _ = add_product_with_alert(db)
    product.marca = "La Serenisima"
    db.commit()

    body = alerts(client)

    assert body[0]["product_category"] == "Lacteo"
    assert body[0]["product_brand"] == "La Serenisima"


def test_a_product_without_brand_gives_no_brand(client, db):
    add_product_with_alert(db)

    assert alerts(client)[0]["product_brand"] is None


def test_every_alert_endpoint_gives_the_category_and_brand(client, db):
    product, _ = add_product_with_alert(db, alert_type="stock_low_coverage", level="critical")
    product.marca = "Sancor"
    db.commit()

    for path in ("/alerts/", "/alerts/critical_alerts", "/alerts/stock_alerts"):
        item = alerts(client, path)[0]
        assert (item["product_category"], item["product_brand"]) == ("Lacteo", "Sancor")


def test_an_alert_of_a_product_without_stock_is_discarded(client, db):
    product, _ = add_product_with_alert(db)
    product.stock = 0
    db.commit()

    assert alerts(client) == []
    assert db.query(Alert).count() == 0


def test_expiry_alerts_includes_expiry_and_slow_pace_but_not_the_stock_ones(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage")
    add_product_with_alert(db, alert_type="expiry")
    add_product_with_alert(db, alert_type="slow_pace")

    assert sorted(a["type"] for a in alerts(client, "/alerts/expiry_alerts")) == ["expiry", "slow_pace"]


def test_stock_alerts_only_lists_the_minimum_stock_ones(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage")
    add_product_with_alert(db, alert_type="expiry")
    add_product_with_alert(db, alert_type="slow_pace")

    assert [a["type"] for a in alerts(client, "/alerts/stock_alerts")] == ["stock_low_coverage"]


def test_a_stock_alert_carries_the_suggested_quantity(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage", suggested_qty=12)

    item = alerts(client)[0]

    assert item["type"] == "stock_low_coverage"
    assert item["suggested_qty"] == 12


def test_the_old_separate_restock_alerts_are_dropped(client, db):
    add_product_with_alert(db, alert_type="restock", level="info", suggested_qty=12)

    assert alerts(client) == []
    assert db.query(Alert).count() == 0


def test_each_alert_says_if_it_comes_from_a_rule_of_the_user_or_from_the_system(client, db):
    for alert_type in ("expiry", "stock_low_coverage", "slow_pace"):
        add_product_with_alert(db, alert_type=alert_type)

    origins = {a["type"]: a["origin"] for a in alerts(client)}

    assert origins == {"expiry": "rule", "stock_low_coverage": "rule", "slow_pace": "system"}


def test_the_alerts_of_the_rules_of_the_user_come_first_then_the_most_serious(client, db):
    _, slow = add_product_with_alert(db, alert_type="slow_pace")
    _, expiry_warning = add_product_with_alert(db, alert_type="expiry", expiry_in=9)
    _, expiry_critical = add_product_with_alert(db, alert_type="expiry", expiry_in=2)
    _, low = add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=9)

    ids = [a["id"] for a in alerts(client)]

    # primero las de las reglas (críticas antes que advertencias) y después las del sistema
    assert ids[0] == expiry_critical.id
    assert set(ids[1:3]) == {expiry_warning.id, low.id}
    assert ids[3:] == [slow.id]


# ── los niveles salen de las reglas ───────────────────────────────────────────

def test_an_expiry_inside_the_limit_is_critical_and_one_near_the_limit_is_a_warning(client, db):
    # límite general de fábrica: 7 días; "cerca" llega hasta 4 días más
    add_product_with_alert(db, expiry_in=7)
    add_product_with_alert(db, expiry_in=8)
    add_product_with_alert(db, expiry_in=11)

    levels = sorted((a["limit_days"], a["level"]) for a in alerts(client))

    assert levels == [(7, "critical"), (7, "warning"), (7, "warning")]


def test_an_expiry_far_from_the_limit_has_no_alert(client, db):
    add_product_with_alert(db, expiry_in=12)

    assert alerts(client) == []


def test_an_expired_product_is_critical(client, db):
    add_product_with_alert(db, expiry_in=-2)

    item = alerts(client)[0]

    assert item["level"] == "critical"


def test_the_limit_of_the_profile_rules_every_product_that_has_no_rule_of_its_own(client, db):
    set_profile(db, dias_alerta_vencimiento=3)
    add_product_with_alert(db, expiry_in=3)
    add_product_with_alert(db, expiry_in=5)
    add_product_with_alert(db, expiry_in=9)

    items = sorted(alerts(client), key=lambda a: a["id"])

    assert [(a["level"], a["limit_days"], a["rule_scope"]) for a in items] == [
        ("critical", 3, "general"), ("warning", 3, "general"),
    ]


def test_the_rule_of_a_product_beats_the_one_of_the_profile(client, db):
    set_profile(db, dias_alerta_vencimiento=3)
    product, _ = add_product_with_alert(db, expiry_in=10)
    product.dias_alerta_vencimiento = 14
    db.commit()

    item = alerts(client)[0]

    assert (item["level"], item["limit_days"], item["rule_scope"]) == ("critical", 14, "product")


def test_changing_the_rule_changes_the_alerts_right_away(client, db):
    add_product_with_alert(db, expiry_in=10)
    assert alerts(client)[0]["level"] == "warning"

    profile = UserProfile(user_id=TEST_USER_ID, dias_alerta_vencimiento=15)
    db.add(profile)
    db.commit()

    assert alerts(client)[0]["level"] == "critical"
    profile.dias_alerta_vencimiento = 2
    db.commit()
    assert alerts(client) == []


def test_reading_the_alerts_creates_the_expiry_ones_that_were_never_registered(client, db):
    # Un producto que ya está por vencer, aunque nadie haya corrido el chequeo ni lo haya editado
    db.add(Product(user_id=TEST_USER_ID, nombre="Queso", categoria="Lacteo", stock=3, vencimiento=days_from_now(4)))
    db.commit()

    body = alerts(client)

    assert [(a["type"], a["level"]) for a in body] == [("expiry", "critical")]


def test_a_stock_alert_is_critical_below_the_minimum_and_a_warning_near_it(client, db):
    # mínimo de fábrica: 7 días; "cerca" llega hasta 4 días más
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=6)
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=7)
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=10)

    levels = sorted((a["days_until_stockout"], a["level"]) for a in alerts(client))

    assert levels == [(6, "critical"), (7, "warning"), (10, "warning")]


def test_a_stock_alert_far_from_the_minimum_is_not_shown(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=11)

    assert alerts(client) == []


def test_the_minimum_stock_of_the_product_beats_the_one_of_the_profile(client, db):
    set_profile(db, stock_minimo=3)
    product, _ = add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=5)
    assert alerts(client) == []
    product.stock_minimo = 10
    db.commit()

    item = alerts(client)[0]

    assert (item["level"], item["limit_days"], item["rule_scope"]) == ("critical", 10, "product")


def test_a_slow_pace_alert_is_critical_when_the_expiry_is_inside_the_limit(client, db):
    product, _ = add_product_with_alert(db, alert_type="slow_pace")
    product.vencimiento = days_from_now(5)
    db.commit()
    assert alerts(client)[0]["level"] == "critical"

    product.vencimiento = days_from_now(20)
    db.commit()
    assert alerts(client)[0]["level"] == "warning"


# ── el resumen sale de la misma lista ─────────────────────────────────────────

def test_the_summary_counts_exactly_what_the_list_shows(client, db):
    add_product_with_alert(db, expiry_in=2)
    add_product_with_alert(db, expiry_in=9)
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=1)
    add_product_with_alert(db, alert_type="slow_pace")

    body = alerts(client)
    summary = client.get("/alerts/summary", headers=AUTH).json()

    assert summary["total"] == len(body) == 4
    assert summary["critical"] == sum(1 for a in body if a["level"] == "critical")
    assert summary["warning"] == sum(1 for a in body if a["level"] == "warning")
    assert summary["critical"] + summary["warning"] + summary["info"] == summary["total"]


def test_the_summary_does_not_count_alerts_whose_product_no_longer_exists(client, db):
    db.add(Alert(user_id=UUID(TEST_USER_ID), product_id=9999, type="expiry", level="critical"))
    db.commit()

    summary = client.get("/alerts/summary", headers=AUTH).json()

    assert summary["total"] == 0


def test_the_summary_tells_how_many_products_are_expiring_and_low_on_stock(client, db):
    add_product_with_alert(db, expiry_in=2)
    add_product_with_alert(db, expiry_in=-1)
    add_product_with_alert(db, expiry_in=9)  # advertencia: no cuenta
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=1)
    add_product_with_alert(db, alert_type="stock_low_coverage", days_until_stockout=8)  # advertencia: no cuenta

    summary = client.get("/alerts/summary", headers=AUTH).json()

    assert (summary["expiring"], summary["low_stock"]) == (2, 1)


def test_the_summary_of_a_user_without_alerts_is_all_zeros(client, db):
    assert client.get("/alerts/summary", headers=AUTH).json() == {
        "critical": 0, "warning": 0, "info": 0, "total": 0, "expiring": 0, "low_stock": 0,
    }


# ── de punta a punta: las alertas nacen de editar productos ───────────────────
#
# Un producto que baja de stock o está por vencer dispara la evaluación del ML;
# acá se simula su predicción y se leen las alertas resultantes por la API.

def prediction(days_until_stockout, daily_rate=2.0):
    return lambda req: httpx.Response(200, json={
        "daily_rate": daily_rate, "days_until_stockout": days_until_stockout, "stage": "bayesian", "segment": "individuo",
    })


def create_product(client, **overrides):
    payload = {"nombre": "Leche", "categoria": "Lacteo", "stock": 10}
    payload.update(overrides)
    resp = client.post("/products/", json=payload, headers=AUTH)
    assert resp.status_code == 201
    return resp.json()


def set_stock(client, product_id, stock):
    assert client.put(f"/products/{product_id}", json={"stock": stock}, headers=AUTH).status_code == 200


def test_no_alerts_at_first(client, db):
    assert alerts(client) == []


def test_lowering_the_stock_generates_low_stock_alerts_with_the_suggested_restock(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=5))
    leche = create_product(client, nombre="Leche")
    pan = create_product(client, nombre="Pan", categoria="Panaderia", stock=5)

    set_stock(client, leche["id"], 1)
    set_stock(client, pan["id"], 1)

    body = alerts(client)
    assert [a["type"] for a in body] == ["stock_low_coverage", "stock_low_coverage"]
    assert all(a["level"] == "critical" and a["suggested_qty"] == 13 for a in body)
    assert len(alerts(client, "/alerts/stock_alerts")) == 2


def test_a_low_stock_edit_registers_the_alert_in_the_same_row_as_the_suggested_restock(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=3, daily_rate=2.0))
    leche = create_product(client, nombre="Leche", stock=10)

    set_stock(client, leche["id"], 4)

    stock = [a for a in alerts(client) if a["type"] == "stock_low_coverage"]
    # 7 días de cobertura a 2 por día = 14, menos las 4 que quedan
    assert [(a["suggested_qty"], a["origin"], a["level"], a["days_until_stockout"]) for a in stock] == [(10, "rule", "critical", 3)]


def test_restocking_updates_the_alert_and_clears_it_when_the_coverage_recovers(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=3, daily_rate=2.0))
    leche = create_product(client, nombre="Leche", stock=10)
    set_stock(client, leche["id"], 4)

    # sigue bajo el mínimo pero con menos que reponer
    ml_transport(prediction(days_until_stockout=5, daily_rate=2.0))
    set_stock(client, leche["id"], 8)
    assert [a["suggested_qty"] for a in alerts(client)] == [6]

    ml_transport(prediction(days_until_stockout=30, daily_rate=2.0))
    set_stock(client, leche["id"], 60)
    assert alerts(client) == []


def test_an_alert_for_a_stockout_today_never_says_zero_days(client, db, notifications, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=0, daily_rate=5.0))
    leche = create_product(client, nombre="Leche", stock=10)

    set_stock(client, leche["id"], 2)

    sent = [n for n in notifications if n["title"] == "Stock por agotarse"]
    assert sent and "0 días" not in sent[0]["body"] and "hoy" in sent[0]["body"]


def test_the_predictions_are_kept_when_the_model_does_not_answer(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=3))
    leche = create_product(client, nombre="Leche", stock=10)
    set_stock(client, leche["id"], 4)
    assert len(alerts(client)) == 1

    ml_transport(httpx.ConnectError("sin conexión"))
    set_stock(client, leche["id"], 3)

    assert len(alerts(client)) == 1


@freeze_time("2024-06-20")
def test_expiry_alerts_list_the_expiring_and_the_slow_pace_ones(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=10))
    leche = create_product(client, nombre="Leche", vencimiento="2024-06-21")
    pan = create_product(client, nombre="Pan", categoria="Panaderia", stock=5, vencimiento="2024-06-30")

    set_stock(client, leche["id"], 7)
    set_stock(client, pan["id"], 4)

    assert sorted(a["type"] for a in alerts(client, "/alerts/expiry_alerts")) == ["expiry", "expiry", "slow_pace"]


@freeze_time("2024-06-20")
def test_a_product_expiring_tomorrow_is_a_critical_alert(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=30))
    create_product(client, nombre="Leche", vencimiento="2024-06-21")

    body = alerts(client, "/alerts/critical_alerts")

    assert [(a["type"], a["level"]) for a in body] == [("expiry", "critical")]


@freeze_time("2024-06-20")
def test_the_summary_counts_the_alerts_generated_by_editing_products(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=30))
    create_product(client, nombre="Leche", vencimiento="2024-06-21")
    create_product(client, nombre="Pan", categoria="Panaderia", stock=5, vencimiento="2024-06-30")

    summary = client.get("/alerts/summary", headers=AUTH).json()

    # Leche vence en 1 día (crítica); Pan, en 10 (cerca del límite de 7 días: advertencia)
    assert (summary["critical"], summary["warning"], summary["total"]) == (1, 1, 2)
