"""
Registro de auditoría de los escaneos hechos desde la app.

Es la contraparte de `backoffice_backend/app/core/ocr_audit.py`: los dos escriben
en la misma tabla para que el panel de OCR muestre el uso de todos los usuarios,
vengan del celular o del backoffice. La regla es la misma —un renglón breve por
ejecución, nunca la foto— y por eso las dos copias tienen que quedar iguales.
"""
import logging
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ocr_audit import OCRScanAudit

logger = logging.getLogger(__name__)

RESUMEN_MAXIMO = 160
ORIGEN_APP = "app"


def registrar(
    db: Session,
    *,
    user_email: str,
    origen: str,
    doc_type: str,
    result: Optional[dict[str, Any]] = None,
    job_id: Optional[str] = None,
    user_id: Optional[str] = None,
    status: str = "done",
    error: Optional[str] = None,
) -> None:
    """
    Deja constancia de una ejecución. Nunca hace fallar a quien la llama.

    Un problema al auditar —la tabla todavía no existe porque el backoffice no
    arrancó, la base no responde— no puede tumbar un escaneo que salió bien: el
    usuario perdería la lectura por un renglón de historial.
    """
    if job_id and _ya_registrado(db, job_id):
        return

    result = result or {}

    try:
        db.add(
            OCRScanAudit(
                job_id=job_id,
                user_id=user_id,
                user_email=user_email,
                origen=origen,
                doc_type=doc_type,
                engine=result.get("engine") or None,
                status=status,
                confianza=_confianza(result),
                processing_ms=_entero(result.get("processing_ms")),
                campos=_campos(result),
                resumen=_resumen(result, error, status),
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("No se pudo auditar el escaneo %s: %s", job_id or "(sincrónico)", e)


async def registrar_falla(db: Session, error, **datos) -> None:
    """
    Deja constancia de un escaneo sincrónico que el módulo no pudo resolver.

    Sólo cuenta una falla del lado del módulo (5xx, o que no se lo pudo
    contactar): un 429 por cupo o un 400 por formato se rechazan antes de correr
    nada, y auditarlos inflaría las fallidas con cosas que no son fallas del OCR.
    """
    if getattr(error, "status_code", 503) < 500:
        return
    await run_in_threadpool(
        registrar, db, status="failed", error=str(getattr(error, "detail", error)), **datos
    )


def _ya_registrado(db: Session, job_id: str) -> bool:
    """Un job encolado se consulta muchas veces y termina una sola: sin este corte habría un renglón por consulta."""
    try:
        return db.query(OCRScanAudit.id).filter(OCRScanAudit.job_id == job_id).first() is not None
    except SQLAlchemyError:
        db.rollback()
        return False


def _confianza(result: dict[str, Any]) -> Optional[float]:
    valor = result.get("document_confidence")
    return float(valor) if isinstance(valor, (int, float)) else None


def _entero(valor: Any) -> Optional[int]:
    return int(valor) if isinstance(valor, (int, float)) else None


def _campos(result: dict[str, Any]) -> Optional[int]:
    """Cuántas cosas se leyeron: renglones en un comprobante, campos en el resto."""
    items = result.get("items")
    if items:
        return len(items)

    fields = result.get("fields")
    if not isinstance(fields, dict):
        return None
    return sum(1 for campo in fields.values() if isinstance(campo, dict) and campo.get("value") is not None)


def _resumen(result: dict[str, Any], error: Optional[str], status: str) -> Optional[str]:
    """Un recorte de lo leído, o el motivo de la falla."""
    texto = error if status == "failed" else result.get("texto_legible")
    if not texto:
        return None

    texto = " ".join(str(texto).split())
    if len(texto) <= RESUMEN_MAXIMO:
        return texto
    return texto[: RESUMEN_MAXIMO - 1].rstrip() + "…"
