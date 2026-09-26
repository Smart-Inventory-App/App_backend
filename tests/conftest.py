"""Test configuration and fixtures."""
import os
from uuid import UUID

os.environ.setdefault("FIREBASE_CREDENTIALS", "{}")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.user import AuthUser

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# El `sub` real es el UUID del usuario en `auth_users`, no un texto libre.
TEST_USER = {"sub": "11111111-1111-4111-8111-111111111111", "email": "test@test.com"}


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


def override_get_current_user():
    return TEST_USER


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user


@pytest.fixture
def client():
    return TestClient(app)


def _seed_auth_user(session):
    """Los endpoints buscan al dueño en `auth_users` para evaluar sus alertas.

    Sin esa fila, una actualización de producto responde 404 aunque el producto
    exista. En el sistema real la fila la crea el servicio Auth al registrarse.
    """
    if session.get(AuthUser, UUID(TEST_USER["sub"])) is None:
        session.add(
            AuthUser(
                id=UUID(TEST_USER["sub"]),
                email=TEST_USER["email"],
                hashed_password="not-a-real-hash",
            )
        )
        session.commit()


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    _seed_auth_user(session)
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ensure_test_user(session):
    """Create the auth_users row that product endpoints look up to send push."""
    if session.query(AuthUser).filter(AuthUser.id == TEST_USER_ID).first():
        return
    session.add(
        AuthUser(
            id=TEST_USER_ID,
            email=TEST_USER["email"],
            hashed_password="x",
            is_active=True,
        )
    )
    session.commit()
