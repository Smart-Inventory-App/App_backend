"""`GET /products/reposicion-sugerida`: cuánto reponer según el ritmo que predice el ML."""
import asyncio
import json

import httpx
import pytest

from app.api import products as products_api
from app.core.config import settings
from app.models.product import Product
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}
URL = "/products/reposicion-sugerida"


def create(client, **overrides):
    payload = {"nombre": "Producto", "categoria": "General", "stock": 5, "stock_minimo": 10}
    payload.update(overrides)
    resp = client.post("/products/", json=payload, headers=AUTH)
    assert resp.status_code == 201
    return resp.json()


def set_profile(client, **fields):
    payload = {"firstName": "Test", "lastName": "User", **fields}
    assert client.put("/profile/", json=payload, headers=AUTH).status_code == 200


def predict(daily_rate, days_until_stockout):
    return lambda req: httpx.Response(200, json={"daily_rate": daily_rate, "days_until_stockout": days_until_stockout})


def by_product(table):
    """Handler que responde según el `id` del producto del request."""
    def handler(req):
        product_id = json.loads(req.content)["product"]["id"]
        daily_rate, days = table[product_id]
        return httpx.Response(200, json={"daily_rate": daily_rate, "days_until_stockout": days})
    return handler


def test_a_user_without_products_gets_an_empty_list(client, db, ml_enabled, ml_transport):
    ml_transport(predict(1.0, 1))

    resp = client.get(URL, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == []


def test_it_suggests_enough_units_to_reach_the_minimum_coverage(client, db, ml_enabled, ml_transport):
    product = create(client, nombre="Leche", stock=5, stock_minimo=10)
    ml_transport(predict(2.0, 3))

    body = client.get(URL, headers=AUTH).json()

    # cobertura de 10 días a 2 u/día = 20 unidades; ya hay 5
    assert body == [{
        "product_id": product["id"], "nombre": "Leche", "stock": 5, "imagen_url": None,
        "daily_rate": 2.0, "days_until_stockout": 3, "suggested_qty": 15,
    }]


def test_the_profile_coverage_is_used_when_the_product_has_no_minimum(client, db, ml_enabled, ml_transport):
    set_profile(client, coverageDaysThreshold=20)
    create(client, nombre="Cafe", stock=5, stock_minimo=None)
    ml_transport(predict(1.0, 5))

    body = client.get(URL, headers=AUTH).json()

    assert body[0]["suggested_qty"] == 15  # 20 días * 1 u/día - 5


def test_the_most_urgent_products_come_first(client, db, ml_enabled, ml_transport):
    lenta = create(client, nombre="Lenta", stock=2)
    urgente = create(client, nombre="Urgente", stock=1)
    media = create(client, nombre="Media", stock=3)
    ml_transport(by_product({lenta["id"]: (1.0, 8), urgente["id"]: (1.0, 1), media["id"]: (1.0, 4)}))

    body = client.get(URL, headers=AUTH).json()

    assert [p["nombre"] for p in body] == ["Urgente", "Media", "Lenta"]


def test_a_product_with_enough_coverage_is_not_suggested(client, db, ml_enabled, ml_transport):
    create(client, stock=50, stock_minimo=10)
    ml_transport(predict(1.0, 50))

    assert client.get(URL, headers=AUTH).json() == []


def test_a_product_exactly_at_the_minimum_coverage_is_not_suggested(client, db, ml_enabled, ml_transport):
    create(client, stock=10, stock_minimo=10)
    ml_transport(predict(1.0, 10))

    assert client.get(URL, headers=AUTH).json() == []


@pytest.mark.parametrize("daily_rate", [0, 0.0, None, -1.0])
def test_a_product_with_no_consumption_rate_is_not_suggested(client, db, ml_enabled, ml_transport, daily_rate):
    create(client)
    ml_transport(predict(daily_rate, 3))

    assert client.get(URL, headers=AUTH).json() == []


def test_a_product_with_no_stockout_date_is_not_suggested(client, db, ml_enabled, ml_transport):
    create(client)
    ml_transport(predict(1.0, None))

    assert client.get(URL, headers=AUTH).json() == []


def test_a_suggestion_that_rounds_to_nothing_is_dropped(client, db, ml_enabled, ml_transport):
    """Faltan pocos días de cobertura, pero el stock ya cubre lo que se consumiría."""
    create(client, stock=5, stock_minimo=10)
    ml_transport(predict(0.1, 3))  # 10 días * 0.1 = 1 unidad < 5 de stock

    assert client.get(URL, headers=AUTH).json() == []


def test_products_without_stock_are_skipped(client, db, ml_enabled, ml_transport):
    product = create(client)
    db.query(Product).filter(Product.id == product["id"]).update({"stock": 0})
    db.commit()
    ml_transport(predict(2.0, 1))

    assert client.get(URL, headers=AUTH).json() == []


def test_other_users_products_are_not_suggested(client, db, ml_enabled, ml_transport):
    db.add(Product(user_id="22222222-2222-4222-8222-222222222222", nombre="Ajeno", categoria="X", stock=1))
    db.commit()
    ml_transport(predict(2.0, 1))

    assert client.get(URL, headers=AUTH).json() == []


def test_an_unreachable_ml_service_gives_an_empty_list(client, db, ml_enabled, ml_transport):
    create(client)
    ml_transport(httpx.ConnectError("el ML no responde"))

    resp = client.get(URL, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == []


def test_a_product_the_ml_could_not_predict_does_not_hide_the_others(client, db, ml_enabled, ml_transport):
    rota = create(client, nombre="Rota", stock=1)
    buena = create(client, nombre="Buena", stock=1)

    def handler(req):
        if json.loads(req.content)["product"]["id"] == rota["id"]:
            return httpx.Response(500)
        return httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 1})

    ml_transport(handler)

    body = client.get(URL, headers=AUTH).json()

    assert [p["product_id"] for p in body] == [buena["id"]]


