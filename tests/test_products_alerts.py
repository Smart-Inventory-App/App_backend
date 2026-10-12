"""Evaluación de alertas de `_check_product_state`: vencimiento y, con el
servicio de ML configurado, cobertura baja / exceso de stock / ritmo lento."""
from datetime import date, timedelta
from uuid import UUID
import httpx
import pytest

from app.api import products as products_api
from app.core.config import settings
from app.models.alert import Alert
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def create(client, **overrides):
    payload = {"nombre": "Producto", "categoria": "General", "stock": 5}
    payload.update(overrides)
    resp = client.post("/products/", json=payload, headers=AUTH)
    assert resp.status_code == 201
    return resp.json()


# ── vencimiento (no necesita ML) ──────────────────────────────────────────────

def test_update_close_to_expiry_creates_a_warning_alert(client, db, notifications):
    product = create(client, nombre="Yogur")
    soon = (date.today() + timedelta(days=3)).isoformat()

    resp = client.put(f"/products/{product['id']}", json={"vencimiento": soon}, headers=AUTH)

    assert resp.status_code == 200
    alert = db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "expiry").first()
    assert alert is not None
    assert alert.level == "warning"
    assert notifications[0]["title"] == "Producto próximo a vencerse"


def test_a_second_update_upgrades_the_alert_to_critical(client, db, notifications):
    product = create(client, nombre="Queso")
    soon = (date.today() + timedelta(days=3)).isoformat()
    client.put(f"/products/{product['id']}", json={"vencimiento": soon}, headers=AUTH)

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    client.put(f"/products/{product['id']}", json={"vencimiento": tomorrow}, headers=AUTH)

    alert = db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "expiry").first()
    assert alert.level == "critical"


def test_pushing_the_expiry_far_enough_deletes_the_alert(client, db, notifications):
    product = create(client, nombre="Manteca")
    soon = (date.today() + timedelta(days=3)).isoformat()
    client.put(f"/products/{product['id']}", json={"vencimiento": soon}, headers=AUTH)

    far = (date.today() + timedelta(days=30)).isoformat()
    client.put(f"/products/{product['id']}", json={"vencimiento": far}, headers=AUTH)

    assert db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "expiry").count() == 0


# ── ML: cobertura baja y ritmo lento ──────────────────────────────────────────

def test_low_coverage_alert_is_created_from_the_ml_prediction(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Arroz", stock=10)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 3}))

    resp = client.put(f"/products/{product['id']}", json={"stock": 9}, headers=AUTH)

    assert resp.status_code == 200
    alert = db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "stock_low_coverage").first()
    assert alert is not None
    assert alert.level == "warning"
    assert any(n["title"] == "Stock por agotarse" for n in notifications)


def test_low_coverage_alert_is_critical_when_the_stockout_is_imminent(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Fideos", stock=10)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 1}))

    client.put(f"/products/{product['id']}", json={"stock": 9}, headers=AUTH)

    alert = db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "stock_low_coverage").first()
    assert alert.level == "critical"


def test_low_coverage_is_suppressed_right_after_a_restock(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Aceite", stock=1)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 3}))

    # El stock subió (restock): no se evalúa cobertura baja, sólo over/understock.
    client.put(f"/products/{product['id']}", json={"stock": 2}, headers=AUTH)

    assert db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "stock_low_coverage").count() == 0


def test_slow_pace_alert_is_created_when_consumption_wont_catch_the_expiry(client, db, notifications, ml_enabled, ml_transport):
    vencimiento = (date.today() + timedelta(days=5)).isoformat()
    product = create(client, nombre="Miel", stock=10, vencimiento=vencimiento)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 0.5, "days_until_stockout": 20}))

    client.put(f"/products/{product['id']}", json={"stock": 9}, headers=AUTH)

    alert = db.query(Alert).filter(Alert.product_id == product["id"], Alert.type == "slow_pace").first()
    assert alert is not None
    assert any(n["title"] == "Riesgo de vencimiento por bajo consumo" for n in notifications)


# ── ML: overstock / understock tras un alta que fusiona o una edición ────────

def test_merging_into_a_lot_that_will_last_too_long_warns_overstock(client, db, notifications, ml_enabled, ml_transport):
    create(client, nombre="Detergente", stock=5)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 0.1, "days_until_stockout": 90}))

    resp = client.post("/products/", json={"nombre": "Detergente", "categoria": "General", "stock": 5}, headers=AUTH)

    assert resp.json()["merged"] is True
    assert any(n["title"] == "Compraste más de lo necesario" for n in notifications)


