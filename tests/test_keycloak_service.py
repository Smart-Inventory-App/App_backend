"""Health and root endpoint tests."""

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_health_message(client):
    resp = client.get("/health")
    assert "message" in resp.json()

def test_version_endpoint(client):
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.0.0"

def test_test_endpoint(client):
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert "Frontend connected" in resp.json()["message"]

def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "message" in data
    assert "version" in data
