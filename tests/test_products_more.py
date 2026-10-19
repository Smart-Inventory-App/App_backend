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


# ── entrada de stock de un producto existente ─────────────────────────────────

def test_restock_adds_stock_and_records_an_entry(client, db, no_alerts):
    product = add_product(db, nombre="Leche", stock=3)

    resp = client.post(f"/products/{product.id}/restock", json={"quantity": 5}, headers=AUTH)

    assert resp.status_code == 201
    assert resp.json()["stock"] == 8
    assert resp.json()["merged"] is True
    db.refresh(product)
    assert product.stock == 8
    event = db.query(ConsumptionEvent).filter(ConsumptionEvent.product_id == product.id).one()
    assert (event.event_type, event.quantity) == ("restocked", 5)


@pytest.mark.parametrize("quantity", [0, -2, 1000000])
def test_restock_rejects_an_invalid_quantity(client, db, no_alerts, quantity):
    product = add_product(db, stock=3)

    resp = client.post(f"/products/{product.id}/restock", json={"quantity": quantity}, headers=AUTH)

    assert resp.status_code == 422
    db.refresh(product)
    assert product.stock == 3


def test_restock_rejects_a_stock_beyond_the_limit(client, db, no_alerts):
    product = add_product(db, stock=999999)

    resp = client.post(f"/products/{product.id}/restock", json={"quantity": 1}, headers=AUTH)

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Cantidad inválida"


def test_restock_of_a_product_that_is_not_the_users_is_a_404(client, db, no_alerts):
    other = add_product(db, user_id="00000000-0000-0000-0000-00000000dead")

    resp = client.post(f"/products/{other.id}/restock", json={"quantity": 1}, headers=AUTH)

    assert resp.status_code == 404


def test_restock_checks_the_alerts_of_the_product(client, db, monkeypatch):
    calls = []

    async def record(product, user, profile, db, stock_increased=False):
        calls.append((product.id, stock_increased))
        return {"days_until_stockout": 1}

    sent = []

    async def understock(token, product, days, email):
        sent.append(days)

    monkeypatch.setattr(products_api, "_check_product_state", record)
    monkeypatch.setattr(products_api, "_notificate_understock", understock)
    product = add_product(db, stock=1)

    resp = client.post(f"/products/{product.id}/restock", json={"quantity": 1}, headers=AUTH)

    assert resp.status_code == 201
    assert calls == [(product.id, True)]
    assert sent == [1]


def test_restock_notifies_when_the_new_stock_is_too_much(client, db, monkeypatch):
    async def far(product, user, profile, db, stock_increased=False):
        return {"days_until_stockout": 10_000}

    sent = []

    async def overstock(token, product, days, email):
        sent.append(days)

    monkeypatch.setattr(products_api, "_check_product_state", far)
    monkeypatch.setattr(products_api, "_notificate_overstock", overstock)
    product = add_product(db, stock=1)

    client.post(f"/products/{product.id}/restock", json={"quantity": 1}, headers=AUTH)

    assert sent == [10_000]


# ── motivos de salida: vendido y alquilado ────────────────────────────────────

@pytest.mark.parametrize("event_type", ["sold", "rented"])
def test_a_sale_or_a_rental_lowers_the_stock_and_is_recorded_with_its_type(client, db, no_alerts, event_type):
    product = add_product(db, stock=10)

    resp = client.post(f"/products/{product.id}/events", json={"event_type": event_type, "quantity": 4}, headers=AUTH)

    assert resp.status_code == 201
    assert resp.json() == {"event_type": event_type, "quantity": 4, "remaining_stock": 6}
    assert db.query(ConsumptionEvent).one().event_type == event_type


def test_an_unknown_kind_of_exit_is_rejected(client, db, no_alerts):
    product = add_product(db, stock=10)

    resp = client.post(f"/products/{product.id}/events", json={"event_type": "stolen", "quantity": 1}, headers=AUTH)

    assert resp.status_code == 422


