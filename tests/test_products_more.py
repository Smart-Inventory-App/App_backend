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


# ── listado paginado ──────────────────────────────────────────────────────────

def names(client, **params):
    return [p["nombre"] for p in client.get("/products/", params=params, headers=AUTH).json()]


def many_products(db, count=25):
    for i in range(count):
        add_product(db, nombre=f"Producto {i:02d}", categoria="Almacen" if i % 2 == 0 else "Lacteos", stock=i)


def test_without_a_limit_the_list_has_every_product(client, db, no_alerts):
    many_products(db)

    assert len(names(client)) == 25


def test_a_limit_gives_the_first_page(client, db, no_alerts):
    many_products(db)

    first = names(client, sort_by="nombre", limit=20)

    assert first == [f"Producto {i:02d}" for i in range(20)]


def test_an_offset_gives_the_following_pages_without_repeating_or_skipping(client, db, no_alerts):
    many_products(db)

    first = names(client, sort_by="nombre", limit=20)
    second = names(client, sort_by="nombre", limit=10, offset=20)

    assert second == [f"Producto {i:02d}" for i in range(20, 25)]
    assert first + second == names(client, sort_by="nombre")


@pytest.mark.parametrize("sort_by", [None, "stock", "categoria", "vencimiento", "nombre"])
@pytest.mark.parametrize("sort_dir", ["asc", "desc"])
def test_pages_add_up_to_the_whole_list_for_every_order(client, db, no_alerts, sort_by, sort_dir):
    for i in range(23):
        add_product(db, nombre=f"P{i:02d}", categoria="Igual", stock=i % 3, vencimiento=date(2027, 1, 1 + i % 5))
    params = {"sort_dir": sort_dir, **({"sort_by": sort_by} if sort_by else {})}
    everything = [p["id"] for p in client.get("/products/", params=params, headers=AUTH).json()]

    pages = []
    offset = 0
    while True:
        page = [p["id"] for p in client.get("/products/", params={**params, "limit": 10, "offset": offset}, headers=AUTH).json()]
        if not page:
            break
        pages += page
        offset += 10

    assert pages == everything
    assert len(set(pages)) == len(pages) == 23


def test_the_pages_respect_the_filters_and_the_search(client, db, no_alerts):
    many_products(db)

    first = names(client, categoria="almacen", sort_by="nombre", limit=5)
    rest = names(client, categoria="almacen", sort_by="nombre", limit=50, offset=5)

    assert len(first) == 5 and all(int(n[-2:]) % 2 == 0 for n in first + rest)
    assert len(first + rest) == 13
    assert names(client, search="Producto 0", sort_by="nombre", limit=3) == ["Producto 00", "Producto 01", "Producto 02"]


def test_an_offset_beyond_the_end_gives_an_empty_page(client, db, no_alerts):
    many_products(db, count=3)

    assert names(client, limit=10, offset=50) == []


def test_the_limit_and_the_offset_are_validated(client, db, no_alerts):
    assert client.get("/products/", params={"limit": 0}, headers=AUTH).status_code == 422
    assert client.get("/products/", params={"limit": 201}, headers=AUTH).status_code == 422
    assert client.get("/products/", params={"offset": -1}, headers=AUTH).status_code == 422


def test_the_default_order_is_newest_first_and_stays_stable_between_pages(client, db, no_alerts):
    many_products(db, count=6)

    everything = names(client)
    assert names(client, limit=4) + names(client, limit=4, offset=4) == everything
    assert everything[0] == "Producto 05"


def test_the_pages_only_have_the_users_own_products(client, db, no_alerts):
    many_products(db, count=3)
    add_product(db, nombre="Ajeno", user_id="00000000-0000-0000-0000-00000000dead")

    assert "Ajeno" not in names(client, limit=50)


# ── stock total del inventario (con los mismos filtros que la lista) ───────────

def stock_total(client, **params):
    return client.get("/products/stock-total", params=params, headers=AUTH)


