"""Endpoints de productos que no tocan `test_auth.py`, `test_barcode.py` ni
`test_scan_matching.py`: filtros, orden, sugerencias, defaults, historial de
consumo y sus correcciones/anulaciones."""
from datetime import date, timedelta

import pytest

from app.api import products as products_api
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}


def add_product(db, **overrides):
    data = dict(user_id=TEST_USER_ID, nombre="Producto", categoria="General", stock=10)
    data.update(overrides)
    product = Product(**data)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@pytest.fixture
def no_alerts(monkeypatch):
    """Evita que estos tests, que no miran alertas, salgan a la red del ML."""

    async def skip(*args, **kwargs):
        return None

    monkeypatch.setattr(products_api, "_check_product_state", skip)


# ── listado: orden ────────────────────────────────────────────────────────────

def test_list_products_sorted_desc_by_stock(client, db, no_alerts):
    add_product(db, nombre="A", stock=1)
    add_product(db, nombre="B", stock=5)

    resp = client.get("/products/", params={"sort_by": "stock", "sort_dir": "desc"}, headers=AUTH)

    assert [p["stock"] for p in resp.json()] == [5, 1]


def test_list_products_sorted_asc_by_nombre(client, db, no_alerts):
    add_product(db, nombre="Zeta")
    add_product(db, nombre="Alfa")

    resp = client.get("/products/", params={"sort_by": "nombre", "sort_dir": "asc"}, headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == ["Alfa", "Zeta"]


# ── filtros disponibles y sugerencias ─────────────────────────────────────────

def test_filter_options_lists_distinct_non_empty_values(client, db, no_alerts):
    add_product(db, categoria="Lacteo", ubicacion="Heladera", marca="Ser")
    add_product(db, categoria="Limpieza", ubicacion="Deposito", marca=None)

    resp = client.get("/products/filters/options", headers=AUTH)

    body = resp.json()
    assert body["categorias"] == ["Lacteo", "Limpieza"]
    assert body["ubicaciones"] == ["Deposito", "Heladera"]
    assert body["marcas"] == ["Ser"]


def test_suggest_products_matches_a_partial_name(client, db, no_alerts):
    add_product(db, nombre="Yogur Ser")
    add_product(db, nombre="Detergente")

    resp = client.get("/products/suggest", params={"q": "yog"}, headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == ["Yogur Ser"]


# ── código de barras: caso "no hay código" ────────────────────────────────────

def test_by_barcode_with_a_blank_code_returns_null_not_422(client, db):
    resp = client.get("/products/by-barcode/%20", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() is None


# ── defaults del alta ─────────────────────────────────────────────────────────

def test_defaults_without_a_profile_are_empty(client, db):
    resp = client.get("/products/defaults", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"last_categoria": None, "last_ubicacion": None}


def test_defaults_after_a_create_reflect_the_last_choice(client, db, no_alerts):
    client.post(
        "/products/",
        json={"nombre": "X", "categoria": "Bebidas", "stock": 1, "ubicacion": "Alacena"},
        headers=AUTH,
    )

    resp = client.get("/products/defaults", headers=AUTH)

    assert resp.json() == {"last_categoria": "Bebidas", "last_ubicacion": "Alacena"}


# ── vencidos ───────────────────────────────────────────────────────────────────

def test_expired_products_excludes_the_ones_with_no_stock_left(client, db, no_alerts):
    add_product(db, nombre="Vencido", vencimiento=date.today() - timedelta(days=1), stock=2)
    add_product(db, nombre="VencidoSinStock", vencimiento=date.today() - timedelta(days=1), stock=0)
    add_product(db, nombre="Vigente", vencimiento=date.today() + timedelta(days=5), stock=2)

    resp = client.get("/products/expired", headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == ["Vencido"]


# ── historial de consumo ───────────────────────────────────────────────────────

def test_consumption_history_marks_which_events_were_reversed(client, db, no_alerts):
    product = add_product(db, stock=10)
    original = ConsumptionEvent(product_id=product.id, user_id=product.user_id, quantity=3, event_type="consumed")
    db.add(original)
    db.commit()
    db.refresh(original)
    reversal = ConsumptionEvent(
        product_id=product.id, user_id=product.user_id, quantity=3,
        event_type="restocked", reverses_event_id=original.id,
    )
    db.add(reversal)
    db.commit()

    resp = client.get(f"/products/{product.id}/consumption", headers=AUTH)

    flags = {e["id"]: e["reversed"] for e in resp.json()}
    assert flags[original.id] is True
    assert flags[reversal.id] is False


# ── registrar un consumo/vencimiento ──────────────────────────────────────────

def test_register_event_consumed_reduces_stock(client, db, no_alerts):
    product = add_product(db, stock=10)

    resp = client.post(
        f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 3}, headers=AUTH
    )

    assert resp.status_code == 201
    assert resp.json()["remaining_stock"] == 7


def test_register_event_rejects_more_than_the_available_stock(client, db, no_alerts):
    product = add_product(db, stock=2)

    resp = client.post(
        f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 5}, headers=AUTH
    )

    assert resp.status_code == 422


# ── corregir un consumo ya cargado ────────────────────────────────────────────

def _latest_event(db, product_id):
    return (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.product_id == product_id)
        .order_by(ConsumptionEvent.id.desc())
        .first()
    )


def test_correcting_an_event_adjusts_stock_by_the_difference(client, db, no_alerts):
    product = add_product(db, stock=10)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 3}, headers=AUTH)
    event = _latest_event(db, product.id)

    resp = client.put(
        f"/products/{product.id}/events/{event.id}",
        json={"event_type": "consumed", "quantity": 5},
        headers=AUTH,
    )

    assert resp.status_code == 200
    assert resp.json()["remaining_stock"] == 5


