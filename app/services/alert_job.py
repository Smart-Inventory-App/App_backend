"""
Job que corre cada hora y envía alertas a los usuarios cuya hora de chequeo
configurada coincide con la hora UTC actual.
"""
import logging
from datetime import date, datetime, timezone
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.ml_client import predict as _ml_predict
from app.services.notifications import NotificationService
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_ALERT_CHECK_HOUR, DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_OVERSTOCK_DAYS, DEFAULT_USER_TYPE, UserProfile
from app.models.user import AuthUser
from app.models.alert import Alert

logger = logging.getLogger(__name__)
notification_service = NotificationService(api_url=settings.NOTIFICATION_SERVICE_URL)

def _create_alert(product: Product, alert_type: str, alert_level: str, db: Session, units_wasted: int, stockout_date: int) -> None:
    alert = Alert(
        user_id=UUID(product.user_id),
        product_id=product.id,
        type=alert_type,
        level=alert_level,
        units_wasted=units_wasted,
        days_until_stockout=stockout_date
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    print(f"\n\nSe creó alerta de tipo '{alert_type}' y nivel '{alert_level}' para el producto '{product.nombre}'\n\n")

def _delete_alert(product: Product, alert_type: str, db: Session) -> None:
    db.query(Alert).filter(
        Alert.user_id == UUID(product.user_id),
        Alert.product_id == product.id,
        Alert.type == alert_type,
    ).delete()
    db.commit()
    print(f"\n\nSe eliminó alerta de tipo '{alert_type}' para el producto '{product.nombre}'\n\n")

def _clear_alert(product: Product, alert_type: str, existing_types: set[str], db: Session) -> None:
    """Borra la alerta de ese tipo si existe: la condición que la generó ya no se cumple."""
    if alert_type in existing_types:
        _delete_alert(product, alert_type, db)


async def run_daily_coverage_check(
    target_user_id: str | None = None,
    force: bool = False,
) -> dict:
    """
    Evalúa alertas de cobertura.
    - target_user_id: si se pasa, solo procesa ese usuario.
    - force: si True, ignora el filtro de hora configurada.
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
            if not user or not user.firebase_token:
                continue

            profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

            # Respetar la hora configurada salvo que sea forzado por el admin
            user_check_hour = (profile.alert_check_hour if profile and profile.alert_check_hour is not None else DEFAULT_ALERT_CHECK_HOUR)
            if not force and user_check_hour != current_hour:
                continue

            users_processed += 1

            user_segment = (profile.user_type if profile else None) or DEFAULT_USER_TYPE
            coverage_threshold = (profile.stock_minimo if profile else None) or DEFAULT_COVERAGE_DAYS
            expiry_threshold = (profile.dias_alerta_vencimiento if profile else None) or DEFAULT_DIAS_ALERTA_VENCIMIENTO

            products = (
                db.query(Product)
                .filter(Product.user_id == user_id, Product.stock > 0)
                .all()
            )

            for product in products:
                existing_types = {row[0] for row in db.query(Alert.type).filter(Alert.product_id == product.id).all()}

                # Alerta de vencimiento
                if product.vencimiento:
                    days_to_expiry = (product.vencimiento - date.today()).days
                    if days_to_expiry > expiry_threshold:
                        _clear_alert(product, "expiry", existing_types, db)
                    if 0 <= days_to_expiry < expiry_threshold:
                        _delete_alert(product, "expiry", db)
                        _create_alert(product, "expiry", "warning" if days_to_expiry > 1 else "critical", db, None, None)
                        await notification_service.send_notification(
                            user.firebase_token,
                            "Producto próximo a vencerse",
                            f"{product.nombre} vence en {days_to_expiry} días.",
                            user.email
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
                    "stock_minimo": product.stock_minimo,
                    "categoria": product.categoria,
                    "nombre": product.nombre,
                }
                ml_result = await _ml_predict(events, product_data, segment=user_segment)
                if ml_result:
                    days_until_stockout = ml_result.get("days_until_stockout")
                    daily_rate = ml_result.get("daily_rate")

                    # Alerta de bajo stock
                    if days_until_stockout is None or days_until_stockout >= coverage_threshold:
                        _clear_alert(product, "stock_low_coverage", existing_types, db)
                    if days_until_stockout is not None and days_until_stockout < coverage_threshold:
                        label = "día" if days_until_stockout == 1 else "días"
                        _delete_alert(product, "stock_low_coverage", db)
                        _create_alert(product, "stock_low_coverage", "warning" if days_until_stockout > 1 else "critical", db, None, days_until_stockout)
                        await notification_service.send_notification(
                            user.firebase_token,
                            "Stock por agotarse",
                            f"{product.nombre} se agotará en aproximadamente {days_until_stockout} {label}.",
                            user.email
                        )
                        alerts_sent += 1

                    # Alerta de ritmo lento vs. vencimiento
                    slow_pace_risk = False
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
                                slow_pace_risk = True
                                _delete_alert(product, "slow_pace", db)
                                _create_alert(product, "slow_pace", "warning", db, units_wasted, None)
                                await notification_service.send_notification(
                                    user.firebase_token,
                                    "Riesgo de vencimiento por bajo consumo",
                                    f"Al ritmo actual, {units_wasted} unidad{'es' if units_wasted != 1 else ''} de {product.nombre} vencer{'án' if units_wasted != 1 else 'á'} en {days_until_expiry} días.",
                                    user.email
                                )
                                alerts_sent += 1
                    if not slow_pace_risk:
                        _clear_alert(product, "slow_pace", existing_types, db)

        logger.info(f"Chequeo completado: {alerts_sent} alertas enviadas a {users_processed} usuarios.")
    except Exception:
        logger.exception("Error en el chequeo de cobertura")
    finally:
        db.close()
    return {"alerts_sent": alerts_sent, "users_processed": users_processed}