def inventory(db):
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=4, ubicacion="Heladera")
    add_product(db, nombre="Yogur", marca="Leches del Sur", categoria="Lacteos", stock=6, ubicacion="Freezer")
    add_product(db, nombre="Arroz", marca="Gallo", categoria="Almacen", stock=10, ubicacion="Alacena")
    add_product(db, nombre="Fideos", marca="Matarazzo", categoria="Almacen", stock=20, ubicacion=None)


def test_the_stock_total_adds_up_every_product_of_the_user(client, db, no_alerts):
    inventory(db)
    assert stock_total(client).json() == {"stock_total": 40, "products": 4}


def test_the_stock_total_of_an_empty_inventory_is_zero(client, db, no_alerts):
    assert stock_total(client).json() == {"stock_total": 0, "products": 0}


def test_the_stock_total_searches_by_name_or_brand_like_the_list(client, db, no_alerts):
    inventory(db)
    # «lech» está en el nombre de la leche y en la marca del yogur
    assert stock_total(client, search="lech").json() == {"stock_total": 10, "products": 2}
    assert stock_total(client, search="Gallo").json() == {"stock_total": 10, "products": 1}
    assert stock_total(client, search="zzz").json() == {"stock_total": 0, "products": 0}


def test_the_stock_total_filters_by_category_and_location(client, db, no_alerts):
    inventory(db)
    assert stock_total(client, categoria="Almacen").json() == {"stock_total": 30, "products": 2}
    assert stock_total(client, ubicacion="Freezer").json() == {"stock_total": 6, "products": 1}
    assert stock_total(client, categoria="lacteos", ubicacion="heladera").json() == {"stock_total": 4, "products": 1}
    assert stock_total(client, categoria="Almacen", ubicacion="Freezer").json() == {"stock_total": 0, "products": 0}


def test_the_stock_total_matches_exactly_what_the_list_returns_with_the_same_filters(client, db, no_alerts):
    inventory(db)
    for filters in ({}, {"search": "lech"}, {"categoria": "Almacen"}, {"search": "a", "ubicacion": "Alacena"}):
        listed = client.get("/products/", params=filters, headers=AUTH).json()
        total = stock_total(client, **filters).json()
        assert total == {"stock_total": sum(p["stock"] for p in listed), "products": len(listed)}


def test_the_stock_total_counts_all_the_products_not_only_a_page(client, db, no_alerts):
    for index in range(25):
        add_product(db, nombre=f"Item {index}", categoria="General", stock=2)
    page = client.get("/products/", params={"limit": 20}, headers=AUTH).json()
    assert len(page) == 20
    assert stock_total(client).json() == {"stock_total": 50, "products": 25}


def test_the_stock_total_never_includes_other_users_products(client, db, no_alerts):
    add_product(db, nombre="Mio", categoria="C", stock=3)
    add_product(db, nombre="Ajeno", categoria="C", stock=99, user_id="00000000-0000-0000-0000-00000000dead")
    assert stock_total(client).json() == {"stock_total": 3, "products": 1}


def test_the_stock_total_reflects_the_changes_of_the_inventory(client, db, no_alerts):
    inventory(db)
    created = client.post("/products/", json={"nombre": "Nuevo", "categoria": "Almacen", "stock": 5}, headers=AUTH).json()
    assert stock_total(client).json() == {"stock_total": 45, "products": 5}
    client.delete(f"/products/{created['id']}", headers=AUTH)
    assert stock_total(client).json() == {"stock_total": 40, "products": 4}


def test_the_old_group_endpoints_are_gone(client, db, no_alerts):
    assert client.get("/products/groups", params={"q": "lec"}, headers=AUTH).status_code in (404, 405, 422)
    assert client.get("/products/group", params={"nombre": "Leche", "categoria": "Lacteos"}, headers=AUTH).status_code in (404, 405, 422)


# ── últimos cambios de stock ──────────────────────────────────────────────────

from datetime import datetime  # noqa: E402

CREATED = datetime(2026, 9, 1, 8, 0)


def at_time(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, 0)


