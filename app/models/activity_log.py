from sqlalchemy import Column, DateTime, Integer, String, func

from app.core.database import Base


class AdminActivityLog(Base):
    """Tabla compartida con el backoffice (`admin_activity_log`, creada por ese
    servicio) donde se registra actividad para la pantalla de Auditoría:
    altas/ediciones/bajas de productos hechas desde la app, y registros de
    usuarios nuevos."""

    __tablename__ = "admin_activity_log"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)
    actor_email = Column(String, nullable=True)
    target_user_id = Column(String, nullable=True)
    target_email = Column(String, nullable=True)
    description = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
