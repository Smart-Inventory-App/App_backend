"""UserService tests against the in-memory SQLite DB."""
import pytest
from fastapi import HTTPException

from app.schemas.user import UserCreate, UserLogin
from app.services.user_service import UserService


@pytest.fixture
def clean_db(db):
    """Alias for the db fixture — ensures tables exist and are clean."""
    return db


def test_create_user(clean_db):
    user = UserService.create_user(clean_db, UserCreate(email="new@test.com", username="newuser", password="pass"))
    assert user.email == "new@test.com"
    assert user.hashed_password != "pass"


def test_create_user_duplicate_raises(clean_db):
    UserService.create_user(clean_db, UserCreate(email="dup@test.com", username="dupuser", password="pass"))
    with pytest.raises(HTTPException) as exc:
        UserService.create_user(clean_db, UserCreate(email="dup@test.com", username="dupuser2", password="pass"))
    assert exc.value.status_code == 400


def test_authenticate_user_success(clean_db):
    UserService.create_user(clean_db, UserCreate(email="auth@test.com", username="authuser", password="secret"))
    result = UserService.authenticate_user(clean_db, UserLogin(email="auth@test.com", password="secret"))
    assert "access_token" in result


def test_authenticate_user_wrong_password(clean_db):
    UserService.create_user(clean_db, UserCreate(email="wp@test.com", username="wpuser", password="correct"))
    with pytest.raises(HTTPException) as exc:
        UserService.authenticate_user(clean_db, UserLogin(email="wp@test.com", password="wrong"))
    assert exc.value.status_code == 401


def test_authenticate_user_not_found(clean_db):
    with pytest.raises(HTTPException) as exc:
        UserService.authenticate_user(clean_db, UserLogin(email="ghost@test.com", password="pass"))
    assert exc.value.status_code == 401


def test_get_user_by_id_not_found(clean_db):
    with pytest.raises(HTTPException) as exc:
        UserService.get_user_by_id(clean_db, 999)
    assert exc.value.status_code == 404
