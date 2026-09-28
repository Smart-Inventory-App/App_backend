"""Endpoints legacy de transacciones (`/transactions/*`).

A diferencia del resto de la app, se identifican por `current_user["user_id"]`
(numérico), no por `sub`. El override global de test no trae esa clave, así
que estos tests reemplazan la dependencia sólo mientras corren."""
import pytest

from app.core.security import get_current_user
from app.main import app
from tests.conftest import TEST_USER

AUTH = {"Authorization": "Bearer token-de-prueba"}


@pytest.fixture
def as_numeric_user(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: {**TEST_USER, "user_id": "1"})


def test_list_transactions_starts_empty(client, db, as_numeric_user):
    resp = client.get("/transactions/", headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_fetch_a_transaction(client, db, as_numeric_user):
    resp = client.post("/transactions/", json={"amount": 100, "description": "Compra"}, headers=AUTH)

    assert resp.status_code == 200
    tx_id = resp.json()["id"]

    resp2 = client.get(f"/transactions/{tx_id}", headers=AUTH)

    assert resp2.status_code == 200
    assert resp2.json()["amount"] == 100


def test_get_an_unknown_transaction_is_404(client, db, as_numeric_user):
    resp = client.get("/transactions/99999", headers=AUTH)

    assert resp.status_code == 404


def test_list_transactions_only_lists_the_callers_own(client, db, as_numeric_user):
    client.post("/transactions/", json={"amount": 50, "description": "A"}, headers=AUTH)

    resp = client.get("/transactions/", headers=AUTH)

    assert len(resp.json()) == 1
