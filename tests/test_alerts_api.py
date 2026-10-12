"""Endpoints de lectura de alertas (`/alerts/*`).

Primero con alertas sembradas directo en la base (qué devuelve cada endpoint) y después
de punta a punta: las alertas nacen de editar productos y se leen por la API."""
from uuid import UUID

import httpx
from freezegun import freeze_time

from app.models.alert import Alert
from app.models.product import Product
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def add_product_with_alert(db, alert_type="expiry", level="warning", **alert_overrides):
    product = Product(user_id=TEST_USER_ID, nombre="Yogur", categoria="Lacteo", stock=5)
    db.add(product)
    db.commit()
    db.refresh(product)
    alert = Alert(user_id=UUID(TEST_USER_ID), product_id=product.id, type=alert_type, level=level, **alert_overrides)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return product, alert


def test_get_alerts_lists_own_alerts_with_product_info(client, db):
    product, _ = add_product_with_alert(db)

    resp = client.get("/alerts/", headers=AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["product_name"] == "Yogur"
    assert body[0]["product_stock"] == 5


def test_critical_alerts_filters_by_level(client, db):
    add_product_with_alert(db, level="warning")
    _, critical = add_product_with_alert(db, level="critical")

    resp = client.get("/alerts/critical_alerts", headers=AUTH)

    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == critical.id


def test_expiry_alerts_includes_expiry_and_slow_pace(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage")
    add_product_with_alert(db, alert_type="expiry")
    add_product_with_alert(db, alert_type="slow_pace")

    resp = client.get("/alerts/expiry_alerts", headers=AUTH)

    assert len(resp.json()) == 2


def test_stock_alerts_only_lists_low_coverage(client, db):
    add_product_with_alert(db, alert_type="stock_low_coverage")
    add_product_with_alert(db, alert_type="expiry")

    resp = client.get("/alerts/stock_alerts", headers=AUTH)

    assert len(resp.json()) == 1


def test_alert_summary_counts_by_level(client, db):
    add_product_with_alert(db, level="critical")
    add_product_with_alert(db, level="warning")
    add_product_with_alert(db, level="warning")

    resp = client.get("/alerts/summary", headers=AUTH)

    assert resp.json() == {"critical": 1, "warning": 2, "info": 0}


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
    assert client.get("/alerts/", headers=AUTH).json() == []


def test_lowering_the_stock_generates_low_coverage_alerts(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=5))
    leche = create_product(client, nombre="Leche")
    pan = create_product(client, nombre="Pan", categoria="Panaderia", stock=5)

    set_stock(client, leche["id"], 1)
    set_stock(client, pan["id"], 1)

    alerts = client.get("/alerts/", headers=AUTH).json()
    assert [a["type"] for a in alerts] == ["stock_low_coverage", "stock_low_coverage"]
    assert len(client.get("/alerts/stock_alerts", headers=AUTH).json()) == 2


@freeze_time("2024-06-20")
def test_expiry_alerts_list_the_expiring_and_the_slow_pace_ones(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=10))
    leche = create_product(client, nombre="Leche", vencimiento="2024-06-21")
    pan = create_product(client, nombre="Pan", categoria="Panaderia", stock=5, vencimiento="2024-06-30")

    set_stock(client, leche["id"], 7)
    set_stock(client, pan["id"], 4)

    alerts = client.get("/alerts/expiry_alerts", headers=AUTH).json()
    assert sorted(a["type"] for a in alerts) == ["expiry", "slow_pace"]


@freeze_time("2024-06-20")
def test_a_product_expiring_tomorrow_is_a_critical_alert(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=5))
    leche = create_product(client, nombre="Leche", vencimiento="2024-06-21")

    set_stock(client, leche["id"], 7)

    critical = client.get("/alerts/critical_alerts", headers=AUTH).json()
    assert [a["product_id"] for a in critical] == [leche["id"]]


@freeze_time("2024-06-20")
def test_the_summary_counts_the_alerts_generated_by_editing_products(client, db, ml_enabled, ml_transport):
    ml_transport(prediction(days_until_stockout=10))
    leche = create_product(client, nombre="Leche", vencimiento="2024-06-21")
    pan = create_product(client, nombre="Pan", categoria="Panaderia", stock=5, vencimiento="2024-06-30")

    set_stock(client, leche["id"], 7)
    set_stock(client, pan["id"], 4)

    assert client.get("/alerts/summary", headers=AUTH).json() == {"critical": 1, "warning": 1, "info": 0}
