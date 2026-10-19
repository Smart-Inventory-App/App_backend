import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import products as products_api
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.schemas.ocr import (
    EntradaOCRRequest,
    EntradaOCRResult,
    SalidaOCRRequest,
    SalidaOCRResult,
    ScanDocType,
    ScanResult,
    ScanState,
)
from app.services import ocr_audit, ocr_client, ocr_draft
from app.utils.bearer import get_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products/scan", tags=["products-scan"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Mismo tope que aplica image_storage_service a la carpeta temporal
# acá ahorra el viaje de ida y el mensaje de error es más claro.
MAX_BYTES = 10 * 1024 * 1024

# Motivo con el que queda asentada en el ledger una salida leída de un
# comprobante. Es el mismo texto que usa el backoffice.
MOTIVO_COMPROBANTE = "Documento Comercial"

# Tope de stock de un producto (el mismo que valida el alta de productos).
MAX_STOCK = 999999

@router.post("", response_model=ScanState)
async def create_scan(
    response: Response,
    file: UploadFile = File(...),
    doc_type: ScanDocType = Form(default=ScanDocType.PRODUCT_LABEL),
    token: str = Depends(get_bearer_token),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manda la foto al módulo de OCR.

    Un código de barras vuelve resuelto en esta misma llamada (`200`, con
    `status: "done"`): no pasa por un motor OCR —lo decodifica el coordinador— y
    encolarlo sería pagar la subida a Cloudinary, la cola y el polling por un
    trabajo de 0,2 s. Medido: 0,07 s por esta vía contra 2,8 s por la otra.

    Los demás tipos vuelven encolados (`202`, `status: "queued"`) y hay que
    consultar el estado. Su imagen no se guarda en este backend ni en la base: la
    sube el coordinador a image_storage_service como temporal y la descarta al
    terminar.
    """
    content = await _read_image(file)
    envio = dict(
        content=content,
        filename=file.filename or "scan.jpg",
        content_type=file.content_type or "image/jpeg",
        doc_type=doc_type.value,
        token=token,
    )

    try:
        if doc_type is ScanDocType.BARCODE:
            try:
                reading = await ocr_client.sync_scan(**envio)
            except (HTTPException, ocr_client.OCRUnavailable) as e:
                await ocr_audit.registrar_falla(
                    db, e, user_email=_actor(current_user), user_id=current_user["sub"],
                    origen=ocr_audit.ORIGEN_APP, doc_type=doc_type.value,
                )
                raise
            await run_in_threadpool(
                ocr_audit.registrar,
                db,
                user_email=_actor(current_user),
                user_id=current_user["sub"],
                origen=ocr_audit.ORIGEN_APP,
                doc_type=doc_type.value,
                result=reading["result"],
            )
            return ScanState(
                status="done",
                doc_type=doc_type,
                result=await _translate(doc_type, reading["result"], db, current_user),
            )

        created = await ocr_client.scan(**envio)
    except ocr_client.OCRUnavailable as e:
        raise ocr_client.unavailable(e)

    response.status_code = status.HTTP_202_ACCEPTED
    return ScanState(
        job_id=created["job_id"],
        status=created.get("status", "queued"),
        doc_type=doc_type,
    )


@router.get("/{job_id}", response_model=ScanState)
async def get_scan(
    job_id: str,
    token: str = Depends(get_bearer_token),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Estado del escaneo y, cuando termina, el borrador para el formulario.

    Con `queued` o `processing`, `result` viene vacío. Con `done` trae el
    borrador traducido a los campos del alta; con `failed`, `error` dice por qué.
    """
    try:
        job = await ocr_client.get_job(job_id, token)
    except ocr_client.OCRUnavailable as e:
        raise ocr_client.unavailable(e)

    doc_type = ScanDocType(job["doc_type"])
    result = job.get("result")

    if job["status"] in ("done", "failed"):
        await run_in_threadpool(
            ocr_audit.registrar,
            db,
            user_email=_actor(current_user),
            user_id=current_user["sub"],
            origen=ocr_audit.ORIGEN_APP,
            doc_type=doc_type.value,
            result=result,
            job_id=job["job_id"],
            status=job["status"],
            error=job.get("error"),
        )

    return ScanState(
        job_id=job["job_id"],
        status=job["status"],
        doc_type=doc_type,
        result=await _translate(doc_type, result, db, current_user) if result else None,
        error=job.get("error"),
        queue_position=job.get("queue_position"),
        estimated_wait_seconds=job.get("estimated_wait_seconds"),
    )


@router.post("/salida", response_model=SalidaOCRResult)
async def salida_from_receipt(
    data: SalidaOCRRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Descarga varios productos de un mismo comprobante.

    Llega con los `product_id` que el usuario ya confirmó contra las
    coincidencias, no con nombres: volver a emparejar acá sería decidir de nuevo
    algo que la persona ya decidió mirando la foto.

    El movimiento queda con el tipo de salida elegido (`motivo`, por defecto consumo) y la
    nota `Documento Comercial`, y cada
    renglón se procesa por su cuenta: que a uno le falte stock no puede dejar el
    comprobante a medio aplicar sin que se sepa cuál falló.

    Después de descontar se evalúan las alertas de cada producto, igual que en
    una salida normal (`POST /products/{id}/events`). Es lo que distingue a este
    endpoint de su par del backoffice, que no notifica.
    """
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    note = f"{MOTIVO_COMPROBANTE} - {data.comercio}" if data.comercio else MOTIVO_COMPROBANTE

    processed = 0
    errors: list[str] = []
    discharged: list[Product] = []

    for item in data.items:
        product = (
            db.query(Product)
            .filter(Product.id == item.product_id, Product.user_id == user_id)
            .first()
        )
        if not product:
            errors.append(f"Producto #{item.product_id}: no encontrado")
            continue
        if item.quantity > product.stock:
            errors.append(
                f'Producto #{item.product_id}: "{product.nombre}" tiene {product.stock} '
                f"unidades y pediste sacar {item.quantity}"
            )
            continue

        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=item.quantity,
            event_type=data.motivo,
            actor_email=actor_email,
            note=note,
        ))
        product.stock = max(0, product.stock - item.quantity)
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            errors.append(f"Producto #{item.product_id}: no se pudo registrar la salida ({exc})")
            continue
        db.refresh(product)

        products_api._log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f'{actor_email or user_id} sacó {item.quantity} unidades de "{product.nombre}" '
            f"({MOTIVO_COMPROBANTE}, stock: {product.stock}) desde la app",
        )
        processed += 1
        discharged.append(product)

    await _check_alerts(discharged, user_id, db)

    return SalidaOCRResult(procesados=processed, fallidos=len(errors), errores=errors)


@router.post("/entrada", response_model=EntradaOCRResult)
async def entrada_from_receipt(
    data: EntradaOCRRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ingresa stock de varios productos ya cargados leídos de un mismo comprobante.

    Es la contracara de `/salida`: llega con los `product_id` que el usuario ya
    confirmó contra las coincidencias y solo suma stock (no crea productos), con
    un movimiento de entrada por renglón. Cada renglón se procesa por su cuenta.
    """
    user_id = current_user["sub"]
    actor_email = current_user.get("email")
    note = f"{MOTIVO_COMPROBANTE} - {data.comercio}" if data.comercio else MOTIVO_COMPROBANTE

    processed = 0
    errors: list[str] = []
    restocked: list[Product] = []

    for item in data.items:
        product = (
            db.query(Product)
            .filter(Product.id == item.product_id, Product.user_id == user_id)
            .first()
        )
        if not product:
            errors.append(f"Producto #{item.product_id}: no encontrado")
            continue
        if product.stock + item.quantity > MAX_STOCK:
            errors.append(
                f'Producto #{item.product_id}: "{product.nombre}" tiene {product.stock} '
                f"unidades y no puede superar {MAX_STOCK}"
            )
            continue

        product.stock += item.quantity
        db.add(ConsumptionEvent(
            product_id=product.id,
            user_id=product.user_id,
            quantity=item.quantity,
            event_type="restocked",
            actor_email=actor_email,
            note=note,
        ))
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            errors.append(f"Producto #{item.product_id}: no se pudo registrar la entrada ({exc})")
            continue
        db.refresh(product)

        products_api._log_activity(
            db, "product_updated", actor_email, user_id, actor_email,
            f'{actor_email or user_id} sumó {item.quantity} unidades a "{product.nombre}" '
            f"({MOTIVO_COMPROBANTE}, stock: {product.stock}) desde la app",
        )
        processed += 1
        restocked.append(product)

    await _check_alerts(restocked, user_id, db, stock_increased=True)

    return EntradaOCRResult(procesados=processed, fallidos=len(errors), errores=errors)


async def _check_alerts(discharged: list[Product], user_id: str, db: Session, stock_increased: bool = False) -> None:
    """
    Evalúa las alertas de los productos que efectivamente bajaron de stock.

    Es best-effort a propósito: cuando esto corre, el stock ya se descontó y el
    movimiento ya está en el ledger. Si alertar falla —el usuario no tiene fila
    en `auth_users`, el servicio de notificaciones no responde— la salida sigue
    siendo válida, y reportarla como fallida le haría creer al usuario que tiene
    que repetirla.
    """
    if not discharged:
        return
    try:
        user = products_api._get_user(user_id, db)
        profile = products_api._get_or_create_profile(user_id, db)
    except HTTPException:
        logger.warning("Salida por comprobante sin alertas: el usuario %s no está en auth_users", user_id)
        return

    for product in discharged:
        try:
            await products_api._check_product_state(product, user, profile, db, stock_increased=stock_increased)
        except Exception:
            logger.exception("No se pudieron evaluar las alertas del producto %s", product.id)


async def _translate(
    doc_type: ScanDocType, result: dict[str, Any], db: Session, current_user: dict
) -> ScanResult:
    """Traduce la lectura y la empareja con el inventario, fuera del event loop.

    Emparejar es leer los productos del usuario y compararlos texto contra texto:
    consultas bloqueantes y CPU. Hacerlo dentro de un handler `async` frenaría a
    los demás escaneos que están esperando al coordinador.
    """
    return await run_in_threadpool(_translate_sync, doc_type, result, db, current_user["sub"])


def _translate_sync(
    doc_type: ScanDocType, result: dict[str, Any], db: Session, user_id: str
) -> ScanResult:
    inventory = db.query(Product).filter(Product.user_id == user_id).all()
    return ocr_draft.to_scan_result(doc_type, result, inventory)


def _actor(current_user: dict) -> str:
    """Quién pidió el escaneo, para la auditoría: el email del token, o el id si no lo trae."""
    return current_user.get("email") or str(current_user["sub"])


async def _read_image(file: UploadFile) -> bytes:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        accepted = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Formato '{file.content_type}' no permitido. Formatos aceptados: {accepted}",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío",
        )

    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"La imagen supera el máximo de {MAX_BYTES // (1024 * 1024)} MB",
        )

    return content
