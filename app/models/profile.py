from sqlalchemy import Column, DateTime, Integer, String, func
from app.core.database import Base

DEFAULT_COVERAGE_DAYS = 7          # días de cobertura mínimos antes de alertar (ML)
DEFAULT_STOCK_MINIMO = DEFAULT_COVERAGE_DAYS  # alias para compatibilidad
DEFAULT_DIAS_ALERTA_VENCIMIENTO = 7
DEFAULT_ALERT_CHECK_HOUR = 8       # hora UTC del chequeo diario de alertas


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
    alert_check_hour = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
