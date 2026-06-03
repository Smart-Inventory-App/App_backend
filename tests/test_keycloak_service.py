"""KeycloakService unit tests — httpx calls are mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from app.services.keycloak_service import KeycloakService

kc = KeycloakService()


def _mock_client(status: int, body: dict):
    """Return an async context manager mock that responds with the given status and body."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = str(body)
    resp.is_success = status < 400
    resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.get = AsyncMock(return_value=resp)
    client.put = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ── admin token ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_admin_token_success():
    mock = _mock_client(200, {"access_token": "admin_tok"})
    with patch("httpx.AsyncClient", return_value=mock):
        token = await kc._get_admin_token()
    assert token == "admin_tok"


@pytest.mark.asyncio
async def test_get_admin_token_failure():
    import httpx as _httpx

    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Unauthorized"
    resp.raise_for_status = MagicMock(
        side_effect=_httpx.HTTPStatusError("401", request=MagicMock(), response=MagicMock())
    )
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=client):
        with pytest.raises(HTTPException):
            await kc._get_admin_token()


# ── login ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success():
    mock = _mock_client(200, {"access_token": "tok", "refresh_token": "ref"})
    with patch("httpx.AsyncClient", return_value=mock):
        result = await kc.login("u@u.com", "pass")
    assert result["access_token"] == "tok"


@pytest.mark.asyncio
async def test_login_invalid_credentials():
    mock = _mock_client(401, {"error": "invalid_grant"})
    with patch("httpx.AsyncClient", return_value=mock):
        with pytest.raises(HTTPException) as exc:
            await kc.login("u@u.com", "bad")
    assert exc.value.status_code == 401


# ── register ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success():
    admin_mock = _mock_client(200, {"access_token": "admin"})
    reg_resp = MagicMock()
    reg_resp.status_code = 201
    reg_resp.is_success = True
    reg_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.post = AsyncMock(side_effect=[admin_mock.post.return_value, reg_resp])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=client):
        await kc.register("new@new.com", "Password1!")


@pytest.mark.asyncio
async def test_register_email_taken():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        taken_resp = MagicMock()
        taken_resp.status_code = 409
        taken_resp.is_success = False
        client = AsyncMock()
        client.post = AsyncMock(return_value=taken_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(HTTPException) as exc:
                await kc.register("taken@test.com", "pass")
    assert exc.value.status_code == 400


# ── email_exists ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_exists_true():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        mock = _mock_client(200, [{"id": "uuid1", "email": "u@u.com"}])
        with patch("httpx.AsyncClient", return_value=mock):
            result = await kc.email_exists("u@u.com")
    assert result is True


@pytest.mark.asyncio
async def test_email_exists_false():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        mock = _mock_client(200, [])
        with patch("httpx.AsyncClient", return_value=mock):
            result = await kc.email_exists("nobody@test.com")
    assert result is False


# ── get_user_id_by_email ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_id_found():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        mock = _mock_client(200, [{"id": "uuid-abc"}])
        with patch("httpx.AsyncClient", return_value=mock):
            uid = await kc.get_user_id_by_email("found@test.com")
    assert uid == "uuid-abc"


@pytest.mark.asyncio
async def test_get_user_id_not_found():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        mock = _mock_client(200, [])
        with patch("httpx.AsyncClient", return_value=mock):
            uid = await kc.get_user_id_by_email("nobody@test.com")
    assert uid is None


# ── reset_password ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_password_success():
    with patch.object(kc, "_get_admin_token", AsyncMock(return_value="admin_tok")):
        resp = MagicMock()
        resp.status_code = 204
        resp.raise_for_status = MagicMock()
        client = AsyncMock()
        client.put = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            await kc.reset_password("user-uuid", "NewPass1!")


# ── validate_token ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_token_active():
    mock = _mock_client(200, {"active": True, "sub": "uuid-123"})
    with patch("httpx.AsyncClient", return_value=mock):
        result = await kc.validate_token("valid-token")
    assert result["active"] is True


@pytest.mark.asyncio
async def test_validate_token_inactive():
    mock = _mock_client(200, {"active": False})
    with patch("httpx.AsyncClient", return_value=mock):
        with pytest.raises(HTTPException) as exc:
            await kc.validate_token("expired-token")
    assert exc.value.status_code == 401


# ── exchange_code ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_code_success():
    mock = _mock_client(200, {"access_token": "social_tok", "refresh_token": "ref"})
    with patch("httpx.AsyncClient", return_value=mock):
        result = await kc.exchange_code("code123", "app-frontend://", "verifier")
    assert result["access_token"] == "social_tok"


@pytest.mark.asyncio
async def test_exchange_code_invalid():
    mock = _mock_client(400, {"error": "invalid_grant"})
    with patch("httpx.AsyncClient", return_value=mock):
        with pytest.raises(HTTPException) as exc:
            await kc.exchange_code("bad_code", "app-frontend://")
    assert exc.value.status_code == 401


# ── recovery code helpers ─────────────────────────────────────────────────────

def test_generate_recovery_code():
    code = KeycloakService.generate_recovery_code()
    assert len(code) == 6
    assert code.isdigit()


def test_send_recovery_email_no_smtp(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        kc.send_recovery_email("u@u.com", "123456")
    assert "SMTP not configured" in caplog.text
