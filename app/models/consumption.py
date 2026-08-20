from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from app.core.database import Base


class ConsumptionEvent(Base):
    __tablename__ = "consumption_events"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    consumed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
