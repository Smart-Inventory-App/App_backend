from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AlertResponse(BaseModel):
    id: int
    user_id: UUID
    product_id: int
    type: str
    level: str
    units_wasted: Optional[int] = None
    days_until_stockout: Optional[int] = None
    suggested_qty: Optional[int] = None
    # "rule": sale de una regla que configuró el usuario (días de anticipación del vencimiento, stock mínimo);
    # "system": la genera el sistema a partir del consumo (ritmo lento, reposición sugerida)
    origin: str = "system"
    # La regla que se aplicó a esta alerta: cuántos días (vencimiento o stock mínimo) y si es la del producto o la general
    limit_days: Optional[int] = None
    rule_scope: Optional[str] = None
    image_url: Optional[str] = None
    product_name: Optional[str] = None
    product_stock: Optional[int] = None
    product_expiry: Optional[date] = None
    product_category: Optional[str] = None
    product_brand: Optional[str] = None