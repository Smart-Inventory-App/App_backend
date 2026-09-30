import pytest
import httpx
import respx
from freezegun import freeze_time

def test_list_alerts_empty(client, db):
    response = client.get("/alerts/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 0

@pytest.mark.asyncio
@respx.mock
def test_get_alerts(client, db):
    respx.post("http://fake-ml-service/models/predict-product").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"daily_rate": 2.0, "days_until_stockout": 5, "stage": "bayesian", "segment": "default"},
        )
    )
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5})
    products = client.get("/products/").json()
    for product in products:
        client.put(f"/products/{product['id']}", json={"stock": 1})
    response = client.get("/alerts/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "stock_low_coverage"

@pytest.mark.asyncio
@respx.mock
@freeze_time("2024-06-20")
def test_get_expiry_alerts(client, db):
    respx.post("http://fake-ml-service/models/predict-product").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"daily_rate": 2.0, "days_until_stockout": 10, "stage": "bayesian", "segment": "default"},
        )
    )
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10, "vencimiento": "2024-06-21"})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5, "vencimiento": "2024-06-30"})
    # -----------------retirar-----------------
    products = client.get("/products/").json()
    for product in products:
        client.put(f"/products/{product['id']}", json={"stock": 7})
    # -----------------retirar-----------------
    response = client.get("/alerts/expiry_alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "expiry"
    assert data[1]["type"] == "slow_pace"

@pytest.mark.asyncio
@respx.mock
@freeze_time("2024-06-20")
def test_get_critical_alerts(client, db):
    respx.post("http://fake-ml-service/models/predict-product").mock(
            return_value=httpx.Response(
                status_code=200,
                json={"daily_rate": 2.0, "days_until_stockout": 5, "stage": "bayesian", "segment": "default"},
            )
        )
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10, "vencimiento": "2024-06-21"})
    products = client.get("/products/").json()
    for product in products:
        client.put(f"/products/{product['id']}", json={"stock": 7})
    response = client.get("/alerts/critical_alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

@pytest.mark.asyncio
@respx.mock
@freeze_time("2024-06-20")
def test_get_stock_alerts(client, db):
    respx.post("http://fake-ml-service/models/predict-product").mock(
        return_value=httpx.Response(
            status_code=200,
            json={"daily_rate": 2.0, "days_until_stockout": 5, "stage": "bayesian", "segment": "default"},
        )
    )
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10, "vencimiento": "2024-06-21"})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5, "vencimiento": "2024-06-30"})
    # -----------------retirar-----------------
    products = client.get("/products/").json()
    for product in products:
        client.put(f"/products/{product['id']}", json={"stock": 1})
    # -----------------retirar-----------------
    response = client.get("/alerts/stock_alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "stock_low_coverage"
    assert data[1]["type"] == "stock_low_coverage"

@pytest.mark.asyncio
@respx.mock
@freeze_time("2024-06-20")
def test_get_alert_summary(client, db):
    respx.post("http://fake-ml-service/models/predict-product").mock(
            return_value=httpx.Response(
                status_code=200,
                json={"daily_rate": 2.0, "days_until_stockout": 10, "stage": "bayesian", "segment": "default"},
            )
        )
    client.post("/products/", json={"nombre": "Leche", "categoria": "Lacteo", "stock": 10, "vencimiento": "2024-06-21"})
    client.post("/products/", json={"nombre": "Pan", "categoria": "Panaderia", "stock": 5, "vencimiento": "2024-06-30"})
    products = client.get("/products/").json()
    for product in products:
        client.put(f"/products/{product['id']}", json={"stock": 7})
    response = client.get("/alerts/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["critical"] == 1
    assert data["warning"] == 1
    assert data["info"] == 0
