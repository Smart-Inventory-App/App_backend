from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.security import get_current_user
from app.schemas.ocr import ScanCreated, ScanDocType, ScanState
from app.services import ocr_client, ocr_draft
from app.utils.bearer import get_bearer_token

router = APIRouter(prefix="/products/scan", tags=["products-scan"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Mismo tope que aplica image_storage_service a la carpeta temporal
# acá ahorra el viaje de ida y el mensaje de error es más claro.
MAX_BYTES = 10 * 1024 * 1024

@router.post("", response_model=ScanCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    file: UploadFile = File(...),
    doc_type: ScanDocType = Form(default=ScanDocType.PRODUCT_LABEL),
    token: str = Depends(get_bearer_token),
    current_user: dict = Depends(get_current_user),
):
    """
    Sube la foto al módulo de OCR y retorna el identificador del escaneo.

    La imagen no se guarda en este backend ni en la base: el coordinador la sube
    a image_storage_service como temporal y la descarta al terminar.
    """
    content = await _read_image(file)

    try:
        created = await ocr_client.scan(
            content=content,
            filename=file.filename or "scan.jpg",
            content_type=file.content_type or "image/jpeg",
            doc_type=doc_type.value,
            token=token,
        )
    except ocr_client.OCRUnavailable as e:
        raise ocr_client.unavailable(e)

    return ScanCreated(job_id=created["job_id"], status=created.get("status", "queued"))


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
