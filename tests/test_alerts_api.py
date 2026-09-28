"""Endpoints de lectura de alertas (`/alerts/*`)."""
from uuid import UUID

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
