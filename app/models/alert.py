from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func

from app.core.database import Base

EXPIRANCY_ALERT = 0
STOCK_ALERT = 1

class Alert(Base):
    __tablename__ = "alert"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("auth_users.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    type = Column(String(50), nullable=False)
    level = Column(String(50), nullable=False)
    # title = Column(String, nullable=False)
    # body = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
