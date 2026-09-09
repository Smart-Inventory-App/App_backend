"""
Cliente del módulo de OCR.

Este backend habla con un solo servicio del módulo: ocr_service, el coordinador.
Los tres motores (Tesseract, EasyOCR, PaddleOCR) viven detrás de él y sus URLs no
se conocen acá, así que cambiar la estrategia de reconocimiento no toca este
repositorio.

La imagen tampoco se guarda acá: `POST /ocr/scan` la sube a image_storage_service
como temporal y la descarta al terminar. Por eso se manda el binario y no una URL.
"""
import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class OCRUnavailable(Exception):
    """El coordinador no respondió, o no está configurado."""


def _base_url() -> str:
    if not settings.OCR_SERVICE_URL:
        raise OCRUnavailable("OCR_SERVICE_URL no está configurada")
    return settings.OCR_SERVICE_URL.rstrip("/")


async def scan(
    *,
    content: bytes,
    filename: str,
    content_type: str,
    doc_type: str,
    token: str,
) -> dict:
    """Encola el procesamiento de una foto y retorna {job_id, status}."""
    try:
        async with httpx.AsyncClient(timeout=settings.OCR_TIMEOUT_SECONDS) as client:
            r = await client.post(
                f"{_base_url()}/ocr/scan",
                files={"file": (filename, content, content_type)},
                data={"doc_type": doc_type},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        raise OCRUnavailable(f"No se pudo contactar al servicio OCR: {e}")

    return _json_or_raise(r)


async def get_job(job_id: str, token: str) -> dict:
    """Estado del escaneo. La app hace polling contra esto."""
    try:
        async with httpx.AsyncClient(timeout=settings.OCR_TIMEOUT_SECONDS) as client:
            r = await client.get(
                f"{_base_url()}/ocr/jobs/{job_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as e:
        raise OCRUnavailable(f"No se pudo contactar al servicio OCR: {e}")

    return _json_or_raise(r)


def unavailable(exc: OCRUnavailable) -> HTTPException:
    """Traduce la caída del módulo a un 503 para el cliente."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"El servicio de escaneo no está disponible: {exc}",
    )


def _json_or_raise(response: httpx.Response) -> dict:
    # Se propaga el código del coordinador
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_detail(response))
    return response.json()


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]

    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail) if detail else response.text[:200]
