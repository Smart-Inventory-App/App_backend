from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.consumption import ConsumptionEvent
from app.models.product import Product

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


@router.get("/products", dependencies=[Depends(_verify_token)])
def get_all_products(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "nombre": p.nombre,
            "categoria": p.categoria,
            "stock": p.stock,
            "vencimiento": str(p.vencimiento) if p.vencimiento else None,
        }
        for p in products
    ]
