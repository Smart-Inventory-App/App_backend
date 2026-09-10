"""
Cliente del módulo de OCR.

Este backend habla con un solo servicio del módulo: ocr_service, el coordinador.
Los motores viven detrás de él y sus URLs no se conocen acá, así que cambiar la
estrategia de reconocimiento —o replicar un motor— no toca este repositorio.

La imagen tampoco se guarda acá: `POST /ocr/scan` la sube a image_storage_service
como temporal y la descarta al terminar. Por eso se manda el binario y no una URL.
"""
import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class OCRUnavailable(Exception):
    """El coordinador no respondió, o no está configurado."""


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    """
    Cliente memoizado, con pool de conexiones.

    Acá no alcanza con abrir uno por llamada como en el resto del backend: el
    escaneo es asincrónico y la app consulta el estado cada medio segundo hasta
    que termina, así que un solo producto son decenas de conexiones nuevas, y
    con varios clientes a la vez son cientos por minuto. Reusarlas evita ese
    handshake y el goteo de sockets en TIME_WAIT.
    """
    global _client

    if _client is None:
        _client = httpx.AsyncClient(
            timeout=settings.OCR_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    return _client


async def close() -> None:
    """Cierra el pool. La llama el shutdown de la app."""
    global _client

    if _client is not None:
        await _client.aclose()
        _client = None


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
    url = f"{_base_url()}/ocr/scan"
    try:
        r = await _http().post(
            url,
            files={"file": (filename, content, content_type)},
            data={"doc_type": doc_type},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as e:
        raise OCRUnavailable(f"No se pudo contactar al servicio OCR: {e}")

    return _json_or_raise(r)


async def sync_scan(
    *,
    content: bytes,
    filename: str,
    content_type: str,
    doc_type: str,
    token: str,
) -> dict:
    """Procesa la foto y devuelve la lectura en la misma llamada.

    Se usa para el código de barras, que el coordinador decodifica él mismo en
    milisegundos sin tocar un motor OCR. Encolarlo sería pagar la subida a
    Cloudinary, la cola y el polling por un trabajo de 0,2 s: medido, un código
    por esta vía tarda 0,07 s contra los 2,8 s de la vía asincrónica.
    """
    url = f"{_base_url()}/ocr/sync/upload"
    try:
        r = await _http().post(
            url,
            files={"file": (filename, content, content_type)},
            data={"doc_type": doc_type},
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as e:
        raise OCRUnavailable(f"No se pudo contactar al servicio OCR: {e}")

    return _json_or_raise(r)


async def get_job(job_id: str, token: str) -> dict:
    """Estado del escaneo. La app hace polling contra esto."""
    url = f"{_base_url()}/ocr/jobs/{job_id}"
    try:
        r = await _http().get(url, headers={"Authorization": f"Bearer {token}"})
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
    # Se propaga el código del coordinador, y con él el `Retry-After` de un 429:
    # es el único dato que le dice a la app cuándo volver a intentar.
    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=_detail(response),
            headers=_retry_after(response),
        )
    return response.json()


def _retry_after(response: httpx.Response) -> dict | None:
    value = response.headers.get("retry-after")
    return {"Retry-After": value} if value else None


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]

    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail) if detail else response.text[:200]
