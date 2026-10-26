from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime
from typing import Literal, Optional

from app.core import barcode


def _codigo_canonico(valor: Optional[str]) -> Optional[str]:
    """Valida el código de barras y lo deja en su forma canónica.

    Se hace en el schema y no en cada endpoint para que ningún camino de alta o
    edición pueda saltearlo: un código que no cierra el dígito verificador —o un
    UPC-A guardado sin normalizar— después no coincide con lo que lee el escáner,
    y el producto deja de encontrarse por código. `CodigoInvalido` hereda de
    `ValueError`, así que llega al cliente como un 422 más, igual que cualquier
    otro campo mal cargado.
    """
    return barcode.normalizar(valor)


# Tope de los campos de reglas de alerta del producto: 7 dígitos para el stock mínimo y 3 para los días de anticipación
STOCK_MINIMO_MAX = 9_999_999
DIAS_ALERTA_VENCIMIENTO_MAX = 999


class ProductCreate(BaseModel):
    nombre: str = Field(..., max_length=20)
    marca: Optional[str] = None
    categoria: str = Field(..., max_length=20)
    stock: int = Field(..., gt=0, le=999999)
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = Field(None, max_length=400)
    imagen_url: Optional[str] = None
    ubicacion: Optional[str] = None
    codigo_barras: Optional[str] = None
    stock_minimo: Optional[int] = Field(None, gt=0, le=STOCK_MINIMO_MAX)
    dias_alerta_vencimiento: Optional[int] = Field(None, gt=0, le=DIAS_ALERTA_VENCIMIENTO_MAX)

    _codigo_barras = field_validator("codigo_barras")(_codigo_canonico)


class ProductUpdate(BaseModel):
    nombre: Optional[str] = Field(None, max_length=20)
    marca: Optional[str] = None
    categoria: Optional[str] = Field(None, max_length=20)
    stock: Optional[int] = Field(None, gt=0, le=999999)
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = Field(None, max_length=400)
    imagen_url: Optional[str] = None
    ubicacion: Optional[str] = None
    codigo_barras: Optional[str] = None
    stock_minimo: Optional[int] = Field(None, gt=0, le=STOCK_MINIMO_MAX)
    dias_alerta_vencimiento: Optional[int] = Field(None, gt=0, le=DIAS_ALERTA_VENCIMIENTO_MAX)

    _codigo_barras = field_validator("codigo_barras")(_codigo_canonico)


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
    codigo_barras: Optional[str] = None
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
    descripcion: Optional[str] = None
    imagen_url: Optional[str] = None
    codigo_barras: Optional[str] = None


class ProductDefaults(BaseModel):
    last_categoria: Optional[str] = None
    last_ubicacion: Optional[str] = None


class ReposicionSuggestion(BaseModel):
    product_id: int
    nombre: str
    stock: int
    imagen_url: Optional[str] = None
    daily_rate: float
    days_until_stockout: Optional[int] = None
    suggested_qty: int


class StockTotalResponse(BaseModel):
    """Stock sumado de los productos que cumplen unos filtros, y cuántos son."""

    stock_total: int
    products: int


class StockChange(BaseModel):
    """Un cambio del stock de un producto: una entrada, una salida o una modificación, con el stock antes y después."""

    id: str
    kind: Literal["entrada", "salida", "modificacion"]
    stock_before: int
    stock_after: int
    quantity: int
    occurred_at: datetime
    producto: ProductResponse
