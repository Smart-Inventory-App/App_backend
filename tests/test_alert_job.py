"""`run_daily_coverage_check`: el job que corre cada hora.

Abre su propia sesión con `SessionLocal()` en vez de recibir una por inyección
de dependencias, así que hay que apuntarla a la base de test (`use_test_db`)
para no intentar hablar con el Postgres de producción.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert import Alert
from app.models.product import Product
from app.models.profile import UserProfile
from app.models.user import AuthUser
from app.services import alert_job
from app.services.notifications import NotificationService
from tests.conftest import TestingSessionLocal


@pytest.fixture
def use_test_db(monkeypatch):
    monkeypatch.setattr(alert_job, "SessionLocal", TestingSessionLocal)


@pytest.fixture
def notifications(monkeypatch):
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
    def install(handler):
        def record(request: httpx.Request) -> httpx.Response:
            return handler(request)

        class FakeClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(record)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    return install


def make_user(db, firebase_token="tok", **profile_overrides):
    user_id = str(uuid.uuid4())
    user = AuthUser(id=uuid.UUID(user_id), email=f"{user_id}@test.com", hashed_password="x", firebase_token=firebase_token)
    db.add(user)
    if profile_overrides:
        db.add(UserProfile(user_id=user_id, **profile_overrides))
    db.commit()
    return user_id


async def test_no_products_means_nobody_gets_processed(db, use_test_db):
    result = await alert_job.run_daily_coverage_check(force=True)

    assert result == {"alerts_sent": 0, "users_processed": 0}


async def test_a_user_without_a_firebase_token_is_skipped(db, use_test_db):
    user_id = make_user(db, firebase_token=None)
    db.add(Product(user_id=user_id, nombre="X", categoria="C", stock=5))
    db.commit()

    result = await alert_job.run_daily_coverage_check(force=True)

    assert result["users_processed"] == 0


async def test_a_product_owned_by_a_non_uuid_is_skipped(db, use_test_db):
    db.add(Product(user_id="not-a-uuid", nombre="X", categoria="C", stock=5))
    db.commit()

    result = await alert_job.run_daily_coverage_check(force=True)

    assert result == {"alerts_sent": 0, "users_processed": 0}


async def test_without_force_only_the_users_matching_the_current_hour_run(db, use_test_db, notifications):
    current_hour = datetime.now(timezone.utc).hour
    other_hour = (current_hour + 1) % 24
    skipped = make_user(db, alert_check_hour=other_hour)
    matched = make_user(db, alert_check_hour=current_hour)
    db.add(Product(user_id=skipped, nombre="Salteado", categoria="C", stock=5))
    db.add(Product(user_id=matched, nombre="Procesado", categoria="C", stock=5))
    db.commit()

    result = await alert_job.run_daily_coverage_check(force=False)

    assert result["users_processed"] == 1


async def test_target_user_id_filters_out_the_rest(db, use_test_db, notifications):
    user_a = make_user(db)
    user_b = make_user(db)
    db.add(Product(user_id=user_a, nombre="A", categoria="C", stock=5))
    db.add(Product(user_id=user_b, nombre="B", categoria="C", stock=5))
    db.commit()

    result = await alert_job.run_daily_coverage_check(target_user_id=user_b, force=True)

    assert result["users_processed"] == 1


# ── vencimiento ────────────────────────────────────────────────────────────────

async def test_a_product_close_to_expiry_gets_an_alert_and_a_notification(db, use_test_db, notifications):
    user_id = make_user(db)
    product = Product(
        user_id=user_id, nombre="Yogur", categoria="Lacteo", stock=5,
        vencimiento=date.today() + timedelta(days=2),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    result = await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    assert result["alerts_sent"] == 1
    alert = db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "expiry").first()
    assert alert is not None
    assert alert.level == "warning"
    assert notifications[0]["title"] == "Producto próximo a vencerse"


async def test_a_product_expiring_tomorrow_gets_a_critical_alert(db, use_test_db, notifications):
    user_id = make_user(db)
    product = Product(
        user_id=user_id, nombre="Queso", categoria="Lacteo", stock=5,
        vencimiento=date.today() + timedelta(days=1),
    )
    db.add(product)
    db.commit()

    await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    alert = db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "expiry").first()
    assert alert.level == "critical"


# ── ML: cobertura baja y ritmo lento ──────────────────────────────────────────

async def test_low_stock_coverage_creates_an_alert_via_the_ml_service(db, use_test_db, notifications, ml_enabled, ml_transport):
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0, "days_until_stockout": 3}))
    user_id = make_user(db)
    product = Product(user_id=user_id, nombre="Arroz", categoria="Almacen", stock=10)
    db.add(product)
    db.commit()
    db.refresh(product)

    result = await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    assert result["alerts_sent"] == 1
    alert = db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "stock_low_coverage").first()
    assert alert is not None


async def test_slow_pace_alert_is_created_via_the_ml_service(db, use_test_db, notifications, ml_enabled, ml_transport):
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 0.5, "days_until_stockout": 20}))
    user_id = make_user(db)
    product = Product(
        user_id=user_id, nombre="Miel", categoria="Almacen", stock=9,
        vencimiento=date.today() + timedelta(days=5),
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    result = await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    assert result["alerts_sent"] >= 1
    alert = db.query(Alert).filter(Alert.product_id == product.id, Alert.type == "slow_pace").first()
    assert alert is not None


async def test_without_an_ml_url_no_coverage_alert_is_generated(db, use_test_db, notifications):
    user_id = make_user(db)
    product = Product(user_id=user_id, nombre="Sal", categoria="Almacen", stock=5)
    db.add(product)
    db.commit()

    result = await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    assert result["alerts_sent"] == 0


async def test_an_unreachable_ml_service_does_not_break_the_job(db, use_test_db, notifications, ml_enabled, monkeypatch):
    def down(request):
        raise httpx.ConnectError("down")

    class FakeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(down)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    user_id = make_user(db)
    product = Product(user_id=user_id, nombre="Fideos", categoria="Almacen", stock=5)
    db.add(product)
    db.commit()

    result = await alert_job.run_daily_coverage_check(target_user_id=user_id, force=True)

    assert result["alerts_sent"] == 0


async def test_an_unexpected_error_is_caught_and_reported_as_zero(db, use_test_db, monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(Session, "query", boom)

    result = await alert_job.run_daily_coverage_check(force=True)

    assert result == {"alerts_sent": 0, "users_processed": 0}
