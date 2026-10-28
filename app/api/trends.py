from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.consumption import CONSUMPTION_EVENT_TYPES, ConsumptionEvent
from app.models.product import Product
from app.schemas.trends import ConsumoPorDia, ProductoConsumo, TrendsResponse

router = APIRouter(prefix="/trends", tags=["trends"])

# Cuántos productos trae el ranking de los más consumidos
TOP_PRODUCTS = 5


# Hora argentina (UTC-3, sin horario de verano): los días del gráfico se cuentan con ella
AR_TZ = timezone(timedelta(hours=-3))


def _ar_day(moment: datetime):
    """Día calendario argentino de un instante. Sin zona horaria se asume UTC (así se guardan los eventos)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(AR_TZ).date()


@router.get("/", response_model=TrendsResponse)
def get_trends(
    period: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["sub"]
    # Los días son los de Argentina; el servidor puede estar en otra zona y los eventos se guardan en UTC.
    today = datetime.now(AR_TZ).date()
    since = today - timedelta(days=period - 1)
    since_start = datetime.combine(since, time.min, tzinfo=AR_TZ)

    reversed_ids = db.query(ConsumptionEvent.reverses_event_id).filter(
        ConsumptionEvent.reverses_event_id.isnot(None)
    )
    events = (
        db.query(ConsumptionEvent)
        .filter(
            ConsumptionEvent.user_id == user_id,
            ConsumptionEvent.consumed_at >= since_start,
            ConsumptionEvent.reverses_event_id.is_(None),
            ConsumptionEvent.id.notin_(reversed_ids),
        )
        .all()
    )

    total_consumido = sum(e.quantity for e in events if e.event_type in CONSUMPTION_EVENT_TYPES)
    total_entradas = sum(e.quantity for e in events if e.event_type == "restocked")

    per_day: dict[str, int] = {}
    for e in events:
        if e.event_type not in CONSUMPTION_EVENT_TYPES:
            continue
        day = _ar_day(e.consumed_at).isoformat()
        per_day[day] = per_day.get(day, 0) + e.quantity

    consumo_por_dia = []
    for i in range(period - 1, -1, -1):
        d = today - timedelta(days=i)
        consumo_por_dia.append(ConsumoPorDia(day=d.isoformat(), quantity=per_day.get(d.isoformat(), 0)))

    per_product: dict[int, int] = {}
    for e in events:
        if e.event_type not in CONSUMPTION_EVENT_TYPES:
            continue
        per_product[e.product_id] = per_product.get(e.product_id, 0) + e.quantity

    product_ids = list(per_product.keys())
    names = {}
    if product_ids:
        names = {
            p.id: p.nombre
            for p in db.query(Product.id, Product.nombre).filter(Product.id.in_(product_ids)).all()
        }

    # Los lotes de un mismo producto (mismo nombre, con otro vencimiento o marca) cuentan como uno solo: el ranking
    # nunca repite un producto
    grouped: dict[str, dict] = {}
    for pid, qty in per_product.items():
        name = names.get(pid, f"Producto #{pid}")
        entry = grouped.setdefault(" ".join(name.lower().split()), {"product_id": pid, "nombre": name, "best": qty, "cantidad": 0})
        entry["cantidad"] += qty
        if qty > entry["best"]:
            entry.update(product_id=pid, nombre=name, best=qty)

    ranked = sorted(
        (ProductoConsumo(product_id=e["product_id"], nombre=e["nombre"], cantidad=e["cantidad"]) for e in grouped.values()),
        key=lambda p: (-p.cantidad, p.nombre.lower()),
    )

    return TrendsResponse(
        period_days=period,
        total_consumido=total_consumido,
        total_entradas=total_entradas,
        consumo_por_dia=consumo_por_dia,
        top_productos=ranked[:TOP_PRODUCTS],
    )
