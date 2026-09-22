from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.schemas.trends import ConsumoPorDia, ProductoConsumo, TrendsResponse

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("/", response_model=TrendsResponse)
def get_trends(
    period: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["sub"]
    today = date.today()
    since = today - timedelta(days=period - 1)

    reversed_ids = db.query(ConsumptionEvent.reverses_event_id).filter(
        ConsumptionEvent.reverses_event_id.isnot(None)
    )
    events = (
        db.query(ConsumptionEvent)
        .filter(
            ConsumptionEvent.user_id == user_id,
            func.date(ConsumptionEvent.consumed_at) >= since,
            ConsumptionEvent.reverses_event_id.is_(None),
            ConsumptionEvent.id.notin_(reversed_ids),
        )
        .all()
    )

    total_consumido = sum(e.quantity for e in events if e.event_type == "consumed")
    total_entradas = sum(e.quantity for e in events if e.event_type == "restocked")

    per_day: dict[str, int] = {}
    for e in events:
        if e.event_type != "consumed":
            continue
        day = e.consumed_at.date().isoformat()
        per_day[day] = per_day.get(day, 0) + e.quantity

    consumo_por_dia = []
    for i in range(period - 1, -1, -1):
        d = today - timedelta(days=i)
        consumo_por_dia.append(ConsumoPorDia(day=d.isoformat(), quantity=per_day.get(d.isoformat(), 0)))

    per_product: dict[int, int] = {}
    for e in events:
        if e.event_type != "consumed":
            continue
        per_product[e.product_id] = per_product.get(e.product_id, 0) + e.quantity

    product_ids = list(per_product.keys())
    names = {}
    if product_ids:
        names = {
            p.id: p.nombre
            for p in db.query(Product.id, Product.nombre).filter(Product.id.in_(product_ids)).all()
        }

    ranked = sorted(
        (
            ProductoConsumo(product_id=pid, nombre=names.get(pid, f"Producto #{pid}"), cantidad=qty)
            for pid, qty in per_product.items()
        ),
        key=lambda p: p.cantidad,
        reverse=True,
    )

    return TrendsResponse(
        period_days=period,
        total_consumido=total_consumido,
        total_entradas=total_entradas,
        consumo_por_dia=consumo_por_dia,
        top_productos=ranked[:5],
        productos_menos_usados=list(reversed(ranked[-5:])) if len(ranked) > 5 else [],
    )
