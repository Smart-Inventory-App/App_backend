from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.core.security import get_current_user
from app.schemas.ocr import ScanDocType, ScanState
from app.services import ocr_client, ocr_draft
from app.utils.bearer import get_bearer_token

router = APIRouter(prefix="/products/scan", tags=["products-scan"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Mismo tope que aplica image_storage_service a la carpeta temporal
# acá ahorra el viaje de ida y el mensaje de error es más claro.
MAX_BYTES = 10 * 1024 * 1024

@router.post("", response_model=ScanState)
async def create_scan(
    response: Response,
    file: UploadFile = File(...),
    doc_type: ScanDocType = Form(default=ScanDocType.PRODUCT_LABEL),
    token: str = Depends(get_bearer_token),
    current_user: dict = Depends(get_current_user),
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
            reading = await ocr_client.sync_scan(**envio)
            return ScanState(
                status="done",
                doc_type=doc_type,
                result=ocr_draft.to_scan_result(doc_type, reading["result"]),
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

    return ScanState(
        job_id=job["job_id"],
        status=job["status"],
        doc_type=doc_type,
        result=ocr_draft.to_scan_result(doc_type, result) if result else None,
        error=job.get("error"),
        queue_position=job.get("queue_position"),
        estimated_wait_seconds=job.get("estimated_wait_seconds"),
    )


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
