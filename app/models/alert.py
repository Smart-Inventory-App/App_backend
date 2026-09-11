from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func, UUID

from app.core.database import Base

EXPIRANCY_ALERT = 0
STOCK_ALERT = 1

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth_users.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    type = Column(String(50), nullable=False)
    level = Column(String(50), nullable=False)
    units_wasted = Column(Integer, nullable=True)
    days_until_stockout = Column(Integer, nullable=True)
