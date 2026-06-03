"""Auth endpoint tests — Keycloak calls are mocked."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.config import settings


def _make_reset_token(email: str, expired: bool = False) -> str:
    delta = timedelta(minutes=-1) if expired else timedelta(minutes=15)
    return jwt.encode(
        {"sub": email, "purpose": "password_reset", "exp": datetime.now(timezone.utc) + delta},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


# ── health ────────────────────────────────────────────────────────────────────

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── login ─────────────────────────────────────────────────────────────────────

def test_login_success(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.login = AsyncMock(return_value={
            "access_token": "tok123", "refresh_token": "ref123", "token_type": "bearer",
        })
        resp = client.post("/auth/login", json={"email": "a@a.com", "password": "pass"})
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "tok123"


def test_login_invalid_credentials(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.login = AsyncMock(side_effect=HTTPException(status_code=401, detail="INVALID_CREDENTIALS"))
        resp = client.post("/auth/login", json={"email": "a@a.com", "password": "wrong"})
    assert resp.status_code == 401


# ── register ──────────────────────────────────────────────────────────────────

def test_register_success(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.register = AsyncMock(return_value=None)
        resp = client.post("/auth/register", json={"email": "new@new.com", "password": "Passw0rd!"})
    assert resp.status_code == 201
    assert resp.json()["detail"] == "Usuario creado"


def test_register_email_taken(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.register = AsyncMock(side_effect=HTTPException(status_code=400, detail="EMAIL_TAKEN"))
        resp = client.post("/auth/register", json={"email": "taken@test.com", "password": "Passw0rd!"})
    assert resp.status_code == 400


# ── check-email ───────────────────────────────────────────────────────────────

def test_check_email_exists(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=True)
        resp = client.post("/auth/check-email", json={"email": "existing@test.com"})
    assert resp.status_code == 200
    assert resp.json()["exists"] is True


def test_check_email_not_exists(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=False)
        resp = client.post("/auth/check-email", json={"email": "new@test.com"})
    assert resp.status_code == 200
    assert resp.json()["exists"] is False


# ── forgot-password ───────────────────────────────────────────────────────────

def test_forgot_password_user_exists(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=True)
        mock_kc.generate_recovery_code = MagicMock(return_value="123456")
        mock_kc.send_recovery_email = MagicMock()
        resp = client.post("/auth/forgot-password", json={"email": "user@test.com"})
    assert resp.status_code == 200


def test_forgot_password_user_not_exists(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=False)
        resp = client.post("/auth/forgot-password", json={"email": "nobody@test.com"})
    assert resp.status_code == 200


# ── verify-code ───────────────────────────────────────────────────────────────

def test_verify_code_valid(client):
    """Insert a code via forgot-password flow, then verify it."""
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=True)
        mock_kc.generate_recovery_code = MagicMock(return_value="777777")
        mock_kc.send_recovery_email = MagicMock()
        client.post("/auth/forgot-password", json={"email": "chain@test.com"})

    resp = client.post("/auth/verify-code", json={"email": "chain@test.com", "code": "777777"})
    assert resp.status_code == 200
    assert "reset_token" in resp.json()


def test_verify_code_invalid(client):
    resp = client.post("/auth/verify-code", json={"email": "x@x.com", "code": "000000"})
    assert resp.status_code == 400


def test_verify_code_used(client):
    """Code cannot be reused."""
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.email_exists = AsyncMock(return_value=True)
        mock_kc.generate_recovery_code = MagicMock(return_value="888888")
        mock_kc.send_recovery_email = MagicMock()
        client.post("/auth/forgot-password", json={"email": "reuse@test.com"})

    client.post("/auth/verify-code", json={"email": "reuse@test.com", "code": "888888"})
    resp = client.post("/auth/verify-code", json={"email": "reuse@test.com", "code": "888888"})
    assert resp.status_code == 400


# ── reset-password ────────────────────────────────────────────────────────────

def test_reset_password_success(client):
    token = _make_reset_token("reset@test.com")
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.get_user_id_by_email = AsyncMock(return_value="user-uuid-123")
        mock_kc.reset_password = AsyncMock(return_value=None)
        resp = client.post("/auth/reset-password", json={"reset_token": token, "new_password": "NewPass1!"})
    assert resp.status_code == 200


def test_reset_password_user_not_found(client):
    token = _make_reset_token("ghost@test.com")
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.get_user_id_by_email = AsyncMock(return_value=None)
        resp = client.post("/auth/reset-password", json={"reset_token": token, "new_password": "NewPass1!"})
    assert resp.status_code == 404


def test_reset_password_invalid_token(client):
    resp = client.post("/auth/reset-password", json={"reset_token": "not.a.valid.token", "new_password": "pass"})
    assert resp.status_code == 400


def test_reset_password_expired_token(client):
    token = _make_reset_token("old@test.com", expired=True)
    resp = client.post("/auth/reset-password", json={"reset_token": token, "new_password": "pass"})
    assert resp.status_code == 400


# ── social-callback ───────────────────────────────────────────────────────────

def test_social_callback_success(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.exchange_code = AsyncMock(return_value={
            "access_token": "social_tok", "token_type": "bearer",
        })
        resp = client.post("/auth/social-callback", json={
            "code": "auth_code", "redirect_uri": "app-frontend://", "code_verifier": "verifier",
        })
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "social_tok"


def test_social_callback_invalid_code(client):
    with patch("app.api.auth.keycloak") as mock_kc:
        mock_kc.exchange_code = AsyncMock(side_effect=HTTPException(status_code=401, detail="INVALID_CODE"))
        resp = client.post("/auth/social-callback", json={
            "code": "bad_code", "redirect_uri": "app-frontend://",
        })
    assert resp.status_code == 401


# ── me ────────────────────────────────────────────────────────────────────────

def test_me(client):
    from app.core.security import get_current_user
    from app.main import app as fastapi_app

    async def fake_user():
        return {"email": "me@test.com", "preferred_username": "me@test.com", "sub": "uuid-123"}

    fastapi_app.dependency_overrides[get_current_user] = fake_user
    try:
        resp = client.get("/auth/me", headers={"Authorization": "Bearer fake"})
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.com"
