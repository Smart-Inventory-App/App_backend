"""
Job que corre cada hora y envía alertas a los usuarios cuya hora de chequeo
configurada coincide con la hora UTC actual.
"""
import logging
from datetime import date, datetime, timezone

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.firebase import send_push
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_ALERT_CHECK_HOUR, DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_OVERSTOCK_DAYS, UserProfile
from app.models.user import AuthUser

logger = logging.getLogger(__name__)


async def _ml_predict(events: list, product_data: dict) -> dict | None:
    """Llama al ML y retorna {daily_rate, days_until_stockout, stage} o None."""
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
            return r.json()
    except Exception:
        pass
    return None


async def run_daily_coverage_check() -> None:
    current_hour = datetime.now(timezone.utc).hour
    logger.info(f"Chequeo de cobertura hora UTC={current_hour}...")
    db = SessionLocal()
    alerts_sent = 0
    try:
        user_ids = [row[0] for row in db.query(Product.user_id).distinct().all()]

        for user_id in user_ids:
            user = db.query(AuthUser).filter(AuthUser.id == user_id).first()
            if not user or not user.firebase_token:
                continue

            profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

            # Solo procesar usuarios cuya hora de chequeo coincide con la hora actual
            user_check_hour = (profile.alert_check_hour if profile and profile.alert_check_hour is not None else DEFAULT_ALERT_CHECK_HOUR)
            if user_check_hour != current_hour:
                continue

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

                # Alertas basadas en ML
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
                ml_result = await _ml_predict(events, product_data)
                if ml_result:
                    days_until_stockout = ml_result.get("days_until_stockout")
                    daily_rate = ml_result.get("daily_rate")

                    # Alerta de bajo stock
                    if days_until_stockout is not None and days_until_stockout < coverage_threshold:
                        label = "día" if days_until_stockout == 1 else "días"
                        send_push(
                            user.firebase_token,
                            "Stock por agotarse",
                            f"{product.nombre} se agotará en aproximadamente {days_until_stockout} {label}.",
                        )
                        alerts_sent += 1

                    # Alerta de ritmo lento vs. vencimiento
                    if (
                        product.vencimiento is not None
                        and days_until_stockout is not None
                        and daily_rate is not None
                        and daily_rate > 0
                    ):
                        days_until_expiry = (product.vencimiento - date.today()).days
                        if 0 < days_until_expiry < days_until_stockout:
                            units_wasted = max(0, product.stock - int(daily_rate * days_until_expiry))
                            if units_wasted > 0:
                                send_push(
                                    user.firebase_token,
                                    "Riesgo de vencimiento por bajo consumo",
                                    f"Al ritmo actual, {units_wasted} unidad{'es' if units_wasted != 1 else ''} de {product.nombre} vencer{'án' if units_wasted != 1 else 'á'} en {days_until_expiry} días.",
                                )
                                alerts_sent += 1

        logger.info(f"Chequeo diario completado: {alerts_sent} alertas enviadas.")
    except Exception:
        logger.exception("Error en el chequeo diario de cobertura")
    finally:
        db.close()
