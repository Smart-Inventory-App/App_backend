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
    image_url: Optional[str] = None
    product_name: Optional[str] = None
    product_stock: Optional[int] = None
    product_expiry: Optional[date] = None