def test_merging_when_the_lot_wont_last_warns_understock(client, db, notifications, ml_enabled, ml_transport):
    create(client, nombre="Jabon", stock=5)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 3}))

    resp = client.post("/products/", json={"nombre": "Jabon", "categoria": "General", "stock": 5}, headers=AUTH)

    assert resp.json()["merged"] is True
    assert any(n["title"] == "Compraste menos de lo necesario" for n in notifications)


def test_a_direct_restock_can_also_warn_overstock(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Papel", stock=5)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 0.1, "days_until_stockout": 90}))

    client.put(f"/products/{product['id']}", json={"stock": 20}, headers=AUTH)

    assert any(n["title"] == "Compraste más de lo necesario" for n in notifications)


# ── el ML no está disponible: no puede tirar abajo el endpoint ──────────────

def test_a_non_200_ml_response_is_ignored(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Sal", stock=5)
    ml_transport(lambda req: httpx.Response(500))

    resp = client.put(f"/products/{product['id']}", json={"stock": 4}, headers=AUTH)

    assert resp.status_code == 200


def test_an_unreachable_ml_service_is_ignored(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Azucar", stock=5)
    ml_transport(httpx.ConnectError("el ML no responde"))

    resp = client.put(f"/products/{product['id']}", json={"stock": 4}, headers=AUTH)

    assert resp.status_code == 200


# ── las alertas se van cuando la condición que las generó deja de cumplirse ──

def alerts_of(db, product, alert_type=None):
    query = db.query(Alert).filter(Alert.product_id == product["id"])
    return query.filter(Alert.type == alert_type).count() if alert_type else query.count()


def predict(days_until_stockout, daily_rate=1.0):
    return lambda req: httpx.Response(200, json={"daily_rate": daily_rate, "days_until_stockout": days_until_stockout})


def test_restocking_clears_the_low_coverage_alert(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Cafe", stock=20)
    ml_transport(predict(3))
    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 19}, headers=AUTH)
    assert alerts_of(db, product, "stock_low_coverage") == 1

    ml_transport(predict(200))
    client.put(f"/products/{product['id']}", json={"stock": 200}, headers=AUTH)

    assert alerts_of(db, product, "stock_low_coverage") == 0


def test_a_restock_that_still_leaves_low_coverage_keeps_the_alert(client, db, notifications, ml_enabled, ml_transport):
    product = create(client, nombre="Te", stock=20)
    ml_transport(predict(3))
    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 19}, headers=AUTH)

    client.put(f"/products/{product['id']}", json={"stock": 2}, headers=AUTH)

    assert alerts_of(db, product, "stock_low_coverage") == 1


def test_a_consumption_with_no_rate_clears_the_low_coverage_alert(client, db, notifications, ml_enabled, ml_transport):
    """Sin ritmo de consumo no hay fecha de agotamiento: nada que alertar."""
    product = create(client, nombre="Sal", stock=20)
    ml_transport(predict(3))
    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 19}, headers=AUTH)
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": None, "days_until_stockout": None}))

    client.put(f"/products/{product['id']}", json={"stock": 50}, headers=AUTH)

    assert alerts_of(db, product, "stock_low_coverage") == 0


def test_moving_the_expiry_away_clears_the_slow_pace_alert(client, db, notifications, ml_enabled, ml_transport):
    vencimiento = (date.today() + timedelta(days=5)).isoformat()
    product = create(client, nombre="Galletas", stock=10, vencimiento=vencimiento)
    ml_transport(predict(20, daily_rate=0.5))
    client.put(f"/products/{product['id']}", json={"stock": 9}, headers=AUTH)
    assert alerts_of(db, product, "slow_pace") == 1

    far = (date.today() + timedelta(days=400)).isoformat()
    client.put(f"/products/{product['id']}", json={"vencimiento": far}, headers=AUTH)

    assert alerts_of(db, product, "slow_pace") == 0


def test_a_depleted_product_has_no_units_left_to_waste(client, db, notifications, ml_enabled, ml_transport):
    vencimiento = (date.today() + timedelta(days=5)).isoformat()
    product = create(client, nombre="Mermelada", stock=10, vencimiento=vencimiento)
    ml_transport(predict(20, daily_rate=0.5))
    client.put(f"/products/{product['id']}", json={"stock": 9}, headers=AUTH)
    assert alerts_of(db, product, "slow_pace") == 1

    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 9}, headers=AUTH)

    assert alerts_of(db, product, "slow_pace") == 0