def test_without_a_configured_ml_service_the_list_is_empty(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ML_SERVICE_URL", "")
    create(client)

    resp = client.get(URL, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == []


def test_the_user_segment_is_sent_to_the_ml(client, db, ml_enabled, ml_transport):
    set_profile(client, userType="comercio")
    create(client)
    seen = []
    ml_transport(lambda req: seen.append(json.loads(req.content)["segment"]) or httpx.Response(200, json={}))

    client.get(URL, headers=AUTH)

    assert seen == ["comercio"]


def test_the_route_is_not_swallowed_by_the_product_id_route(client, db, ml_enabled, ml_transport):
    ml_transport(predict(1.0, 1))

    assert client.get(URL, headers=AUTH).status_code == 200  # y no un 422 por "reposicion-sugerida" no entero


def test_predictions_run_in_parallel_with_a_concurrency_cap(client, db, monkeypatch):
    for i in range(20):
        create(client, nombre=f"P{i}", stock=1)
    running = {"now": 0, "max": 0, "calls": 0}

    async def fake_predict(events, product_data, segment="individuo"):
        running["now"] += 1
        running["calls"] += 1
        running["max"] = max(running["max"], running["now"])
        await asyncio.sleep(0.01)
        running["now"] -= 1
        return {"daily_rate": 1.0, "days_until_stockout": 1}

    monkeypatch.setattr(products_api.ml_client, "predict", fake_predict)

    body = client.get(URL, headers=AUTH).json()

    assert len(body) == 20
    assert running["calls"] == 20
    assert 1 < running["max"] <= products_api._ML_CONCURRENCY


def test_reposicion_requires_a_token(client, db):
    from app.main import app
    from app.core.security import get_current_user

    override = app.dependency_overrides.pop(get_current_user)
    try:
        assert client.get(URL).status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = override