def test_a_movement_can_be_corrected_into_a_sale(client, db, no_alerts):
    product = add_product(db, stock=10)
    client.post(f"/products/{product.id}/events", json={"event_type": "consumed", "quantity": 4}, headers=AUTH)
    event = db.query(ConsumptionEvent).one()

    resp = client.put(
        f"/products/{product.id}/events/{event.id}",
        json={"event_type": "sold", "quantity": 4},
        headers=AUTH,
    )

    assert resp.status_code == 200


# ── listado: orden alfabético y por vencimiento ───────────────────────────────

NAMES = ["bruno", "Ana", "carlos", "Álvaro", "ñandú", "Nube", "oso", "Zeta"]
ALPHABETICAL = ["Álvaro", "Ana", "bruno", "carlos", "Nube", "ñandú", "oso", "Zeta"]


def names_sorted(client, direction):
    resp = client.get("/products/", params={"sort_by": "nombre", "sort_dir": direction}, headers=AUTH)
    return [p["nombre"] for p in resp.json()]


def test_sort_by_nombre_ascending_is_alphabetical_ignoring_case_and_accents(client, db, no_alerts):
    for name in NAMES:
        add_product(db, nombre=name)

    assert names_sorted(client, "asc") == ALPHABETICAL


def test_sort_by_nombre_descending_is_the_exact_reverse(client, db, no_alerts):
    for name in NAMES:
        add_product(db, nombre=name)

    assert names_sorted(client, "desc") == list(reversed(ALPHABETICAL))


def test_sort_by_nombre_does_not_put_every_capital_letter_first(client, db, no_alerts):
    for name in ["banana", "Cereal", "arroz", "Dulce"]:
        add_product(db, nombre=name)

    assert names_sorted(client, "asc") == ["arroz", "banana", "Cereal", "Dulce"]


def test_sort_by_nombre_is_stable_for_names_that_differ_only_in_case(client, db, no_alerts):
    first = add_product(db, nombre="leche")
    second = add_product(db, nombre="Leche")

    asc = [p["id"] for p in client.get("/products/", params={"sort_by": "nombre"}, headers=AUTH).json()]

    assert asc == [second.id, first.id]


