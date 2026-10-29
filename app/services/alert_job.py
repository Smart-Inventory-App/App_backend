"""
Job que corre cada hora y evalúa las alertas de los usuarios cuya hora de chequeo
configurada coincide con la hora UTC actual.

Las alertas se calculan siempre; los avisos (push y mail) solo salen si el usuario tiene las notificaciones activadas.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import alert_engine, alert_rules, alert_texts
from app.services.ml_client import predict as _ml_predict
from app.services.notifications import NotificationService
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_ALERT_CHECK_HOUR, DEFAULT_USER_TYPE, UserProfile
from app.models.user import AuthUser
from app.models.alert import Alert

logger = logging.getLogger(__name__)
notification_service = NotificationService(api_url=settings.NOTIFICATION_SERVICE_URL)


async def _notify(user: AuthUser, enabled: bool, title: str, body: str, **extras) -> bool:
    """Manda el aviso si corresponde. Sin notificaciones activadas la alerta igual queda en el Centro de Alertas."""
    if not enabled or not user.firebase_token:
        return False
    await notification_service.send_notification(user.firebase_token, title, body, user.email, **extras)
    return True


async def run_daily_coverage_check(
    target_user_id: str | None = None,
    force: bool = False,
    notify: bool = True,
) -> dict:
    """
    Evalúa las alertas de vencimiento, de stock mínimo (con el modelo predictivo) y de ritmo lento.
    - target_user_id: si se pasa, solo procesa ese usuario.
    - force: si True, ignora el filtro de hora configurada.
    - notify: si False, solo actualiza las alertas, sin mandar avisos (por ejemplo, al cambiar las reglas).
    """
    current_hour = datetime.now(timezone.utc).hour
    logger.info(f"Chequeo de cobertura hora UTC={current_hour} force={force} user={target_user_id}")
    db = SessionLocal()
    alerts_sent = 0
    users_processed = 0
    try:
        user_ids = [row[0] for row in db.query(Product.user_id).distinct().all()]

        for user_id in user_ids:
            if target_user_id is not None and str(user_id) != str(target_user_id):
                continue

            try:
                uid = UUID(str(user_id))
            except ValueError:
                continue

            user = db.query(AuthUser).filter(AuthUser.id == uid).first()
            if not user:
                continue

            profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

            # Respetar la hora configurada salvo que sea forzado por el admin
            user_check_hour = (profile.alert_check_hour if profile and profile.alert_check_hour is not None else DEFAULT_ALERT_CHECK_HOUR)
            if not force and user_check_hour != current_hour:
                continue

            users_processed += 1

            user_segment = (profile.user_type if profile else None) or DEFAULT_USER_TYPE

            for product in db.query(Product).filter(Product.user_id == user_id).all():
                existing = db.query(Alert).filter(Alert.product_id == product.id).all()

                # Sin stock no hay nada que vencer ni que agotar
                if product.stock <= 0:
                    alert_engine.clear_alerts(db, existing, "expiry", "stock_low_coverage", "slow_pace", *alert_engine.LEGACY_TYPES)
                    continue

                # Alerta de vencimiento
                expiry_days = alert_engine.sync_product_expiry(db, product, profile, existing)
                if expiry_days is not None:
                    limit, _ = alert_rules.expiry_limit(product.dias_alerta_vencimiento, profile)
                    sent = await _notify(
                        user, notify, "Producto próximo a vencerse", alert_texts.expiry_body(product.nombre, expiry_days),
                        kind="expiry", product_name=product.nombre, days=expiry_days, limit_days=limit,
                    )
                    alerts_sent += int(sent)

                # Alertas del modelo predictivo: si no responde, las que ya había se conservan tal cual
                events = (
                    db.query(ConsumptionEvent)
                    .filter(ConsumptionEvent.product_id == product.id)
                    .order_by(ConsumptionEvent.consumed_at.asc())
                    .all()
                )
                product_data = {
                    "id": product.id,
                    "stock": product.stock,
                    "stock_minimo": product.stock_minimo,
                    "categoria": product.categoria,
                    "nombre": product.nombre,
                }
                ml_result = await _ml_predict(events, product_data, segment=user_segment)
                if not ml_result:
                    continue

                days_until_stockout = alert_rules.whole_days(ml_result.get("days_until_stockout"))
                daily_rate = ml_result.get("daily_rate")

                # Alerta de stock mínimo (con la reposición sugerida)
                level, _ = alert_engine.apply_coverage(db, product, profile, existing, days_until_stockout, daily_rate)
                if level == "critical":
                    limit, _ = alert_rules.coverage_limit(product.stock_minimo, profile)
                    sent = await _notify(
                        user, notify, "Stock por agotarse", alert_texts.low_coverage_body(product.nombre, days_until_stockout),
                        kind="low_coverage", product_name=product.nombre, days=days_until_stockout,
                        limit_days=limit, daily_rate=daily_rate,
                    )
                    alerts_sent += int(sent)

                # Alerta de ritmo lento vs. vencimiento
                units_wasted = None
                days_until_expiry = None
                if (
                    product.vencimiento is not None
                    and days_until_stockout is not None
                    and daily_rate is not None
                    and daily_rate > 0
                ):
                    days_until_expiry = alert_rules.days_until(product.vencimiento)
                    if 0 < days_until_expiry < days_until_stockout:
                        units_wasted = max(0, product.stock - int(daily_rate * days_until_expiry))
                if alert_engine.apply_slow_pace(db, product, profile, existing, days_until_expiry, units_wasted):
                    sent = await _notify(
                        user, notify, "Riesgo de vencimiento por bajo consumo",
                        alert_texts.slow_pace_body(product.nombre, units_wasted, days_until_expiry),
                        kind="slow_pace", product_name=product.nombre, days=days_until_expiry, units=units_wasted,
                    )
                    alerts_sent += int(sent)

        logger.info(f"Chequeo completado: {alerts_sent} alertas enviadas a {users_processed} usuarios.")
    except Exception:
        logger.exception("Error en el chequeo de cobertura")
    finally:
        db.close()
    return {"alerts_sent": alerts_sent, "users_processed": users_processed}
