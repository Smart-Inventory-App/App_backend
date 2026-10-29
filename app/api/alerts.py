from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.alert import Alert
from app.models.product import Product
from app.models.profile import UserProfile
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.alert import AlertResponse
from app.services import alert_engine, alert_rules

router = APIRouter(prefix="/alerts", tags=["alerts"])

# TODO: Implementar paginación

# Alertas que salen de una regla que el usuario configura (los días de anticipación del vencimiento y el stock mínimo,
# en su perfil o en cada producto). El resto las genera el sistema a partir del consumo del usuario.
RULE_ALERT_TYPES = ("expiry", "stock_low_coverage")
# Alertas que calcula el modelo predictivo: siempre se muestran
PREDICTIVE_ALERT_TYPES = ("stock_low_coverage", "slow_pace")
LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}


def alert_origin(alert_type: str) -> str:
    return "rule" if alert_type in RULE_ALERT_TYPES else "system"


def alerts_of_user(db: Session, user_id: str, *filters, level: str | None = None) -> list[AlertResponse]:
    """Alertas del usuario con los datos del producto que necesita la app para mostrarlas.

    Antes de armarlas se ponen al día las de vencimiento y se descartan las huérfanas. El nivel de cada una se calcula
    con las reglas vigentes (no es el que quedó guardado), así un cambio de regla se ve enseguida y el resumen, los
    filtros y la lista siempre coinciden.
    """
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    alert_engine.sync_user_alerts(db, user_id, profile)

    rows = (
        db.query(
            Alert,
            Product.nombre,
            Product.stock,
            Product.vencimiento,
            Product.imagen_url,
            Product.categoria,
            Product.marca,
            Product.stock_minimo,
            Product.dias_alerta_vencimiento,
        )
        .join(Product, Alert.product_id == Product.id)
        .filter(Alert.user_id == UUID(user_id), *filters)
        .all()
    )
    responses = []
    for alert, nombre, stock, vencimiento, imagen_url, categoria, marca, stock_minimo, dias_vencimiento in rows:
        limit_days, scope, alert_level = None, None, alert.level
        if alert.type in ("expiry", "slow_pace"):
            limit_days, scope = alert_rules.expiry_limit(dias_vencimiento, profile)
        if alert.type == "expiry" and vencimiento is not None:
            alert_level = alert_rules.expiry_level(alert_rules.days_until(vencimiento), limit_days) or alert.level
        elif alert.type == "slow_pace" and vencimiento is not None:
            alert_level = "critical" if alert_rules.days_until(vencimiento) < limit_days else "warning"
        elif alert.type == "stock_low_coverage":
            limit_days, scope = alert_rules.coverage_limit(stock_minimo, profile)
            alert_level = alert_rules.coverage_level(alert.days_until_stockout, limit_days)
            if alert_level is None:
                continue  # con la regla de hoy ya no corresponde
        responses.append(AlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            product_id=alert.product_id,
            type=alert.type,
            level=alert_level,
            units_wasted=alert.units_wasted,
            days_until_stockout=alert.days_until_stockout,
            suggested_qty=alert.suggested_qty,
            origin=alert_origin(alert.type),
            limit_days=limit_days,
            rule_scope=scope,
            image_url=imagen_url or None,
            product_name=nombre or None,
            product_stock=stock,
            product_expiry=vencimiento or None,
            product_category=categoria or None,
            product_brand=marca or None,
        ))
    if level is not None:
        responses = [a for a in responses if a.level == level]
    # Primero las de las reglas del usuario; dentro de cada grupo, las críticas antes que las demás
    responses.sort(key=lambda a: (a.origin != "rule", LEVEL_ORDER.get(a.level, 3), -a.id))
    return responses


@router.get("/", response_model=list[AlertResponse])
async def get_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"])


@router.get("/critical_alerts", response_model=list[AlertResponse])
async def get_critical_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], level="critical")


@router.get("/expiry_alerts", response_model=list[AlertResponse])
async def get_expiry_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], Alert.type.in_(["expiry", "slow_pace"]))


@router.get("/stock_alerts", response_model=list[AlertResponse])
async def get_stock_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], Alert.type == "stock_low_coverage")


@router.get("/summary", response_model=dict)
async def get_alert_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Cuántas alertas hay por nivel. Sale de la misma lista que ve el usuario, así los números siempre coinciden.

    `expiring` y `low_stock` son los productos con alertas de la opción «Vencimiento» (vencimiento y ritmo lento) y de
    la opción «Stock» del Centro de Alertas, de cualquier nivel y también las de predicción: lo que muestra el inicio de
    la app, el mismo número de productos que se ve al abrir cada opción.
    """
    alerts = alerts_of_user(db, current_user["sub"])
    count = lambda level: sum(1 for a in alerts if a.level == level)
    products_with = lambda types: len({a.product_id for a in alerts if a.type in types})
    return {
        "critical": count("critical"),
        "warning": count("warning"),
        "info": count("info"),
        "total": len(alerts),
        "expiring": products_with(("expiry", "slow_pace")),
        "low_stock": products_with(("stock_low_coverage",)),
    }
