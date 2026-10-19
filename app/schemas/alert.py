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
    image_url: Optional[str] = None
    product_name: Optional[str] = None
    product_stock: Optional[int] = None
    product_expiry: Optional[date] = None
    product_category: Optional[str] = None
    product_brand: Optional[str] = None