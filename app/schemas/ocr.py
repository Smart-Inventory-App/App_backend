from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ScanDocType(str, Enum):
    """Qué hay en la foto. Cada tipo se procesa con una cadena distinta."""

    PRODUCT_LABEL = "product_label"
    EXPIRY_DATE = "expiry_date"
    RECEIPT = "receipt"
    BARCODE = "barcode"


class ProductDraft(BaseModel):
    """
    Los campos de `ProductCreate` que el OCR pudo leer.
    
    Todos opcionales, incluidos los que el alta exige: un borrador incompleto es
    el caso normal —una etiqueta no dice la categoría ni cuántas unidades compró
    el usuario— y lo que falta lo completa la persona.
    """

    nombre: Optional[str] = Field(default=None, max_length=20)
    marca: Optional[str] = None
    categoria: Optional[str] = Field(default=None, max_length=20)
    stock: Optional[int] = Field(default=None, gt=0)
    vencimiento: Optional[date] = None
    descripcion: Optional[str] = Field(default=None, max_length=400)

    # No son campos de `ProductCreate` (la tabla de productos no los guarda),
    # pero identifican al producto sin ambigüedad.
    codigo_barras: Optional[str] = None
    pais_registro: Optional[str] = Field(
        default=None,
        description="País que registró el código, deducido del prefijo GS1. No es dónde se fabricó.",
    )

    confianzas: dict[str, float] = Field(
        default_factory=dict,
        description="Confianza por campo, de 0 a 1. Bajo 0.85 conviene mostrarlo como sugerencia.",
    )


class ReceiptInfo(BaseModel):
    """Cabecera de un ticket, remito o factura."""

    comercio: Optional[str] = None
    fecha_compra: Optional[date] = None
    total: Optional[float] = None


class ScanResult(BaseModel):
    doc_type: ScanDocType

    draft: Optional[ProductDraft] = Field(
        default=None,
        description="Borrador de un producto. Nulo cuando la foto es un comprobante.",
    )
    items: list[ProductDraft] = Field(
        default_factory=list,
        description="Un borrador por renglón del comprobante. Vacío en los demás tipos.",
    )
    comprobante: Optional[ReceiptInfo] = None

    needs_review: bool = Field(
        default=True,
        description="True si un campo clave no llega al umbral de 0.85. No bloquea el alta: avisa.",
    )
    confianza: float = Field(default=0.0, ge=0.0, le=1.0)

    texto_legible: str = Field(
        default="",
        description="El texto reconocido, para que el usuario lo contraste con la foto.",
    )
    advertencias: list[str] = Field(
        default_factory=list,
        description="Qué pasó al procesar y cambia cómo leer el resultado (motor caído, campo recortado).",
    )


class ScanState(BaseModel):
    """
    Estado de un escaneo, y su resultado cuando ya está.

    Es la única forma que devuelven los dos endpoints. Un código de barras se
    decodifica en el momento y vuelve con `status: "done"` y el borrador adentro,
    sin `job_id`: no hay nada que consultar después. Los demás tipos vuelven en
    `queued` y la app consulta hasta que pasan a `done` o `failed`. La regla para
    el cliente es una sola: si `status` es `done`, ya tenés el resultado.
    """

    job_id: Optional[str] = None
    status: str
    doc_type: ScanDocType
    result: Optional[ScanResult] = None
    error: Optional[str] = None

    queue_position: Optional[int] = Field(
        default=None, description="Lugar en la fila, empezando en 1. Sólo mientras espera."
    )
    estimated_wait_seconds: Optional[int] = Field(
        default=None,
        description=(
            "Cuánto falta, estimado. Está para que la app muestre «3º de 7, ~2 min» "
            "en vez de un spinner sin información."
        ),
    )
