"""Product CRUD endpoint tests."""
import pytest


# ── list ──────────────────────────────────────────────────────────────────────

def test_list_products_empty(client, db):
    resp = client.get("/products/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_products_returns_own_products(client, db):
    client.post("/products/", json={"nombre": "Prod1", "categoria": "Cat", "stock": 5})
    client.post("/products/", json={"nombre": "Prod2", "categoria": "Cat", "stock": 3})
    resp = client.get("/products/")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_products_search_by_name(client, db):
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5})
    resp = client.get("/products/", params={"search": "Leche"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["nombre"] == "Leche"


def test_list_products_filter_categoria(client, db):
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5})
    resp = client.get("/products/", params={"categoria": "Lacteo"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_products_filter_ubicacion(client, db):
    client.post("/products/", json={"nombre": "A", "categoria": "Cat", "stock": 1, "ubicacion": "Estante A"})
    client.post("/products/", json={"nombre": "B", "categoria": "Cat", "stock": 1, "ubicacion": "Estante B"})
    resp = client.get("/products/", params={"ubicacion": "Estante A"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── create ────────────────────────────────────────────────────────────────────

def test_create_product_success(client, db):
    payload = {"nombre": "Producto", "categoria": "General", "stock": 10}
    resp = client.post("/products/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["nombre"] == "Producto"
    assert data["stock"] == 10
    assert "id" in data


def test_create_product_with_all_fields(client, db):
    payload = {
        "nombre": "Completo",
        "categoria": "Varios",
        "stock": 5,
        "marca": "MarcaX",
        "descripcion": "Una descripcion",
        "vencimiento": "2025-12-31",
        "ubicacion": "Deposito",
    }
    resp = client.post("/products/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["marca"] == "MarcaX"
    assert data["ubicacion"] == "Deposito"


def test_create_product_stock_zero_rejected(client, db):
    resp = client.post("/products/", json={"nombre": "Bad", "categoria": "Cat", "stock": 0})
    assert resp.status_code == 422


def test_create_product_nombre_too_long_rejected(client, db):
    resp = client.post("/products/", json={"nombre": "A" * 21, "categoria": "Cat", "stock": 5})
    assert resp.status_code == 422


def test_create_product_missing_required_fields(client, db):
    resp = client.post("/products/", json={"nombre": "Prod"})
    assert resp.status_code == 422


# ── get ───────────────────────────────────────────────────────────────────────

def test_get_product_success(client, db):
    create_resp = client.post("/products/", json={"nombre": "ToGet", "categoria": "Cat", "stock": 3})
    product_id = create_resp.json()["id"]
    resp = client.get(f"/products/{product_id}")
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "ToGet"


def test_get_product_not_found(client, db):
    resp = client.get("/products/99999")
    assert resp.status_code == 404


# ── update ────────────────────────────────────────────────────────────────────

def test_update_product_stock(client, db):
    create_resp = client.post("/products/", json={"nombre": "Original", "categoria": "Cat", "stock": 5})
    product_id = create_resp.json()["id"]
    resp = client.put(f"/products/{product_id}", json={"stock": 20})
    assert resp.status_code == 200
    assert resp.json()["stock"] == 20


def test_update_product_nombre(client, db):
    create_resp = client.post("/products/", json={"nombre": "Viejo", "categoria": "Cat", "stock": 5})
    product_id = create_resp.json()["id"]
    resp = client.put(f"/products/{product_id}", json={"nombre": "Nuevo"})
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "Nuevo"


def test_update_product_not_found(client, db):
    resp = client.put("/products/99999", json={"stock": 10})
    assert resp.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_product_success(client, db):
    create_resp = client.post("/products/", json={"nombre": "ToDelete", "categoria": "Cat", "stock": 1})
    product_id = create_resp.json()["id"]
    resp = client.delete(f"/products/{product_id}")
    assert resp.status_code == 204
    assert client.get(f"/products/{product_id}").status_code == 404


def test_delete_product_not_found(client, db):
    resp = client.delete("/products/99999")
    assert resp.status_code == 404