def test_sort_by_nombre_keeps_the_search_and_category_filters(client, db, no_alerts):
    add_product(db, nombre="Leche", categoria="Lacteos")
    add_product(db, nombre="Yogur", categoria="Lacteos")
    add_product(db, nombre="Arroz", categoria="Almacen")

    resp = client.get("/products/", params={"sort_by": "nombre", "categoria": "lacteos"}, headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == ["Leche", "Yogur"]


def test_sort_by_nombre_only_lists_the_users_own_products(client, db, no_alerts):
    add_product(db, nombre="Mio")
    add_product(db, nombre="Ajeno", user_id="00000000-0000-0000-0000-00000000dead")

    assert names_sorted(client, "asc") == ["Mio"]


@pytest.mark.parametrize("direction, expected", [("asc", ["Viejo", "Medio", "Nuevo"]), ("desc", ["Nuevo", "Medio", "Viejo"])])
def test_sort_by_vencimiento_hides_products_without_an_expiry_date(client, db, no_alerts, direction, expected):
    add_product(db, nombre="Medio", vencimiento=date(2027, 6, 1))
    add_product(db, nombre="Sin fecha", vencimiento=None)
    add_product(db, nombre="Nuevo", vencimiento=date(2028, 1, 1))
    add_product(db, nombre="Viejo", vencimiento=date(2026, 12, 1))

    resp = client.get("/products/", params={"sort_by": "vencimiento", "sort_dir": direction}, headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == expected


def test_without_a_sort_the_products_without_an_expiry_date_are_still_listed(client, db, no_alerts):
    add_product(db, nombre="Con fecha", vencimiento=date(2027, 6, 1))
    add_product(db, nombre="Sin fecha", vencimiento=None)

    resp = client.get("/products/", headers=AUTH)

    assert {p["nombre"] for p in resp.json()} == {"Con fecha", "Sin fecha"}


def test_sorting_by_other_fields_still_lists_the_products_without_an_expiry_date(client, db, no_alerts):
    add_product(db, nombre="Con fecha", vencimiento=date(2027, 6, 1), stock=1)
    add_product(db, nombre="Sin fecha", vencimiento=None, stock=2)

    resp = client.get("/products/", params={"sort_by": "stock", "sort_dir": "desc"}, headers=AUTH)

    assert [p["nombre"] for p in resp.json()] == ["Sin fecha", "Con fecha"]


# ── stock total de un mismo producto (mismo nombre y categoría) ───────────────

def lots(db):
    """Tres lotes de la misma leche, una leche de otra marca (que también cuenta) y productos que no son lo mismo."""
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=4, vencimiento=date(2027, 3, 1), ubicacion="Heladera")
    add_product(db, nombre="leche", marca="SER", categoria="lacteos", stock=6, vencimiento=date(2027, 1, 1), ubicacion="Freezer")
    add_product(db, nombre="  Leche ", marca="Ser", categoria="Lacteos", stock=2, vencimiento=None, codigo_barras=None)
    add_product(db, nombre="Leche", marca="Otra", categoria="Lacteos", stock=50)
    add_product(db, nombre="Leche", marca="Ser", categoria="Almacen", stock=70)
    add_product(db, nombre="Leche entera", marca="Ser", categoria="Lacteos", stock=90)


def get_group(client, **params):
    return client.get("/products/group", params=params, headers=AUTH)


def test_a_group_adds_up_the_stock_of_every_product_with_the_same_name_and_category(client, db, no_alerts):
    lots(db)

    body = get_group(client, nombre="Leche", categoria="Lacteos").json()

    assert body["stock_total"] == 62
    assert body["lotes"] == 4
    assert len(body["productos"]) == 4


def test_the_brand_does_not_split_a_group(client, db, no_alerts):
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=1)
    add_product(db, nombre="Leche", marca="Otra", categoria="Lacteos", stock=2)
    add_product(db, nombre="Leche", marca=None, categoria="Lacteos", stock=4)

    body = get_group(client, nombre="Leche", categoria="Lacteos").json()

    assert body["stock_total"] == 7
    assert {p["marca"] for p in body["productos"]} == {"Ser", "Otra", None}
    assert "marca" not in body


def test_a_different_category_is_a_different_group(client, db, no_alerts):
    lots(db)

    assert get_group(client, nombre="Leche", categoria="Almacen").json()["stock_total"] == 70


def test_the_group_ignores_case_accents_and_extra_spaces(client, db, no_alerts):
    add_product(db, nombre="Café", marca="Marca", categoria="Almacén", stock=2)
    add_product(db, nombre="cafe ", marca="otra", categoria="almacen", stock=3)

    body = get_group(client, nombre="CAFÉ", categoria="Almacen").json()

    assert body["stock_total"] == 5


def test_the_products_come_ordered_by_expiry_with_the_ones_that_do_not_expire_last(client, db, no_alerts):
    lots(db)

    body = get_group(client, nombre="Leche", categoria="Lacteos").json()

    assert [p["vencimiento"] for p in body["productos"]][:3] == ["2027-01-01", "2027-03-01", None]
    assert body["productos"][3]["vencimiento"] is None


def test_the_group_reports_the_nearest_expiry_of_the_products_that_still_have_stock(client, db, no_alerts):
    add_product(db, nombre="Yogur", marca="Ser", categoria="Lacteos", stock=0, vencimiento=date(2026, 1, 1))
    add_product(db, nombre="Yogur", marca="Ser", categoria="Lacteos", stock=3, vencimiento=date(2027, 5, 1))

    body = get_group(client, nombre="Yogur", categoria="Lacteos").json()

    assert body["proximo_vencimiento"] == "2027-05-01"
    assert body["stock_total"] == 3
    assert body["lotes"] == 2


