"""
Job diario que revisa la cobertura de stock de todos los productos
y envía alertas push cuando el ML predice agotamiento inminente.
Se ejecuta una vez por día a las 8:00 AM (UTC).
"""
import logging
from datetime import date

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.firebase import send_push
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, UserProfile
from app.models.user import AuthUser

logger = logging.getLogger(__name__)


async def _ml_days_until_stockout(events: list, product_data: dict) -> int | None:
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
                json={"events": events_payload, "product": product_data},
                headers={"X-Internal-Token": settings.INTERNAL_SERVICE_TOKEN},
            )
        if r.status_code == 200:
            return r.json().get("days_until_stockout")
    except Exception:
        pass
    return None


async def run_daily_coverage_check() -> None:
    logger.info("Iniciando chequeo diario de cobertura de stock...")
    db = SessionLocal()
    alerts_sent = 0
    try:
        user_ids = [row[0] for row in db.query(Product.user_id).distinct().all()]

        for user_id in user_ids:
            user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
            if not user or not user.firebase_token:
                continue

            profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
            coverage_threshold = (profile.stock_minimo if profile else None) or DEFAULT_COVERAGE_DAYS
            expiry_threshold = (profile.dias_alerta_vencimiento if profile else None) or DEFAULT_DIAS_ALERTA_VENCIMIENTO

            products = (
                db.query(Product)
                .filter(Product.user_id == user_id, Product.stock > 0)
                .all()
            )

            for product in products:
                # Alerta de vencimiento
                if product.vencimiento:
                    days_to_expiry = (product.vencimiento - date.today()).days
                    if 0 <= days_to_expiry < expiry_threshold:
                        send_push(
                            user.firebase_token,
                            "Producto próximo a vencerse",
                            f"{product.nombre} vence en {days_to_expiry} días.",
                        )
                        alerts_sent += 1

                # Alerta de cobertura de stock (ML)
                events = (
                    db.query(ConsumptionEvent)
                    .filter(ConsumptionEvent.product_id == product.id)
                    .order_by(ConsumptionEvent.consumed_at.asc())
                    .all()
                )
                product_data = {
                    "id": product.id,
                    "stock": product.stock,
                    "categoria": product.categoria,
                    "nombre": product.nombre,
                }
                days_until_stockout = await _ml_days_until_stockout(events, product_data)
                if days_until_stockout is not None and days_until_stockout < coverage_threshold:
                    label = "día" if days_until_stockout == 1 else "días"
                    send_push(
                        user.firebase_token,
                        "Stock por agotarse",
                        f"{product.nombre} se agotará en aproximadamente {days_until_stockout} {label}.",
                    )
                    alerts_sent += 1

        logger.info(f"Chequeo diario completado: {alerts_sent} alertas enviadas.")
    except Exception:
        logger.exception("Error en el chequeo diario de cobertura")
    finally:
        db.close()
