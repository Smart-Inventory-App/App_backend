"""Endpoints internos (`/internal/*`), usados por el servicio de ML y por el
disparador manual de alertas. Se autentican con un token compartido, no con
el JWT de usuario."""
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import UserProfile
from app.services import alert_job
from tests.conftest import TEST_USER_ID, TestingSessionLocal

TOKEN = {"X-Internal-Token": "test-internal-token"}


def test_missing_token_is_forbidden(client, db):
    resp = client.get("/internal/consumption")

    assert resp.status_code == 403


def test_wrong_token_is_forbidden(client, db):
    resp = client.get("/internal/consumption", headers={"X-Internal-Token": "nope"})

    assert resp.status_code == 403


def test_get_all_consumption_lists_every_users_events(client, db):
    product = Product(user_id=TEST_USER_ID, nombre="X", categoria="C", stock=5)
    db.add(product)
    db.commit()
    db.refresh(product)
    db.add(ConsumptionEvent(product_id=product.id, user_id=TEST_USER_ID, quantity=2, event_type="consumed"))
    db.commit()

    resp = client.get("/internal/consumption", headers=TOKEN)

    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_all_products_includes_the_users_segment(client, db):
    db.add(Product(user_id=TEST_USER_ID, nombre="X", categoria="C", stock=5))
    db.add(UserProfile(user_id=TEST_USER_ID, user_type="comercio"))
    db.commit()

    resp = client.get("/internal/products", headers=TOKEN)

    body = resp.json()
    assert len(body) == 1
    assert body[0]["user_type"] == "comercio"


def test_get_all_products_defaults_the_segment_when_theres_no_profile(client, db):
    db.add(Product(user_id=TEST_USER_ID, nombre="X", categoria="C", stock=5))
    db.commit()

    resp = client.get("/internal/products", headers=TOKEN)

    assert resp.json()[0]["user_type"] == "individuo"


def test_trigger_alerts_for_everyone(client, db, monkeypatch):
    monkeypatch.setattr(alert_job, "SessionLocal", TestingSessionLocal)

    resp = client.post("/internal/alerts/run", headers=TOKEN)

    assert resp.status_code == 200
    assert "alerts_sent" in resp.json()


def test_trigger_alerts_for_one_user(client, db, monkeypatch):
    monkeypatch.setattr(alert_job, "SessionLocal", TestingSessionLocal)

    resp = client.post(f"/internal/alerts/run/{TEST_USER_ID}", headers=TOKEN)

    assert resp.status_code == 200
    assert "alerts_sent" in resp.json()


def test_internal_endpoints_reject_a_missing_token_too(client, db, monkeypatch):
    monkeypatch.setattr(alert_job, "SessionLocal", TestingSessionLocal)

    resp = client.post("/internal/alerts/run")

    assert resp.status_code == 403
