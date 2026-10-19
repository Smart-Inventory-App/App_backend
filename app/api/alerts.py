from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.alert import Alert
from app.models.product import Product
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.alert import AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

# TODO: Implementar paginación

def alerts_of_user(db: Session, user_id: str, *filters) -> list[AlertResponse]:
    """Alertas del usuario con los datos del producto que necesita la app para mostrarlas."""
    rows = (
        db.query(
            Alert,
            Product.nombre,
            Product.stock,
            Product.vencimiento,
            Product.imagen_url,
            Product.categoria,
            Product.marca,
        )
        .join(Product, Alert.product_id == Product.id)
        .filter(Alert.user_id == UUID(user_id), *filters)
        .all()
    )
    return [
        AlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            product_id=alert.product_id,
            type=alert.type,
            level=alert.level,
            units_wasted=alert.units_wasted,
            days_until_stockout=alert.days_until_stockout,
            image_url=imagen_url or None,
            product_name=nombre or None,
            product_stock=stock,
            product_expiry=vencimiento or None,
            product_category=categoria or None,
            product_brand=marca or None,
        )
        for alert, nombre, stock, vencimiento, imagen_url, categoria, marca in rows
    ]


@router.get("/", response_model=list[AlertResponse])
async def get_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"])


@router.get("/critical_alerts", response_model=list[AlertResponse])
async def get_critical_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], Alert.level == "critical")


@router.get("/expiry_alerts", response_model=list[AlertResponse])
async def get_expiry_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], Alert.type.in_(["expiry", "slow_pace"]))


@router.get("/stock_alerts", response_model=list[AlertResponse])
async def get_stock_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return alerts_of_user(db, current_user["sub"], Alert.type == "stock_low_coverage")


@router.get("/summary", response_model=dict)
async def get_alert_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    critical_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == UUID(current_user["sub"]), Alert.level == "critical")
            .count()
    )
    warning_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == UUID(current_user["sub"]), Alert.level == "warning")
            .count()
    )
    info_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == UUID(current_user["sub"]), Alert.level == "info")
            .count()
    )
    return {
        "critical": critical_alerts,
        "warning": warning_alerts,
        "info": info_alerts
    }
