import httpx

from app.core.config import settings
from app.models.consumption import ConsumptionEvent
from app.models.profile import DEFAULT_USER_TYPE


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    """Cliente memoizado con pool de conexiones, para no abrir uno por producto.

    Las sugerencias de reposición y el job de alertas consultan al ML una vez por
    producto; reusar las conexiones evita el handshake en cada una.
    """
    global _client

    if _client is None:
        _client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    return _client


async def close() -> None:
    """Cierra el pool. La llama el shutdown de la app."""
    global _client

    client, _client = _client, None
    if client is None:
        return
    try:
        await client.aclose()
    except RuntimeError:
        # Si el pool tiene conexiones abiertas desde un event loop que ya se cerró, no queda nada que cerrar bien
        # y el apagado de la app no tiene que fallar por eso.
        pass


async def predict(events: list[ConsumptionEvent], product_data: dict, segment: str = DEFAULT_USER_TYPE) -> dict | None:
    """Llama al servicio ML y retorna {daily_rate, days_until_stockout, stage} o None."""
    if not settings.ML_SERVICE_URL:
        return None
    events_payload = [
        {
            "quantity": e.quantity,
            "event_type": e.event_type,
            "consumed_at": e.consumed_at.isoformat(),
            "product_id": e.product_id,
        }
        for e in events
    ]
    try:
        r = await _http().post(
            f"{settings.ML_SERVICE_URL}/models/predict-product",
            json={"events": events_payload, "product": product_data, "segment": segment},
            headers={"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN},
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None
