"""
Traduce una lectura de ocr_service a un borrador del formulario de alta.

El criterio es que el borrador no inventa: lo que el OCR no leyó queda vacío para
que lo complete el usuario. Rellenar un hueco con un valor plausible es peor que
dejarlo vacío, porque se confirma el formulario sin releerlo.
"""
from datetime import date
from typing import Any, Iterable, Optional

from app.core import matching
from app.models.product import Product
from app.schemas.ocr import ProductDraft, ProductMatch, ReceiptInfo, ScanDocType, ScanResult

# Máximos de `ProductCreate`.
MAX_NOMBRE = 20
MAX_DESCRIPCION = 400


def to_scan_result(
    doc_type: ScanDocType,
    result: dict[str, Any],
    inventory: Optional[Iterable[Product]] = None,
) -> ScanResult:
    """Arma el borrador a partir del OCRResult que devolvió el coordinador.

    Con `inventory` —los productos del usuario— cada borrador vuelve además
    emparejado: qué productos que ya tiene podrían ser el que escaneó. Sin él,
    el borrador es la lectura sola, que es lo que alcanza para traducir campos.
    """
    fields = result.get("fields") or {}
    warnings = list(result.get("warnings") or [])
    products = list(inventory) if inventory is not None else []

    if doc_type is ScanDocType.RECEIPT:
        items, receipt = _from_receipt(fields, result.get("items") or [], warnings, products)
        draft = None
    else:
        items, receipt = [], None
        draft = _from_single(doc_type, fields, warnings, products)

    return ScanResult(
        doc_type=doc_type,
        draft=draft,
        items=items,
        comprobante=receipt,
        needs_review=bool(result.get("needs_review", True)),
        confianza=float(result.get("document_confidence") or 0.0),
        texto_legible=result.get("texto_legible") or "",
        advertencias=warnings,
        sin_coincidencia=sum(1 for item in items if not item.coincidencias),
    )


def _from_single(
    doc_type: ScanDocType,
    fields: dict[str, Any],
    warnings: list[str],
    products: list[Product],
) -> ProductDraft:
    """Un producto por foto: etiqueta, sello de vencimiento o código de barras."""
    draft = ProductDraft()
    confidences: dict[str, float] = {}

    def take(ocr_field: str, draft_field: str, value) -> None:
        if value is None:
            return
        setattr(draft, draft_field, value)
        confidences[draft_field] = _confidence(fields, ocr_field)

    if doc_type is ScanDocType.PRODUCT_LABEL:
        read_name = _text(fields, "nombre_producto")
        draft.texto_leido = read_name
        take("nombre_producto", "nombre",
             _truncate(read_name, MAX_NOMBRE, "nombre", warnings))
        take("marca", "marca", _text(fields, "marca"))
        take("detalles", "descripcion",
             _truncate(_text(fields, "detalles"), MAX_DESCRIPCION, "descripcion", warnings))
        _match_by_name(draft, read_name, products)

    elif doc_type is ScanDocType.EXPIRY_DATE:
        take("fecha_vencimiento", "vencimiento", _date(fields, "fecha_vencimiento"))

    elif doc_type is ScanDocType.BARCODE:
        code = _text(fields, "codigo")
        take("codigo", "codigo_barras", code)
        take("pais_registro", "pais_registro", _text(fields, "pais_registro"))
        draft.texto_leido = code
        _match_by_barcode(draft, code, products)

    draft.confianzas = confidences
    return draft


