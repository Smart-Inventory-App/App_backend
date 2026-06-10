"""JWT security tests."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt

from app.core.config import settings
from app.core.security import get_current_user


def _make_token(payload: dict) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_valid_token_returns_payload():
    token = _make_token({"sub": "user-123", "email": "test@test.com"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    result = await get_current_user(credentials=creds)
    assert result["sub"] == "user-123"


@pytest.mark.asyncio
async def test_valid_token_preserves_all_claims():
    token = _make_token({"sub": "user-abc", "email": "a@b.com", "role": "admin"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    result = await get_current_user(credentials=creds)
    assert result["email"] == "a@b.com"


@pytest.mark.asyncio
async def test_missing_sub_raises_401():
    token = _make_token({"email": "test@test.com"})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_raises_401():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not.a.valid.jwt")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_raises_401():
    token = _make_token({
        "sub": "user-123",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
    })
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_secret_raises_401():
    token = jwt.encode({"sub": "user-123"}, "wrong-secret", algorithm=settings.JWT_ALGORITHM)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)
    assert exc_info.value.status_code == 401
