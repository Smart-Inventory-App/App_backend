"""Ramas de `app/api/scan.py` que `test_scan.py` y `test_scan_matching.py` no
ejercitan: el 503 de consultar un job caído, el archivo que excede el tamaño
máximo, un error de base de datos a mitad de una salida por comprobante, y el
best-effort de las alertas cuando el usuario no tiene fila en `auth_users`."""
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import scan as scan_api
from app.models.product import Product
from app.services import ocr_client
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def add_product(db, **overrides):
    data = dict(user_id=TEST_USER_ID, nombre="Leche", categoria="Lacteo", stock=10)
    data.update(overrides)
    product = Product(**data)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def test_get_scan_returns_503_when_the_coordinator_is_down(client, monkeypatch):
    async def down(job_id, token):
        raise ocr_client.OCRUnavailable("caído")

    monkeypatch.setattr(ocr_client, "get_job", down)

    resp = client.get("/products/scan/job-1", headers=AUTH)

    assert resp.status_code == 503


def test_a_file_over_the_size_limit_is_rejected(client):
    big = b"\xff\xd8" + b"0" * (scan_api.MAX_BYTES + 1)

    resp = client.post(
        "/products/scan",
        files={"file": ("grande.jpg", big, "image/jpeg")},
        headers=AUTH,
    )

    assert resp.status_code == 413


def test_salida_reports_a_db_error_without_aborting_the_rest_of_the_batch(client, db, monkeypatch):
    leche = add_product(db, nombre="Leche", stock=10)
    yogur = add_product(db, nombre="Yogur", stock=5)

    original_commit = Session.commit
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SQLAlchemyError("db down")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", flaky)

    resp = client.post(
        "/products/scan/salida",
        json={"items": [{"product_id": leche.id, "quantity": 1}, {"product_id": yogur.id, "quantity": 1}]},
        headers=AUTH,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["procesados"] == 1
    assert body["fallidos"] == 1


def test_salida_skips_alerts_gracefully_when_the_caller_has_no_auth_users_row(client, db, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app

    ghost = {"sub": "not-a-uuid", "email": "g@test.com"}
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: ghost)
    leche = add_product(db, user_id="not-a-uuid", nombre="Leche", stock=10)

    resp = client.post(
        "/products/scan/salida",
        json={"items": [{"product_id": leche.id, "quantity": 1}]},
        headers=AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["procesados"] == 1
