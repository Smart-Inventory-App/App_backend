from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.models.profile import DEFAULT_USER_TYPE, UserProfile
from app.services.alert_job import run_daily_coverage_check

router = APIRouter(prefix="/internal", tags=["internal"])

_token_header = APIKeyHeader(name="X-Internal-Token", auto_error=False)


def _verify_token(token: str = Security(_token_header)):
    if not token or token != settings.INTERNAL_SERVICE_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get("/consumption", dependencies=[Depends(_verify_token)])
def get_all_consumption(db: Session = Depends(get_db)):
    events = db.query(ConsumptionEvent).order_by(ConsumptionEvent.consumed_at.asc()).all()
    return [
        {
            "id": e.id,
            "product_id": e.product_id,
            "user_id": e.user_id,
            "quantity": e.quantity,
            "event_type": e.event_type,
            "consumed_at": e.consumed_at,
        }
        for e in events
    ]


@router.post("/alerts/run", dependencies=[Depends(_verify_token)])
async def trigger_alerts_all():
    """Dispara el chequeo de alertas para todos los usuarios (forzado, ignora hora)."""
    return await run_daily_coverage_check(force=True)


@router.post("/alerts/run/{user_id}", dependencies=[Depends(_verify_token)])
async def trigger_alerts_user(user_id: str, notify: bool = Query(True)):
    """Dispara el chequeo de alertas para un usuario específico (forzado). Con `notify=false` solo actualiza las
    alertas, sin mandar avisos: lo usa el backoffice cuando el usuario cambia una regla o carga un producto."""
    return await run_daily_coverage_check(target_user_id=user_id, force=True, notify=notify)


@router.get("/products", dependencies=[Depends(_verify_token)])
def get_all_products(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    user_types = dict(db.query(UserProfile.user_id, UserProfile.user_type).all())
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "nombre": p.nombre,
            "categoria": p.categoria,
            "stock": p.stock,
            "stock_minimo": p.stock_minimo,
            "vencimiento": str(p.vencimiento) if p.vencimiento else None,
            "user_type": user_types.get(p.user_id) or DEFAULT_USER_TYPE,
        }
        for p in products
    ]