def test_correcting_a_correction_itself_is_rejected(client, db, no_alerts):
    product = add_product(db, stock=10)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 3}, headers=AUTH)
    original = _latest_event(db, product.id)
    client.put(
        f"/products/{product.id}/events/{original.id}",
        json={"event_type": "consumed", "quantity": 2},
        headers=AUTH,
    )
    reversal = (
        db.query(ConsumptionEvent)
        .filter(ConsumptionEvent.reverses_event_id == original.id)
        .first()
    )

    resp = client.put(
        f"/products/{product.id}/events/{reversal.id}",
        json={"event_type": "consumed", "quantity": 1},
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert "ya es una corrección" in resp.json()["detail"]


def test_correcting_the_same_event_twice_is_rejected(client, db, no_alerts):
    product = add_product(db, stock=10)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 3}, headers=AUTH)
    event = _latest_event(db, product.id)
    client.put(
        f"/products/{product.id}/events/{event.id}",
        json={"event_type": "consumed", "quantity": 2},
        headers=AUTH,
    )

    resp = client.put(
        f"/products/{product.id}/events/{event.id}",
        json={"event_type": "consumed", "quantity": 1},
        headers=AUTH,
    )

    assert resp.status_code == 400


def test_correcting_an_event_that_would_leave_negative_stock_is_rejected(client, db, no_alerts):
    product = add_product(db, stock=3)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 3}, headers=AUTH)
    event = _latest_event(db, product.id)

    resp = client.put(
        f"/products/{product.id}/events/{event.id}",
        json={"event_type": "expired", "quantity": 100},
        headers=AUTH,
    )

    assert resp.status_code == 422


def test_correcting_an_unknown_event_is_404(client, db, no_alerts):
    product = add_product(db, stock=5)

    resp = client.put(
        f"/products/{product.id}/events/99999",
        json={"event_type": "consumed", "quantity": 1},
        headers=AUTH,
    )

    assert resp.status_code == 404


# ── deshacer un consumo cargado por error ─────────────────────────────────────

def test_deleting_an_event_reverts_its_effect_on_stock(client, db, no_alerts):
    product = add_product(db, stock=10)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 4}, headers=AUTH)
    event = _latest_event(db, product.id)

    resp = client.delete(f"/products/{product.id}/events/{event.id}", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["remaining_stock"] == 10


def test_deleting_an_event_that_would_leave_negative_stock_is_rejected(client, db, no_alerts):
    product = add_product(db, stock=3)
    # Un "restocked" no se puede cargar por `/events` (sólo consumed/expired);
    # se inserta directo para simular el caso que el endpoint tiene que rechazar.
    event = ConsumptionEvent(product_id=product.id, user_id=product.user_id, quantity=5, event_type="restocked")
    db.add(event)
    db.commit()
    db.refresh(event)

    resp = client.delete(f"/products/{product.id}/events/{event.id}", headers=AUTH)

    assert resp.status_code == 422


# ── fallas de la base al confirmar un alta ────────────────────────────────────

def _flaky_commit(monkeypatch, fail_on_call):
    """Deja pasar los primeros commits y hace fallar uno puntual, para forzar
    la rama `except` sin tocar las escrituras que no nos interesan probar."""
    from sqlalchemy.orm import Session

    original_commit = Session.commit
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        if calls["n"] == fail_on_call:
            raise Exception("no se pudo escribir en la base")
        return original_commit(self)

    monkeypatch.setattr(Session, "commit", flaky)


def test_create_reports_422_when_the_final_commit_fails(client, db, monkeypatch, no_alerts):
    # Sin perfil todavía: el primer commit crea el `UserProfile`, el segundo
    # guarda `last_categoria`/`last_ubicacion` (no está protegido, tiene que
    # pasar), y el tercero es el alta en sí, al que le hacemos fallar la
    # escritura.
    _flaky_commit(monkeypatch, fail_on_call=3)

    resp = client.post("/products/", json={"nombre": "Nuevo", "categoria": "Cat", "stock": 1}, headers=AUTH)

    assert resp.status_code == 422


def test_merge_reports_422_when_the_final_commit_fails(client, db, monkeypatch, no_alerts):
    create_resp = client.post("/products/", json={"nombre": "Yerba", "categoria": "Cat", "stock": 5}, headers=AUTH)
    assert create_resp.status_code == 201

    # El alta de arriba ya dejó el perfil creado, así que ahora el único commit
    # de `_get_or_create_profile`/la actualización de últimos valores es el
    # primero; el segundo es la fusión de stock, que es la que probamos.
    _flaky_commit(monkeypatch, fail_on_call=2)

    resp = client.post("/products/", json={"nombre": "Yerba", "categoria": "Cat", "stock": 5}, headers=AUTH)

    assert resp.status_code == 422
