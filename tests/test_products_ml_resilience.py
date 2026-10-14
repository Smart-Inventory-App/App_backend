"""`_check_product_state` con el ML: segmento del usuario y tolerancia a fallas.

Antes todo el cuerpo estaba dentro de un `try/except Exception: pass`; ahora solo
la evaluación de alertas de ML lo está, para que un error en ella no tumbe la
operación del producto que la disparó.
"""
import json
import logging

import httpx

from app.api import products as products_api
from app.core.config import settings
from app.models.alert import Alert
from app.models.product import Product
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def create(client, **overrides):
    payload = {"nombre": "Producto", "categoria": "General", "stock": 20}
    payload.update(overrides)
    resp = client.post("/products/", json=payload, headers=AUTH)
    assert resp.status_code == 201
    return resp.json()


def predict(days_until_stockout, daily_rate=1.0):
    return lambda req: httpx.Response(200, json={"daily_rate": daily_rate, "days_until_stockout": days_until_stockout})


# ── segmento ──────────────────────────────────────────────────────────────────

def test_the_profile_user_type_is_sent_to_the_ml_when_a_product_changes(client, db, notifications, ml_enabled, ml_transport):
    resp = client.put("/profile/", json={"firstName": "Test", "lastName": "User", "userType": "comercio"}, headers=AUTH)
    assert resp.status_code == 200
    product = create(client)
    seen = []
    ml_transport(lambda req: seen.append(json.loads(req.content)["segment"]) or httpx.Response(200, json=predict(50)(req).json()))

    client.put(f"/products/{product['id']}", json={"stock": 19}, headers=AUTH)

    assert seen == ["comercio"]


def test_the_default_segment_is_sent_when_the_profile_has_none(client, db, notifications, ml_enabled, ml_transport):
    product = create(client)
    seen = []
    ml_transport(lambda req: seen.append(json.loads(req.content)["segment"]) or httpx.Response(200, json=predict(50)(req).json()))

    client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 1}, headers=AUTH)

    assert seen == ["individuo"]


# ── una falla al evaluar alertas no tumba la operación ────────────────────────

def test_a_failure_while_creating_the_alert_does_not_break_the_update(client, db, notifications, ml_enabled, ml_transport, monkeypatch, caplog):
    product = create(client, nombre="Cafe")
    ml_transport(predict(1))  # cobertura crítica: intentará crear la alerta

    def boom(*args, **kwargs):
        raise RuntimeError("la base de datos se cayó")

    monkeypatch.setattr(products_api, "_create_alert", boom)

    with caplog.at_level(logging.ERROR, logger=products_api.logger.name):
        resp = client.put(f"/products/{product['id']}", json={"stock": 19}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["stock"] == 19
    assert db.query(Product).filter(Product.id == product["id"]).one().stock == 19
    assert db.query(Alert).filter(Alert.product_id == product["id"]).count() == 0
    assert "No se pudieron evaluar las alertas de ML" in caplog.text


def test_a_failure_while_creating_the_alert_does_not_break_a_consumption_event(client, db, notifications, ml_enabled, ml_transport, monkeypatch):
    product = create(client, nombre="Te")
    ml_transport(predict(1))
    monkeypatch.setattr(products_api, "_create_alert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falla")))

    resp = client.post(f"/products/{product['id']}/events", json={"event_type": "consumed", "quantity": 2}, headers=AUTH)

    assert resp.status_code == 201
    assert resp.json()["remaining_stock"] == 18


async def test_check_product_state_returns_none_when_the_alert_logic_fails(db, ml_enabled, ml_transport, monkeypatch):
    from app.models.profile import UserProfile
    from app.models.user import AuthUser
    from uuid import UUID

    product = Product(user_id=TEST_USER_ID, nombre="Sal", categoria="X", stock=5)
    db.add(product)
    db.commit()
    user = db.get(AuthUser, UUID(TEST_USER_ID))
    profile = UserProfile(user_id=TEST_USER_ID)
    ml_transport(predict(1))

    async def boom(*args, **kwargs):
        raise RuntimeError("falla")

    monkeypatch.setattr(products_api, "_apply_ml_alerts", boom)

    assert await products_api._check_product_state(product, user, profile, db) is None


async def test_check_product_state_returns_the_prediction_when_everything_works(db, notifications, ml_enabled, ml_transport):
    from app.models.profile import UserProfile
    from app.models.user import AuthUser
    from uuid import UUID

    product = Product(user_id=TEST_USER_ID, nombre="Sal", categoria="X", stock=5)
    db.add(product)
    db.commit()
    user = db.get(AuthUser, UUID(TEST_USER_ID))
    profile = UserProfile(user_id=TEST_USER_ID)
    ml_transport(predict(50, daily_rate=0.1))

    result = await products_api._check_product_state(product, user, profile, db)

    assert result == {"daily_rate": 0.1, "days_until_stockout": 50}


async def test_check_product_state_does_nothing_with_ml_when_the_service_is_not_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "ML_SERVICE_URL", "")
    from uuid import UUID

    from app.models.profile import UserProfile
    from app.models.user import AuthUser

    product = Product(user_id=TEST_USER_ID, nombre="Sal", categoria="X", stock=5)
    db.add(product)
    db.commit()
    user = db.get(AuthUser, UUID(TEST_USER_ID))

    assert await products_api._check_product_state(product, user, UserProfile(user_id=TEST_USER_ID), db) is None
