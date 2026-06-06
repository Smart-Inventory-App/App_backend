from sqlalchemy import Column, Integer, String, Date, DateTime, func
from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    nombre = Column(String, nullable=False)
    marca = Column(String, nullable=True)
    categoria = Column(String, nullable=False)
    stock = Column(Integer, nullable=False)
    vencimiento = Column(Date, nullable=True)
    descripcion = Column(String, nullable=True)
    imagen_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
