"""Piezas chicas de infraestructura: la dependencia real de sesión de DB (los
demás tests siempre usan la de test, así que ésta nunca corre sola), el
extractor de bearer token, el servicio de notificaciones por HTTP, y el ciclo
de vida de la app (arranque/apagado del scheduler)."""
import json
import logging

import httpx
import pytest
import respx
from fastapi import HTTPException, Request
from sqlalchemy import text

import app.core.database as database_module
from app.services.notifications import NotificationService, notification_url
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


SEND_URL = "http://notify:8010/notification/send_notification"


@pytest.mark.parametrize("configured", [
    "http://notify:8010",
    "http://notify:8010/",
    "http://notify:8010/notification",
    "http://notify:8010/notification/",
])
def test_notification_url_accepts_the_service_base_and_the_prefixed_form(configured):
    """Las dos formas de configurarla apuntan a la misma ruta: mezclarlas daba
    `/notification/notification/send_notification`, un 404 que nadie veía."""
    assert notification_url(configured) == SEND_URL


def test_notification_url_without_a_configured_service_does_not_crash():
    assert notification_url("") == "/notification/send_notification"


async def test_notification_service_posts_the_payload_and_returns_the_status_code():
    service = NotificationService(api_url="http://notify:8010")

    with respx.mock as router:
        route = router.post(SEND_URL).mock(return_value=httpx.Response(200))
        status = await service.send_notification("tok", "Titulo", "Cuerpo", "a@b.com")

    assert status == 200
    assert json.loads(route.calls.last.request.content) == {
        "title": "Titulo", "body": "Cuerpo", "token": "tok", "email": "a@b.com",
    }


async def test_notification_service_sends_the_details_for_the_email_only_when_there_are():
    service = NotificationService(api_url="http://notify:8010")

    with respx.mock as router:
        route = router.post(SEND_URL).mock(return_value=httpx.Response(200))
        await service.send_notification(
            "tok", "Titulo", "Cuerpo", "a@b.com", kind="slow_pace", product_name="Pan", days=4, units=0,
        )

    assert json.loads(route.calls.last.request.content) == {
        "title": "Titulo", "body": "Cuerpo", "token": "tok", "email": "a@b.com",
        "kind": "slow_pace", "product_name": "Pan", "days": 4, "units": 0,
    }


async def test_notification_service_swallows_network_errors_but_logs_them(caplog):
    service = NotificationService(api_url="http://notify:8010")

    with respx.mock as router, caplog.at_level(logging.WARNING):
        router.post(SEND_URL).mock(side_effect=httpx.ConnectError("down"))
        status = await service.send_notification("tok", "Titulo", "Cuerpo", "a@b.com")

    assert status is None
    assert "No se pudo enviar la notificación" in caplog.text


async def test_notification_service_logs_a_rejected_request(caplog):
    """Un 404 o un 500 no se pueden ignorar en silencio: así se perdieron notificaciones."""
    service = NotificationService(api_url="http://notify:8010")

    with respx.mock as router, caplog.at_level(logging.WARNING):
        router.post(SEND_URL).mock(return_value=httpx.Response(404))
        status = await service.send_notification("tok", "Titulo", "Cuerpo", "a@b.com")

    assert status == 404
    assert "respondió 404" in caplog.text


def test_the_legacy_transactions_endpoints_are_gone(client):
    """Identificaban al usuario por un `user_id` que el JWT de Auth no trae: con un token real daban 500."""
    assert client.get("/transactions/").status_code == 404


def test_the_app_starts_and_stops_its_scheduler(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as ctx_client:
        resp = ctx_client.get("/")
        assert resp.status_code == 200
