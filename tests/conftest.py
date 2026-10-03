"""Test configuration and fixtures."""
import os
from uuid import UUID

os.environ.setdefault("FIREBASE_CREDENTIALS", "{}")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api import products as products_api
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.user import AuthUser
from app.services import alert_job

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

TEST_USER = {"sub": "11111111-1111-4111-8111-111111111111", "email": "test@test.com"}
TEST_USER_ID = TEST_USER["sub"]


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


ML_URL = "http://ml:9000"


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    """Registra las notificaciones que se hubieran mandado, sin pegarle a la red.

    Es automática a propósito: un test que dispara una alerta sin acordarse de
    esto terminaría llamando al servicio de notificaciones de verdad, y si hay
    uno corriendo en la máquina le llegarían mensajes de prueba. Se reemplaza el
    método de las dos instancias que usa la app; un `NotificationService` creado
    a mano dentro de un test sigue siendo el real.
    """
    sent = []

    async def fake_send(token, title, body, email):
        sent.append({"token": token, "title": title, "body": body, "email": email})
        return 200

    monkeypatch.setattr(products_api.notification_service, "send_notification", fake_send)
    monkeypatch.setattr(alert_job.notification_service, "send_notification", fake_send)
    return sent


@pytest.fixture
def ml_enabled(monkeypatch):
    """Activa la integración con el servicio de ML (por defecto está apagada)."""
    monkeypatch.setattr(settings, "ML_SERVICE_URL", ML_URL)


@pytest.fixture
def ml_transport():
    """Fija qué responde el servicio de ML: `install(handler)`.

    `handler(request)` devuelve un `httpx.Response`; también se le puede pasar una
    excepción (`httpx.ConnectError(...)`) para simular que el servicio no
    responde. Se puede llamar más de una vez en el mismo test para cambiar la
    predicción entre dos pasos.
    """
    with respx.mock(assert_all_called=False) as router:
        route = router.route()

        def install(handler):
            route.mock(side_effect=handler)

        yield install


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
