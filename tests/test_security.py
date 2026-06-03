"""Security utility tests."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from app.core.security import verify_password, get_password_hash, create_access_token


def test_get_password_hash_returns_string():
    hashed = get_password_hash("mysecret")
    assert isinstance(hashed, str)
    assert hashed != "mysecret"


def test_verify_password_correct():
    hashed = get_password_hash("correct")
    assert verify_password("correct", hashed) is True


def test_verify_password_wrong():
    hashed = get_password_hash("correct")
    assert verify_password("wrong", hashed) is False


def test_create_access_token():
    from jose import jwt
    from app.core.config import settings

    token = create_access_token({"sub": "user-123"})
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "user-123"
    assert "exp" in payload


@pytest.mark.asyncio
async def test_get_current_user_valid():
    from app.core.security import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    with patch("app.services.keycloak_service.keycloak") as mock_kc:
        mock_kc.validate_token = AsyncMock(return_value={"sub": "uuid", "email": "u@u.com"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="fake-token")
        result = await get_current_user(credentials=creds)

    assert result["sub"] == "uuid"


@pytest.mark.asyncio
async def test_get_current_user_invalid():
    from app.core.security import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    with patch("app.services.keycloak_service.keycloak") as mock_kc:
        mock_kc.validate_token = AsyncMock(side_effect=HTTPException(status_code=401, detail="invalid"))
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
        with pytest.raises(HTTPException):
            await get_current_user(credentials=creds)
