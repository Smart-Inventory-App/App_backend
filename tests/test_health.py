"""Health endpoint tests."""

def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

def test_version(client):
    resp = client.get("/version")
    assert resp.status_code == 200
    assert resp.json()["version"] == "1.0.0"

def test_test_endpoint(client):
    resp = client.get("/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert "Frontend connected" in resp.json()["message"]
