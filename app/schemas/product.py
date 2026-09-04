from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional


class ProductCreate(BaseModel):
    nombre: str = Field(..., max_length=20)
    marca: Optional[str] = None
    categoria: str = Field(..., max_length=20)
    stock: int = Field(..., gt=0)
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = Field(None, max_length=400)
    imagen_url: Optional[str] = None
    ubicacion: Optional[str] = None
    stock_minimo: Optional[int] = Field(None, gt=0)
    dias_alerta_vencimiento: Optional[int] = Field(None, gt=0)


class ProductUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=20)
    marca: Optional[str] = None
    categoria: Optional[str] = Field(None, max_length=20)
    stock: Optional[int] = Field(None, gt=0)
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = Field(None, max_length=400)
    imagen_url: Optional[str] = None
    ubicacion: Optional[str] = None
    stock_minimo: Optional[int] = Field(None, gt=0)
    dias_alerta_vencimiento: Optional[int] = Field(None, gt=0)


class ProductResponse(BaseModel):
    id: int
    user_id: str
    nombre: str
    marca: Optional[str] = None
    categoria: str
    stock: int
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    ubicacion: Optional[str] = None
    stock_minimo: Optional[int] = None
    dias_alerta_vencimiento: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    merged: bool = False

    class Config:
        from_attributes = True


class ProductSuggestion(BaseModel):
    id: int
    nombre: str
    marca: Optional[str] = None
    categoria: str
    ubicacion: Optional[str] = None
    vencimiento: Optional[date] = None
    stock: int = 0
    stock_minimo: Optional[int] = None
    dias_alerta_vencimiento: Optional[int] = None


class ProductDefaults(BaseModel):
    last_categoria: Optional[str] = None
    last_ubicacion: Optional[str] = None