def test_an_unknown_group_is_a_404(client, db, no_alerts):
    lots(db)

    assert get_group(client, nombre="Pan", categoria="Lacteos").status_code == 404


def test_the_group_never_includes_other_users_products(client, db, no_alerts):
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=1)
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=100, user_id="00000000-0000-0000-0000-00000000dead")

    body = get_group(client, nombre="Leche", categoria="Lacteos").json()

    assert body["stock_total"] == 1


def test_the_group_requires_a_name_and_a_category(client, db, no_alerts):
    assert client.get("/products/group", params={"categoria": "Lacteos"}, headers=AUTH).status_code == 422
    assert client.get("/products/group", params={"nombre": "Leche"}, headers=AUTH).status_code == 422


def test_group_suggestions_list_each_name_and_category_once_with_its_total(client, db, no_alerts):
    lots(db)

    resp = client.get("/products/groups", params={"q": "lec"}, headers=AUTH)

    summary = {(g["nombre"], g["categoria"]): g["stock_total"] for g in resp.json()}
    assert summary[("Leche", "Lacteos")] == 62
    assert summary[("Leche", "Almacen")] == 70
    assert summary[("Leche entera", "Lacteos")] == 90
    assert len(summary) == 3
    assert all("marca" not in g for g in resp.json())


def test_group_suggestions_ignore_case_and_accents_when_searching(client, db, no_alerts):
    add_product(db, nombre="Café molido", marca="Marca", categoria="Almacen", stock=2)

    assert [g["nombre"] for g in client.get("/products/groups", params={"q": "CAFE"}, headers=AUTH).json()] == ["Café molido"]
    assert [g["nombre"] for g in client.get("/products/groups", params={"q": "molido"}, headers=AUTH).json()] == ["Café molido"]


def test_the_search_does_not_look_at_the_brand(client, db, no_alerts):
    add_product(db, nombre="Galletitas", marca="Terrabusi", categoria="Almacen", stock=2)

    assert client.get("/products/groups", params={"q": "terrabusi"}, headers=AUTH).json() == []


def test_group_suggestions_are_alphabetical_and_limited_to_ten(client, db, no_alerts):
    for i in range(12):
        add_product(db, nombre=f"Item {i:02d}", marca="M", categoria="C", stock=1)

    names = [g["nombre"] for g in client.get("/products/groups", params={"q": "item"}, headers=AUTH).json()]

    assert names == [f"Item {i:02d}" for i in range(10)]


def test_group_suggestions_sum_every_product_even_when_only_some_match_the_search_text(client, db, no_alerts):
    add_product(db, nombre="Léche", marca="Ser", categoria="Lacteos", stock=1)
    add_product(db, nombre="Leche", marca="Otra", categoria="Lacteos", stock=2)

    body = client.get("/products/groups", params={"q": "léche"}, headers=AUTH).json()

    assert len(body) == 1
    assert body[0]["stock_total"] == 3


def test_group_suggestions_find_nothing_for_an_unknown_name_or_a_blank_search(client, db, no_alerts):
    lots(db)

    assert client.get("/products/groups", params={"q": "zzz"}, headers=AUTH).json() == []
    assert client.get("/products/groups", params={"q": "   "}, headers=AUTH).json() == []


def test_group_suggestions_only_include_the_users_products(client, db, no_alerts):
    add_product(db, nombre="Ajeno", marca="M", categoria="C", user_id="00000000-0000-0000-0000-00000000dead")

    assert client.get("/products/groups", params={"q": "ajeno"}, headers=AUTH).json() == []


def test_group_suggestions_require_a_search_text(client, db, no_alerts):
    assert client.get("/products/groups", headers=AUTH).status_code == 422
