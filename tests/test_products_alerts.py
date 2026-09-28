"""Evaluación de alertas de `_check_product_state`: vencimiento y, con el
servicio de ML configurado, cobertura baja / exceso de stock / ritmo lento."""
from datetime import date, timedelta
import httpx
import pytest

from app.api import products as products_api
from app.core.config import settings
from app.models.alert import Alert
from app.services.notifications import NotificationService
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


@pytest.fixture
def notifications(monkeypatch):
    """Registra las notificaciones que se hubieran mandado, sin pegarle a la red."""
    sent = []

    def fake_send(self, token, title, body, email):
        sent.append({"token": token, "title": title, "body": body, "email": email})
        return 200

    monkeypatch.setattr(NotificationService, "send_notification", fake_send)
    return sent


@pytest.fixture
def ml_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ML_SERVICE_URL", "http://ml:9000")


@pytest.fixture
def ml_transport(monkeypatch):
    """Reemplaza el httpx.AsyncClient que usa `_check_product_state` para hablar con el ML."""

    def install(handler):
        def record(request: httpx.Request) -> httpx.Response:
            return handler(request)

        class FakeClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(record)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    return install


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


def test_an_unreachable_ml_service_is_ignored(client, db, notifications, ml_enabled, monkeypatch):
    product = create(client, nombre="Azucar", stock=5)

    class BoomClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("el ML no responde")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)

    resp = client.put(f"/products/{product['id']}", json={"stock": 4}, headers=AUTH)

    assert resp.status_code == 200


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
