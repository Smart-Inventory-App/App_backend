from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.models.alert import Alert
from app.models.product import Product
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.alert import AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])

# TODO: Implementar paginación

@router.get("/", response_model=list[AlertResponse])
async def get_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product)
            .join(Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user.id)
            .all()
        )
    return [
        AlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            product_id=alert.product_id,
            type=alert.type,
            level=alert.level,
            image_url=alert.product.image_url if alert.product else None,
            product_name=alert.product.nombre if alert.product else None,
            product_stock=alert.product.stock if alert.product else None,
            product_expiry=alert.product.vencimiento if alert.product else None,
        )
        for alert in alerts
    ]

@router.get("/critical_alerts", response_model=list[AlertResponse])
async def get_critical_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product)
            .join(Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user.id, Alert.level == "critical")
            .all()
        )
    return [
        AlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            product_id=alert.product_id,
            type=alert.type,
            level=alert.level,
            image_url=alert.product.image_url if alert.product else None,
            product_name=alert.product.nombre if alert.product else None,
            product_stock=alert.product.stock if alert.product else None,
            product_expiry=alert.product.vencimiento if alert.product else None,
        )
        for alert in alerts
    ]

@router.get("/expiry_alerts", response_model=list[AlertResponse])
async def get_expiry_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product)
            .join(Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user.id, Alert.type == "expiry")
            .all()
        )
    return [
        AlertResponse(
            id=alert.id,
            user_id=alert.user_id,
            product_id=alert.product_id,
            type=alert.type,
            level=alert.level,
            image_url=alert.product.image_url if alert.product else None,
            product_name=alert.product.nombre if alert.product else None,
            product_stock=alert.product.stock if alert.product else None,
            product_expiry=alert.product.vencimiento if alert.product else None,
        )
        for alert in alerts
    ]

@router.get("/summary", response_model=dict)
async def get_alert_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    critical_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user.id, Alert.level == "critical")
            .count()
    )
    warning_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user.id, Alert.level == "warning")
            .count()
    )
    info_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user.id, Alert.level == "info")
            .count()
    )
    return {
        "critical": critical_alerts,
        "warning": warning_alerts,
        "info": info_alerts
    }