def add_event(db, product, quantity, event_type, when, note=None, user_id=TEST_USER_ID, reverses=None):
    event = ConsumptionEvent(
        product_id=product.id, user_id=user_id, quantity=quantity, event_type=event_type,
        consumed_at=when, note=note, reverses_event_id=reverses,
    )
    db.add(event)
    db.commit()
    return event


def get_changes(client, **params):
    return client.get("/products/changes", params=params, headers=AUTH)


def summary(resp):
    return [(c["kind"], c["stock_before"], c["stock_after"], c["producto"]["nombre"]) for c in resp.json()]


def test_no_products_means_no_changes(client, db, no_alerts):
    assert get_changes(client).json() == []


def test_a_product_that_was_just_loaded_shows_up_as_an_entry_from_zero(client, db, no_alerts):
    add_product(db, nombre="Leche", stock=8, created_at=CREATED)

    body = get_changes(client).json()

    assert summary(get_changes(client)) == [("entrada", 0, 8, "Leche")]
    assert body[0]["quantity"] == 8
    assert body[0]["id"].startswith("created-")


def test_the_stock_before_and_after_of_each_change_is_rebuilt_from_the_current_stock(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=20, created_at=CREATED)
    add_event(db, leche, 5, "restocked", at_time(2))
    add_event(db, leche, 3, "consumed", at_time(3))

    resp = get_changes(client)

    assert summary(resp) == [
        ("salida", 23, 20, "Leche"),
        ("entrada", 18, 23, "Leche"),
        ("entrada", 0, 18, "Leche"),
    ]


def test_changes_come_from_the_newest_to_the_oldest_across_products(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=10, created_at=at_time(1))
    yogur = add_product(db, nombre="Yogur", stock=7, created_at=at_time(2))
    add_event(db, leche, 2, "consumed", at_time(5))
    add_event(db, yogur, 1, "restocked", at_time(4))

    assert [c[3] for c in summary(get_changes(client))][:2] == ["Leche", "Yogur"]


def test_exits_sales_rentals_and_expirations_are_all_exits(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=1, created_at=CREATED)
    for day, event_type in enumerate(["consumed", "sold", "rented", "expired"], start=2):
        add_event(db, leche, 1, event_type, at_time(day))

    kinds = [c["kind"] for c in get_changes(client, limit=10).json()]

    assert kinds[:4] == ["salida"] * 4


def test_a_stock_edit_is_a_modification_and_not_an_entry_or_an_exit(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=10, created_at=CREATED)
    add_event(db, leche, 4, "restocked", at_time(2), note="Modificación de stock")
    add_event(db, leche, 1, "consumed", at_time(3), note="Modificación de stock")

    kinds = [c["kind"] for c in get_changes(client, limit=10).json()]

    assert kinds[:2] == ["modificacion", "modificacion"]


def test_editing_the_stock_of_a_product_through_the_api_leaves_a_modification(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=10, created_at=CREATED)

    client.put(f"/products/{leche.id}", json={"stock": 14}, headers=AUTH)
    client.put(f"/products/{leche.id}", json={"stock": 9}, headers=AUTH)

    assert summary(get_changes(client))[:2] == [("modificacion", 14, 9, "Leche"), ("modificacion", 10, 14, "Leche")]


def test_entries_and_exits_made_through_the_api_are_listed_with_their_kind(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=10, created_at=CREATED)

    client.post(f"/products/{leche.id}/restock", json={"quantity": 5}, headers=AUTH)
    client.post(f"/products/{leche.id}/events", json={"event_type": "sold", "quantity": 3}, headers=AUTH)

    assert summary(get_changes(client))[:2] == [("salida", 15, 12, "Leche"), ("entrada", 10, 15, "Leche")]


