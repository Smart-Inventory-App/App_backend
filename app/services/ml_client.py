import httpx

from app.core.config import settings
from app.models.consumption import ConsumptionEvent
from app.models.profile import DEFAULT_USER_TYPE


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
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{settings.ML_SERVICE_URL}/models/predict-product",
                json={"events": events_payload, "product": product_data, "segment": segment},
                headers={"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN},
            )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None
