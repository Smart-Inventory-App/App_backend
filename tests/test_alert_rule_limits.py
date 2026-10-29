"""Tope de las reglas de alerta propias de un producto: stock mínimo de hasta 7 dígitos y días de anticipación de hasta 3."""
import pytest

AUTH = {"Authorization": "Bearer token-de-prueba"}


def new_product(client, **overrides):
    payload = {"nombre": "Producto", "categoria": "General", "stock": 5, **overrides}
    return client.post("/products/", json=payload, headers=AUTH)


# ── alta ─────────────────────────────────────────────────────────────────────

def test_the_highest_stock_minimo_is_a_seven_digit_number(client, db):
    resp = new_product(client, stock_minimo=9_999_999)
    assert resp.status_code == 201
    assert resp.json()["stock_minimo"] == 9_999_999


@pytest.mark.parametrize("value", [10_000_000, 99_999_999, 123_456_789])
def test_a_stock_minimo_of_eight_digits_or_more_is_rejected(client, db, value):
    assert new_product(client, stock_minimo=value).status_code == 422


def test_the_highest_dias_de_anticipacion_is_a_three_digit_number(client, db):
    resp = new_product(client, dias_alerta_vencimiento=999)
    assert resp.status_code == 201
    assert resp.json()["dias_alerta_vencimiento"] == 999


@pytest.mark.parametrize("value", [1000, 9999, 12345])
def test_dias_de_anticipacion_of_four_digits_or_more_are_rejected(client, db, value):
    assert new_product(client, dias_alerta_vencimiento=value).status_code == 422


def test_the_other_limits_of_these_fields_still_apply(client, db):
    assert new_product(client, stock_minimo=0).status_code == 422
    assert new_product(client, dias_alerta_vencimiento=0).status_code == 422
    assert new_product(client, stock_minimo=1, dias_alerta_vencimiento=1).status_code == 201


def test_both_fields_are_still_optional(client, db):
    resp = new_product(client)
    assert resp.status_code == 201
    assert resp.json()["stock_minimo"] is None
    assert resp.json()["dias_alerta_vencimiento"] is None


# ── edición ──────────────────────────────────────────────────────────────────

def test_editing_a_product_has_the_same_limits(client, db):
    product_id = new_product(client).json()["id"]
    put = lambda **fields: client.put(f"/products/{product_id}", json=fields, headers=AUTH)

    assert put(stock_minimo=9_999_999, dias_alerta_vencimiento=999).status_code == 200
    assert put(stock_minimo=10_000_000).status_code == 422
    assert put(dias_alerta_vencimiento=1000).status_code == 422


def test_a_rejected_edit_leaves_the_product_untouched(client, db):
    product_id = new_product(client, stock_minimo=5, dias_alerta_vencimiento=5).json()["id"]
    client.put(f"/products/{product_id}", json={"stock_minimo": 10_000_000, "dias_alerta_vencimiento": 1000}, headers=AUTH)

    product = client.get(f"/products/{product_id}", headers=AUTH).json()
    assert product["stock_minimo"] == 5
    assert product["dias_alerta_vencimiento"] == 5
