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
        db.query(Alert, Product.nombre, Product.stock, Product.vencimiento, Product.imagen_url)
            .join(Product, Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user["sub"])
            .all()
        )
    return [
        AlertResponse(
            id=alert[0].id,
            user_id=alert[0].user_id,
            product_id=alert[0].product_id,
            type=alert[0].type,
            level=alert[0].level,
            image_url=alert[4] if alert[4] else None,
            product_name=alert[1] if alert[1] else None,
            product_stock=alert[2] if alert[2] else None,
            product_expiry=alert[3] if alert[3] else None,
        )
        for alert in alerts
    ]

@router.get("/critical_alerts", response_model=list[AlertResponse])
async def get_critical_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product.nombre, Product.stock, Product.vencimiento, Product.imagen_url)
            .join(Product, Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user["sub"], Alert.level == "critical")
            .all()
        )
    return [
        AlertResponse(
            id=alert[0].id,
            user_id=alert[0].user_id,
            product_id=alert[0].product_id,
            type=alert[0].type,
            level=alert[0].level,
            image_url=alert[4] if alert[4] else None,
            product_name=alert[1] if alert[1] else None,
            product_stock=alert[2] if alert[2] else None,
            product_expiry=alert[3] if alert[3] else None,
        )
        for alert in alerts
    ]

@router.get("/expiry_alerts", response_model=list[AlertResponse])
async def get_expiry_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product.nombre, Product.stock, Product.vencimiento, Product.imagen_url)
            .join(Product, Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user["sub"], Alert.type == "expiry")
            .all()
        )
    return [
        AlertResponse(
            id=alert[0].id,
            user_id=alert[0].user_id,
            product_id=alert[0].product_id,
            type=alert[0].type,
            level=alert[0].level,
            image_url=alert[4] if alert[4] else None,
            product_name=alert[1] if alert[1] else None,
            product_stock=alert[2] if alert[2] else None,
            product_expiry=alert[3] if alert[3] else None,
        )
        for alert in alerts
    ]

@router.get("/stock_alerts", response_model=list[AlertResponse])
async def get_expiry_alerts(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert, Product.nombre, Product.stock, Product.vencimiento, Product.imagen_url)
            .join(Product, Alert.product_id == Product.id)
            .filter(Alert.user_id == current_user["sub"], Alert.type == "stock")
            .all()
        )
    return [
        AlertResponse(
            id=alert[0].id,
            user_id=alert[0].user_id,
            product_id=alert[0].product_id,
            type=alert[0].type,
            level=alert[0].level,
            image_url=alert[4] if alert[4] else None,
            product_name=alert[1] if alert[1] else None,
            product_stock=alert[2] if alert[2] else None,
            product_expiry=alert[3] if alert[3] else None,
        )
        for alert in alerts
    ]

@router.get("/summary", response_model=dict)
async def get_alert_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    critical_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user["sub"], Alert.level == "critical")
            .count()
    )
    warning_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user["sub"], Alert.level == "warning")
            .count()
    )
    info_alerts = (
        db.query(Alert)
            .filter(Alert.user_id == current_user["sub"], Alert.level == "info")
            .count()
    )
    return {
        "critical": critical_alerts,
        "warning": warning_alerts,
        "info": info_alerts
    }
