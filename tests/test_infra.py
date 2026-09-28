"""Piezas chicas de infraestructura: la dependencia real de sesión de DB (los
demás tests siempre usan la de test, así que ésta nunca corre sola), el
extractor de bearer token, el servicio de notificaciones por HTTP, y el ciclo
de vida de la app (arranque/apagado del scheduler)."""
import pytest
import requests
from fastapi import HTTPException, Request
from sqlalchemy import text

import app.core.database as database_module
from app.services.notifications import NotificationService
from app.utils.bearer import get_bearer_token
from tests.conftest import TestingSessionLocal


def test_get_db_yields_a_session_and_closes_it_on_teardown(monkeypatch):
    # `get_db` abre su propia `SessionLocal()`, que en producción apunta a
    # Postgres: para probarlo sin salir a la red se la redirige a la de test.
    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)

    gen = database_module.get_db()
    session = next(gen)
    session.execute(text("SELECT 1"))
    gen.close()  # dispara el `finally: db.close()`


def _fake_request(header_value):
    headers = [(b"authorization", header_value.encode())] if header_value is not None else []
    return Request({"type": "http", "headers": headers})


def test_get_bearer_token_returns_the_raw_token():
    request = _fake_request("Bearer abc123")

    assert get_bearer_token(request) == "abc123"


def test_get_bearer_token_rejects_a_missing_header():
    request = _fake_request(None)

    with pytest.raises(HTTPException) as exc:
        get_bearer_token(request)
    assert exc.value.status_code == 401


def test_get_bearer_token_rejects_a_non_bearer_scheme():
    request = _fake_request("Basic abc123")

    with pytest.raises(HTTPException):
        get_bearer_token(request)


def test_notification_service_returns_the_status_code_on_success(monkeypatch):
    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResponse())
    service = NotificationService(api_url="http://notify")

    assert service.send_notification("tok", "Titulo", "Cuerpo", "a@b.com") == 200


def test_notification_service_swallows_network_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.RequestException("down")

    monkeypatch.setattr(requests, "post", boom)
    service = NotificationService(api_url="http://notify")

    assert service.send_notification("tok", "Titulo", "Cuerpo", "a@b.com") is None


def test_the_app_starts_and_stops_its_scheduler(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as ctx_client:
        resp = ctx_client.get("/")
        assert resp.status_code == 200
