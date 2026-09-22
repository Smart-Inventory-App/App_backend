from typing import List

from pydantic import BaseModel


class ConsumoPorDia(BaseModel):
    day: str
    quantity: int


class ProductoConsumo(BaseModel):
    product_id: int
    nombre: str
    cantidad: int


class TrendsResponse(BaseModel):
    period_days: int
    total_consumido: int
    total_entradas: int
    consumo_por_dia: List[ConsumoPorDia]
    top_productos: List[ProductoConsumo]
    productos_menos_usados: List[ProductoConsumo]