def test_loading_a_product_again_through_the_api_is_an_entry_of_the_added_stock(client, db, no_alerts):
    first = client.post("/products/", json={"nombre": "Yerba", "categoria": "Almacen", "stock": 3}, headers=AUTH).json()
    client.post("/products/", json={"nombre": "Yerba", "categoria": "Almacen", "stock": 4}, headers=AUTH)

    resp = get_changes(client)

    assert summary(resp)[:2] == [("entrada", 3, 7, "Yerba"), ("entrada", 0, 3, "Yerba")]
    assert resp.json()[0]["producto"]["id"] == first["id"]


def test_a_correction_shows_the_corrected_movement_and_not_the_reversal(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=10, created_at=CREATED)
    client.post(f"/products/{leche.id}/events", json={"event_type": "consumed", "quantity": 4}, headers=AUTH)
    event = db.query(ConsumptionEvent).one()

    client.put(f"/products/{leche.id}/events/{event.id}", json={"event_type": "sold", "quantity": 4}, headers=AUTH)

    kinds = [c["kind"] for c in get_changes(client, limit=10).json()]
    assert kinds == ["salida", "entrada"]


def test_the_limit_is_respected_and_validated(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=30, created_at=CREATED)
    for day in range(2, 9):
        add_event(db, leche, 1, "restocked", at_time(day))

    assert len(get_changes(client).json()) == 5
    assert len(get_changes(client, limit=2).json()) == 2
    assert get_changes(client, limit=0).status_code == 422
    assert get_changes(client, limit=51).status_code == 422


def test_the_next_pages_of_changes_are_asked_with_an_offset(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=30, created_at=CREATED)
    for day in range(2, 8):
        add_event(db, leche, 1, "restocked", at_time(day))

    everything = [c["id"] for c in get_changes(client, limit=50).json()]
    first = [c["id"] for c in get_changes(client, limit=3).json()]
    second = [c["id"] for c in get_changes(client, limit=3, offset=3).json()]
    third = [c["id"] for c in get_changes(client, limit=3, offset=6).json()]

    assert first + second + third == everything
    assert len(everything) == 7
    assert len(third) == 1


def test_an_offset_beyond_the_last_change_gives_an_empty_list(client, db, no_alerts):
    add_product(db, nombre="Leche", stock=3, created_at=CREATED)

    assert get_changes(client, offset=10).json() == []


def test_the_offset_cannot_be_negative(client, db, no_alerts):
    assert get_changes(client, offset=-1).status_code == 422


def test_each_change_carries_the_whole_product(client, db, no_alerts):
    add_product(db, nombre="Leche", marca="Ser", categoria="Lacteos", stock=4, created_at=CREATED, imagen_url="https://cdn/a.jpg")

    product = get_changes(client).json()[0]["producto"]

    assert (product["nombre"], product["marca"], product["categoria"], product["imagen_url"]) == ("Leche", "Ser", "Lacteos", "https://cdn/a.jpg")


def test_only_the_users_own_changes_are_listed(client, db, no_alerts):
    mine = add_product(db, nombre="Mia", stock=1, created_at=CREATED)
    other = add_product(db, nombre="Ajena", stock=5, created_at=CREATED, user_id="00000000-0000-0000-0000-00000000dead")
    add_event(db, other, 2, "consumed", at_time(3), user_id="00000000-0000-0000-0000-00000000dead")

    assert [c[3] for c in summary(get_changes(client, limit=10))] == ["Mia"]
    assert mine.id != other.id


def test_a_product_without_a_load_date_has_no_initial_entry(client, db, no_alerts):
    leche = add_product(db, nombre="Leche", stock=3)
    # La base completa la fecha de carga sola al crear el producto: se la saca después, como en un producto viejo
    db.query(Product).filter(Product.id == leche.id).update({"created_at": None})
    db.commit()
    add_event(db, leche, 1, "consumed", at_time(3))

    assert summary(get_changes(client, limit=10)) == [("salida", 4, 3, "Leche")]


def test_changes_require_a_token(client, db):
    from app.core.security import get_current_user
    from app.main import app

    override = app.dependency_overrides.pop(get_current_user)
    try:
        assert client.get("/products/changes").status_code in (401, 403)
    finally:
        app.dependency_overrides[get_current_user] = override
