"""Barcode validation, normalization and lookup tests"""
import pytest
from pydantic import ValidationError

from app.api import products as products_api
from app.core import barcode
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}

ALTA = {"nombre": "Ibuprofeno", "categoria": "Farmacia", "stock": 5}


def add_product(db, **overrides):
    data = dict(user_id=TEST_USER_ID, nombre="Ibuprofeno", categoria="Farmacia", stock=5)
    data.update(overrides)
    product = Product(**data)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@pytest.fixture
def no_alerts(monkeypatch):
    """El alta que fusiona evalúa alertas; acá no interesan y saldrían a la red."""
    async def skip(*args, **kwargs):
        return None

    monkeypatch.setattr(products_api, "_check_product_state", skip)


# ── la regla ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "written, canonical",
    [
        ("7794640172021", "7794640172021"),      # EAN-13 tal cual
        ("779-464 017 2021", "7794640172021"),   # como lo copia una persona del envase
        ("036000291452", "0036000291452"),       # UPC-A se guarda como EAN-13
        ("96385074", "96385074"),                # EAN-8
        ("10012345678902", "10012345678902"),    # GTIN-14 de una caja mayorista
    ],
)
def test_valid_codes_are_normalized(written, canonical):
    assert barcode.normalizar(written) == canonical


@pytest.mark.parametrize(
    "written",
    [
        "12345",           # ningún GTIN tiene 5 dígitos
        "7794640172020",   # un dígito mal copiado: no cierra el verificador
        "abc",             # antes se descartaba en silencio y quedaba "sin código"
        "7794640I72021",   # una I en lugar de un 1
        "77946401720²1",   # `isdigit()` lo acepta pero `int()` no puede convertirlo
    ],
)
def test_invalid_codes_are_rejected(written):
    with pytest.raises(barcode.CodigoInvalido):
        barcode.normalizar(written)


@pytest.mark.parametrize("written", [None, "", "   "])
def test_an_empty_code_means_no_code(written):
    assert barcode.normalizar(written) is None


# ── en el schema: ningún alta ni edición lo saltea ────────────────────────────

def test_the_schema_stores_the_canonical_form():
    assert ProductCreate(**ALTA, codigo_barras="036000291452").codigo_barras == "0036000291452"


def test_the_schema_rejects_an_invalid_code():
    with pytest.raises(ValidationError):
        ProductCreate(**ALTA, codigo_barras="7794640172020")


def test_a_partial_update_without_a_code_does_not_touch_it():
    # Si el validador corriera sobre un campo que no vino, una edición de stock
    # borraría el código del producto.
    assert "codigo_barras" not in ProductUpdate(stock=3).model_dump(exclude_unset=True)


def test_create_rejects_an_invalid_barcode_with_422(client, db):
    resp = client.post("/products/", json={**ALTA, "codigo_barras": "12345"}, headers=AUTH)

    assert resp.status_code == 422
    assert db.query(Product).count() == 0


def test_create_saves_the_barcode_normalized(client, db):
    resp = client.post("/products/", json={**ALTA, "codigo_barras": "036000291452"}, headers=AUTH)

    assert resp.status_code == 201
    assert resp.json()["codigo_barras"] == "0036000291452"


def test_update_rejects_an_invalid_barcode(client, db):
    product = add_product(db)

    resp = client.put(f"/products/{product.id}", json={"codigo_barras": "abc"}, headers=AUTH)

    assert resp.status_code == 422


def test_merge_fills_a_missing_barcode(client, db, no_alerts):
    # Es dato nuevo sobre un producto que ya existía, no un producto distinto.
    product = add_product(db, codigo_barras=None)

    resp = client.post("/products/", json={**ALTA, "codigo_barras": "7794640172021"}, headers=AUTH)

    assert resp.json()["merged"] is True
    db.refresh(product)
    assert product.codigo_barras == "7794640172021"
    assert product.stock == 10


def test_merge_does_not_overwrite_an_existing_barcode(client, db, no_alerts):
    product = add_product(db, codigo_barras="7794640172021")

    client.post("/products/", json={**ALTA, "codigo_barras": "7790895000997"}, headers=AUTH)

    db.refresh(product)
    assert product.codigo_barras == "7794640172021"


# ── búsqueda por código ───────────────────────────────────────────────────────

def test_lookup_finds_the_product_ignoring_separators(client, db):
    product = add_product(db, codigo_barras="7794640172021")

    resp = client.get("/products/by-barcode/779-464 017 2021", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["id"] == product.id


def test_lookup_of_an_unknown_code_returns_null(client, db):
    # Que no esté es un resultado normal: es lo que abre el alta con el código puesto.
    add_product(db, codigo_barras="7794640172021")

    resp = client.get("/products/by-barcode/7790895000997", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() is None


def test_lookup_of_a_malformed_code_is_422(client, db):
    resp = client.get("/products/by-barcode/12345", headers=AUTH)

    assert resp.status_code == 422


def test_lookup_does_not_see_other_users_products(client, db):
    add_product(db, user_id="00000000-0000-0000-0000-000000000000", codigo_barras="7794640172021")

    resp = client.get("/products/by-barcode/7794640172021", headers=AUTH)

    assert resp.json() is None


def test_lookup_route_does_not_shadow_get_product_by_id(client, db):
    # `/by-barcode/{codigo}` va antes que `/{product_id}`; al revés, esto daría 422.
    product = add_product(db)

    assert client.get(f"/products/{product.id}", headers=AUTH).status_code == 200
