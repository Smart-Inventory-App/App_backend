from sqlalchemy import Column, DateTime, Integer, String, func
from app.core.database import Base

DEFAULT_STOCK_MINIMO = 10
DEFAULT_DIAS_ALERTA_VENCIMIENTO = 7


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String, primary_key=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    last_categoria = Column(String, nullable=True)
    last_ubicacion = Column(String, nullable=True)
    stock_minimo = Column(Integer, nullable=True)
    dias_alerta_vencimiento = Column(Integer, nullable=True)
    notification_token = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
