from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from app.core.database import Base


class ConsumptionEvent(Base):
    __tablename__ = "consumption_events"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    # "consumed": bajó el stock por uso real; "expired": el producto venció sin consumirse
    event_type = Column(String, nullable=False, server_default="consumed")
    consumed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Quién generó el movimiento (distinto de user_id, que es de quién es el inventario)
    actor_email = Column(String, nullable=True)
    # Motivo libre opcional (ej. "vencido en heladera", "pedido especial")
    note = Column(String, nullable=True)
    # Si está seteado, esta fila revierte el efecto de stock de otra fila (ledger append-only:
    # corregir/deshacer nunca muta ni borra una fila, siempre agrega una nueva)
    reverses_event_id = Column(Integer, ForeignKey("consumption_events.id", ondelete="SET NULL"), nullable=True)
