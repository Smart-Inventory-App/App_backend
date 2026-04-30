"""
Test suite for authentication endpoints
"""
from tests.conftest import client


def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_user(client):
    """Test user registration"""
    response = client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


def test_login_user(client):
    """Test user login"""
    # First register
    client.post(
        "/auth/register",
        json={
            "email": "test@example.com",
            "username": "testuser",
            "password": "password123",
        },
    )
    
    # Then login
    response = client.post(
        "/auth/login",
        json={
            "email": "test@example.com",
            "password": "password123",
        },
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
