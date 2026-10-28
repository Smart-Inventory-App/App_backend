"""Crear, actualizar y borrar las alertas de un producto según las reglas del usuario (ver `alert_rules`).

Lo usan el job diario, los endpoints de productos y la lectura de alertas, así todos aplican exactamente el mismo criterio.
"""
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.product import Product
from app.services import alert_rules
from app.services.restock import suggested_restock

logger = logging.getLogger(__name__)

# Tipos de alerta que ya no existen: la reposición sugerida ahora va dentro de la alerta de stock
LEGACY_TYPES = ("restock",)


def _find(existing: list[Alert], alert_type: str) -> Alert | None:
    return next((alert for alert in existing if alert.type == alert_type), None)


def upsert_alert(
    db: Session, product: Product, existing: list[Alert], alert_type: str, level: str,
    units_wasted: int | None = None, days_until_stockout: int | None = None, suggested_qty: int | None = None,
    commit: bool = True,
) -> tuple[Alert, str]:
    """Deja una sola alerta de ese tipo para el producto, con los datos nuevos. Devuelve la alerta y si se creó,
    cambió de nivel o quedó igual (`created`, `changed`, `same`)."""
    current = _find(existing, alert_type)
    if current is None:
        current = Alert(
            user_id=UUID(str(product.user_id)), product_id=product.id, type=alert_type, level=level,
            units_wasted=units_wasted, days_until_stockout=days_until_stockout, suggested_qty=suggested_qty,
        )
        db.add(current)
        existing.append(current)
        outcome = "created"
    else:
        outcome = "changed" if current.level != level else "same"
        current.level = level
        current.units_wasted = units_wasted
        current.days_until_stockout = days_until_stockout
        current.suggested_qty = suggested_qty
    if commit:
        db.commit()
    return current, outcome


def clear_alerts(db: Session, existing: list[Alert], *alert_types: str, commit: bool = True) -> None:
    """Borra las alertas de esos tipos: la condición que las generó ya no se cumple."""
    for alert in [a for a in existing if a.type in alert_types]:
        db.delete(alert)
        existing.remove(alert)
    if commit:
        db.commit()


def sync_product_expiry(db: Session, product: Product, profile, existing: list[Alert], commit: bool = True) -> int | None:
    """Deja la alerta de vencimiento del producto como corresponde hoy. Devuelve los días que faltan si hay que avisar
    (es crítica y es nueva o acaba de pasar a crítica), o `None`."""
    if product.vencimiento is None or product.stock <= 0:
        clear_alerts(db, existing, "expiry", commit=commit)
        return None
    limit, _ = alert_rules.expiry_limit(product.dias_alerta_vencimiento, profile)
    days = alert_rules.days_until(product.vencimiento)
    level = alert_rules.expiry_level(days, limit)
    if level is None:
        clear_alerts(db, existing, "expiry", commit=commit)
        return None
    _, outcome = upsert_alert(db, product, existing, "expiry", level, commit=commit)
    return days if level == "critical" and outcome != "same" else None


def apply_coverage(
    db: Session, product: Product, profile, existing: list[Alert], days_until_stockout: int | None,
    daily_rate: float | None, commit: bool = True,
) -> tuple[str | None, int]:
    """Deja la alerta de stock (cuántos días alcanza, con la reposición sugerida) según la predicción y el stock mínimo
    del usuario. Devuelve el nivel (o `None` si no hay alerta) y la cantidad sugerida a reponer."""
    days = alert_rules.whole_days(days_until_stockout)
    limit, _ = alert_rules.coverage_limit(product.stock_minimo, profile)
    level = alert_rules.coverage_level(days, limit)
    clear_alerts(db, existing, *LEGACY_TYPES, commit=False)
    if level is None:
        clear_alerts(db, existing, "stock_low_coverage", commit=commit)
        return None, 0
    restock_qty = suggested_restock(daily_rate, limit, product.stock)
    upsert_alert(
        db, product, existing, "stock_low_coverage", level,
        days_until_stockout=days, suggested_qty=restock_qty or None, commit=commit,
    )
    return level, restock_qty


def apply_slow_pace(
    db: Session, product: Product, profile, existing: list[Alert], days_until_expiry: int | None,
    units_wasted: int | None, commit: bool = True,
) -> bool:
    """Alerta de que, al ritmo actual, parte del stock se vence. Crítica si el vencimiento está dentro del límite."""
    if not units_wasted or units_wasted <= 0 or days_until_expiry is None:
        clear_alerts(db, existing, "slow_pace", commit=commit)
        return False
    limit, _ = alert_rules.expiry_limit(product.dias_alerta_vencimiento, profile)
    level = "critical" if days_until_expiry < limit else "warning"
    upsert_alert(db, product, existing, "slow_pace", level, units_wasted=units_wasted, commit=commit)
    return True


def sync_user_alerts(db: Session, user_id: str, profile) -> None:
    """Pone al día lo que se puede saber sin el modelo predictivo: las alertas de vencimiento (que dependen de la fecha
    de hoy y de la regla vigente) y la limpieza de las que quedaron huérfanas o ya no existen. Así lo que se ve en el
    Centro de Alertas nunca queda atrasado respecto de las reglas."""
    products = db.query(Product).filter(Product.user_id == user_id).all()
    alerts = db.query(Alert).filter(Alert.user_id == UUID(str(user_id))).all()
    by_product: dict[int, list[Alert]] = {}
    for alert in alerts:
        by_product.setdefault(alert.product_id, []).append(alert)

    known = {product.id for product in products}
    for alert in alerts:
        if alert.product_id not in known or alert.type in LEGACY_TYPES:
            db.delete(alert)
            by_product[alert.product_id].remove(alert)

    for product in products:
        sync_product_expiry(db, product, profile, by_product.setdefault(product.id, []), commit=False)
    db.commit()
