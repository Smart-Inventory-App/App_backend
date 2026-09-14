"""Test configuration and fixtures"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.alert import Alert
from app.models.user import AuthUser

# SQLite has no UUID type: without this, create_all cannot build these tables.
AuthUser.__table__.c.id.type = String(36)
Alert.__table__.c.user_id.type = String(36)

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

TEST_USER_ID = "11111111-2222-3333-4444-555555555555"
TEST_USER = {"sub": TEST_USER_ID, "email": "test@test.com"}


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


@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    _ensure_test_user(session)
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
