"""`ml_client.predict`: llamada al servicio de ML y cliente HTTP compartido."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.models.consumption import ConsumptionEvent
from app.models.profile import DEFAULT_USER_TYPE
from app.services import ml_client

PRODUCT = {"id": 1, "stock": 4, "nombre": "Leche"}


@pytest.fixture(autouse=True)
async def fresh_client():
    ml_client._client = None
    yield
    await ml_client.close()


def event(quantity=2, event_type="consumed"):
    return ConsumptionEvent(
        product_id=1, quantity=quantity, event_type=event_type,
        consumed_at=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
    )


async def test_without_a_configured_url_it_returns_none_and_does_not_call(monkeypatch, ml_transport):
    monkeypatch.setattr(settings, "ML_SERVICE_URL", "")
    calls = []
    ml_transport(lambda req: calls.append(req) or httpx.Response(200, json={}))

    assert await ml_client.predict([event()], PRODUCT) is None
    assert calls == []


async def test_a_200_response_is_returned_as_is(ml_enabled, ml_transport):
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.5, "days_until_stockout": 3}))

    assert await ml_client.predict([event()], PRODUCT) == {"daily_rate": 1.5, "days_until_stockout": 3}


async def test_the_request_carries_events_product_segment_and_internal_token(ml_enabled, ml_transport, monkeypatch):
    monkeypatch.setattr(settings, "INTERNAL_SERVICE_TOKEN", "token-interno")
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"daily_rate": 1.0})

    ml_transport(handler)

    await ml_client.predict([event(2), event(1, "restocked")], PRODUCT, segment="comercio")

    request = seen[0]
    assert request.url.path == "/models/predict-product"
    assert request.headers["X-Internal-Token"] == "token-interno"
    body = json.loads(request.content)
    assert body["segment"] == "comercio"
    assert body["product"] == PRODUCT
    assert [(e["quantity"], e["event_type"], e["product_id"]) for e in body["events"]] == [(2, "consumed", 1), (1, "restocked", 1)]
    assert body["events"][0]["consumed_at"] == "2026-10-01T08:00:00+00:00"


async def test_the_default_segment_is_the_default_user_type(ml_enabled, ml_transport):
    seen = []
    ml_transport(lambda req: seen.append(json.loads(req.content)) or httpx.Response(200, json={}))

    await ml_client.predict([], PRODUCT)

    assert seen[0]["segment"] == DEFAULT_USER_TYPE


@pytest.mark.parametrize("status_code", [403, 404, 422, 500, 502])
async def test_a_non_200_response_returns_none(ml_enabled, ml_transport, status_code):
    ml_transport(lambda req: httpx.Response(status_code, json={"detail": "x"}))

    assert await ml_client.predict([event()], PRODUCT) is None


async def test_a_network_error_returns_none(ml_enabled, ml_transport):
    ml_transport(httpx.ConnectError("el ML no responde"))

    assert await ml_client.predict([event()], PRODUCT) is None


async def test_a_timeout_returns_none(ml_enabled, ml_transport):
    ml_transport(httpx.ReadTimeout("demasiado lento"))

    assert await ml_client.predict([event()], PRODUCT) is None


async def test_a_body_that_is_not_json_returns_none(ml_enabled, ml_transport):
    ml_transport(lambda req: httpx.Response(200, content=b"<html>no es json</html>"))

    assert await ml_client.predict([event()], PRODUCT) is None


# ── cliente compartido ────────────────────────────────────────────────────────

async def test_the_http_client_is_created_once_and_reused():
    first = ml_client._http()

    assert ml_client._http() is first


async def test_close_shuts_the_client_down_and_the_next_call_builds_a_new_one():
    first = ml_client._http()

    await ml_client.close()

    assert ml_client._client is None
    assert first.is_closed
    assert ml_client._http() is not first


async def test_closing_without_a_client_does_nothing():
    ml_client._client = None

    await ml_client.close()

    assert ml_client._client is None


async def test_one_client_serves_consecutive_predictions(ml_enabled, ml_transport):
    ml_transport(lambda req: httpx.Response(200, json={"daily_rate": 1.0}))

    await ml_client.predict([], PRODUCT)
    client = ml_client._client
    await ml_client.predict([], PRODUCT)

    assert ml_client._client is client


async def test_shutting_the_app_down_closes_the_client(monkeypatch):
    from app import main

    class FakeScheduler:
        def add_job(self, *args, **kwargs): pass
        def start(self): pass
        def shutdown(self): pass

    monkeypatch.setattr(main, "_scheduler", FakeScheduler())
    ml_client._http()

    async with main.lifespan(main.app):
        assert ml_client._client is not None

    assert ml_client._client is None