def test_an_ml_failure_does_not_clear_existing_alerts(client, db, notifications, ml_enabled, ml_transport):
    """Si el ML no contesta no se sabe si la condición sigue: se conserva lo que había."""
    product = create(client, nombre="Aceitunas", stock=20)
    ml_transport(predict(3))
    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 19}, headers=AUTH)

    ml_transport(lambda req: httpx.Response(500))
    client.put(f"/products/{product['id']}", json={"stock": 100}, headers=AUTH)

    assert alerts_of(db, product, "stock_low_coverage") == 1


# ── `_get_user`: 404 cuando el token no corresponde a un usuario real ────────

def test_update_is_404_when_the_caller_is_not_a_valid_uuid(client, db, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app
    from app.models.product import Product

    ghost = {"sub": "not-a-uuid", "email": "g@test.com"}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: ghost)

    product = Product(user_id=ghost["sub"], nombre="X", categoria="C", stock=5)
    db.add(product)
    db.commit()
    db.refresh(product)

    resp = client.put(f"/products/{product.id}", json={"stock": 1}, headers=AUTH)

    assert resp.status_code == 404


def test_update_is_404_when_the_caller_has_no_auth_users_row(client, db, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app
    from app.models.product import Product

    ghost = {"sub": "99999999-9999-4999-8999-999999999999", "email": "g@test.com"}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: ghost)

    product = Product(user_id=ghost["sub"], nombre="X", categoria="C", stock=5)
    db.add(product)
    db.commit()
    db.refresh(product)

    resp = client.put(f"/products/{product.id}", json={"stock": 1}, headers=AUTH)

    assert resp.status_code == 404


# ── borrar un producto que tiene alertas ──────────────────────────────────────

def test_deleting_a_product_also_deletes_its_alerts(client, db):
    # Regresión: en Postgres la FK de alerts.product_id rechazaba el borrado (500).
    product = create(client, nombre="Con alerta")
    other = create(client, nombre="Otro")
    for p in (product, other):
        db.add(Alert(user_id=UUID(TEST_USER_ID), product_id=p["id"], type="expiry", level="warning"))
    db.commit()

    resp = client.delete(f"/products/{product['id']}", headers=AUTH)

    assert resp.status_code == 204
    db.expire_all()
    assert db.query(Alert).filter(Alert.product_id == product["id"]).count() == 0
    # las alertas de otros productos no se tocan
    assert db.query(Alert).filter(Alert.product_id == other["id"]).count() == 1


# ── límites de stock (6 dígitos) y de motivo (50 caracteres) ──────────────────

def test_stock_above_six_digits_is_rejected_on_create_and_update(client, db):
    resp = client.post("/products/", json={"nombre": "Grande", "categoria": "X", "stock": 1000000}, headers=AUTH)
    assert resp.status_code == 422

    ok = client.post("/products/", json={"nombre": "Grande", "categoria": "X", "stock": 999999}, headers=AUTH)
    assert ok.status_code == 201

    upd = client.put(f"/products/{ok.json()['id']}", json={"stock": 1000000}, headers=AUTH)
    assert upd.status_code == 422


def test_event_quantity_and_note_limits(client, db):
    product = create(client, nombre="Eventos", stock=999999)
    base = {"event_type": "consumed", "quantity": 1}

    assert client.post(f"/products/{product['id']}/events", json={**base, "quantity": 1000000}, headers=AUTH).status_code == 422
    assert client.post(f"/products/{product['id']}/events", json={**base, "note": "x" * 51}, headers=AUTH).status_code == 422
    assert client.post(f"/products/{product['id']}/events", json={**base, "note": "x" * 50}, headers=AUTH).status_code == 201


def test_correction_quantity_and_note_limits(client, db):
    product = create(client, nombre="Corregir", stock=20)
    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 2}, headers=AUTH)
    event_id = client.get(f"/products/{product['id']}/consumption", headers=AUTH).json()[0]["id"]
    url = f"/products/{product['id']}/events/{event_id}"

    assert client.put(url, json={"event_type": "consumed", "quantity": 1000000}, headers=AUTH).status_code == 422
    assert client.put(url, json={"event_type": "consumed", "quantity": 3, "note": "x" * 51}, headers=AUTH).status_code == 422
    assert client.put(url, json={"event_type": "consumed", "quantity": 3, "note": "x" * 50}, headers=AUTH).status_code == 200