def _from_receipt(
    fields: dict[str, Any],
    items: list[dict[str, Any]],
    warnings: list[str],
    products: list[Product],
) -> tuple[list[ProductDraft], ReceiptInfo]:
    """
    Varios productos por foto: un borrador por renglón, más la cabecera.

    La cantidad del renglón es el stock del alta: es lo que el usuario acaba de
    comprar. La categoría y el vencimiento no salen de un ticket, así que quedan
    vacíos.
    """
    drafts: list[ProductDraft] = []

    for item in items:
        nombre = _value(item.get("nombre_producto"))
        if not nombre:
            continue

        cantidad = _value(item.get("cantidad"))
        legible = isinstance(cantidad, (int, float)) and cantidad >= 1

        draft = ProductDraft(
            nombre=_truncate(str(nombre), MAX_NOMBRE, "nombre", warnings),
            stock=int(cantidad) if legible else None,
            texto_leido=str(nombre),
            confianzas={
                "nombre": _confidence(item, "nombre_producto"),
                "stock": _confidence(item, "cantidad"),
            },
        )
        _match_by_name(draft, str(nombre), products)
        drafts.append(draft)

    receipt = ReceiptInfo(
        comercio=_text(fields, "comercio"),
        fecha_compra=_date(fields, "fecha_compra"),
        total=_number(fields, "total"),
    )

    return drafts, receipt


def _match_by_name(draft: ProductDraft, read_name: Optional[str], products: list[Product]) -> None:
    """Cuelga del borrador los productos del usuario que podrían ser éste."""
    found = matching.buscar(read_name, products)
    draft.coincidencias = [_to_match(product, score) for product, score in found]

    if found and found[0][1] >= matching.UMBRAL_CONFIABLE:
        draft.coincidencia_id = found[0][0].id


def _match_by_barcode(draft: ProductDraft, code: Optional[str], products: list[Product]) -> None:
    """
    Un código de barras no se parece a un producto: es ese producto.

    Por eso no pasa por el emparejado difuso ni por el umbral. Si ningún producto
    tiene ese código, el borrador vuelve sin coincidencias y la app abre un alta
    nueva con el código ya cargado.
    """
    if not code:
        return
    # Dos lotes del mismo producto comparten código y difieren en el vencimiento.
    # Van primero los que vencen antes —y los sin fecha al final—, que es el que
    # conviene sacar primero y el mismo orden que usa la búsqueda por código.
    same = sorted(
        (product for product in products if product.codigo_barras == code),
        key=lambda product: (product.vencimiento is None, product.vencimiento or date.max, product.id),
    )
    draft.coincidencias = [_to_match(product, 1.0, by_barcode=True) for product in same]
    if same:
        draft.coincidencia_id = same[0].id


def _to_match(product: Product, score: float, by_barcode: bool = False) -> ProductMatch:
    return ProductMatch(
        id=product.id,
        nombre=product.nombre,
        marca=product.marca,
        categoria=product.categoria,
        ubicacion=product.ubicacion,
        vencimiento=product.vencimiento,
        stock=product.stock or 0,
        codigo_barras=product.codigo_barras,
        score=round(score, 3),
        por_codigo=by_barcode,
    )


def _value(field: Any) -> Any:
    return field.get("value") if isinstance(field, dict) else None


def _confidence(container: dict[str, Any], name: str) -> float:
    field = container.get(name)
    return float(field.get("confidence") or 0.0) if isinstance(field, dict) else 0.0


def _text(fields: dict[str, Any], name: str) -> Optional[str]:
    value = _value(fields.get(name))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(fields: dict[str, Any], name: str) -> Optional[float]:
    value = _value(fields.get(name))
    return float(value) if isinstance(value, (int, float)) else None


def _date(fields: dict[str, Any], name: str) -> Optional[date]:
    """El coordinador normaliza toda fecha a ISO YYYY-MM-DD antes de devolverla."""
    text = _text(fields, name)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _truncate(
    text: Optional[str], maximo: int, field: str, warnings: list[str]
) -> Optional[str]:
    """
    Ajusta el texto al máximo del formulario, cortando por palabra si se puede.

    Cortar a la mitad de una palabra da un nombre que el usuario no reconoce, y
    que el campo llegue recortado se avisa: quien revisa el borrador tiene que
    saber que ahí falta texto.
    """
    if text is None or len(text) <= maximo:
        return text

    cut = text.rfind(" ", 0, maximo + 1)
    warnings.append(f"{field}_recortado")

    return text[: cut if cut > 0 else maximo].rstrip()
