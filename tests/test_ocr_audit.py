"""Auditoría de los escaneos de la app (`ocr_scan_audit`).

La tabla es la misma que lee el panel de OCR del backoffice: sin estos renglones
los escaneos del celular no dejarían rastro y el panel sólo vería el uso del
propio backoffice. La foto nunca se guarda: sólo un resumen breve por ejecución.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ocr_audit import OCRScanAudit
from app.services import ocr_audit, ocr_client
from tests.conftest import TEST_USER, TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}
PHOTO = ("foto.jpg", b"\xff\xd8foto-de-prueba", "image/jpeg")


def rows(db):
    db.expire_all()
    return db.query(OCRScanAudit).order_by(OCRScanAudit.id).all()


@pytest.fixture
def coordinator(monkeypatch):
    """Un coordinador de mentira: `state` fija qué responden el escaneo sincrónico y la consulta de jobs."""
    state = {
        "sync": {"result": {"engine": "zbar", "document_confidence": 1.0, "processing_ms": 70,
                            "fields": {"codigo": {"value": "7790742000019", "confidence": 1.0}}, "texto_legible": "7790742000019"}},
        "job": None,
    }

    async def sync_scan(**kwargs):
        if isinstance(state["sync"], Exception):
            raise state["sync"]
        return state["sync"]

    async def get_job(job_id, token):
        return state["job"]

    monkeypatch.setattr(ocr_client, "sync_scan", sync_scan)
    monkeypatch.setattr(ocr_client, "get_job", get_job)
    return state


def done_job(job_id="job-1", doc_type="product_label", **result):
    return {"job_id": job_id, "status": "done", "doc_type": doc_type,
            "result": {"engine": "paddleocr", "document_confidence": 0.9, "processing_ms": 4200,
                       "fields": {"nombre_producto": {"value": "Leche", "confidence": 0.9}}, "texto_legible": "Leche entera", **result}}


# ── código de barras: se resuelve en la misma llamada ────────────────────────

def test_a_barcode_scan_leaves_one_audit_row(client, db, coordinator):
    resp = client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert resp.status_code == 200
    (row,) = rows(db)
    assert (row.origen, row.doc_type, row.status, row.engine) == ("app", "barcode", "done", "zbar")
    assert row.user_email == TEST_USER["email"]
    assert row.user_id == TEST_USER_ID
    assert row.confianza == 1.0
    assert row.processing_ms == 70
    assert row.campos == 1
    assert row.resumen == "7790742000019"
    assert row.job_id is None


def test_a_module_failure_on_a_barcode_scan_is_audited_as_failed(client, db, coordinator):
    coordinator["sync"] = HTTPException(status_code=502, detail="El motor OCR no está disponible")

    resp = client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert resp.status_code == 502
    (row,) = rows(db)
    assert row.status == "failed"
    assert row.resumen == "El motor OCR no está disponible"


def test_an_unreachable_module_counts_as_a_failed_execution(client, db, coordinator):
    coordinator["sync"] = ocr_client.OCRUnavailable("sin conexión")

    resp = client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert resp.status_code == 503
    (row,) = rows(db)
    assert (row.status, row.doc_type) == ("failed", "barcode")


@pytest.mark.parametrize("status_code", [400, 413, 429])
def test_a_rejection_before_running_anything_is_not_an_ocr_failure(client, db, coordinator, status_code):
    """Un cupo agotado o un formato inválido no son fallas del OCR: auditarlas inflaría las fallidas."""
    coordinator["sync"] = HTTPException(status_code=status_code, detail="rechazado")

    resp = client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert resp.status_code == status_code
    assert rows(db) == []


# ── jobs encolados: un renglón cuando terminan, no uno por consulta ──────────

def test_a_finished_job_is_audited_once_however_many_times_it_is_polled(client, db, coordinator):
    coordinator["job"] = done_job()

    for _ in range(5):
        assert client.get("/products/scan/job-1", headers=AUTH).status_code == 200

    (row,) = rows(db)
    assert (row.job_id, row.doc_type, row.status, row.engine) == ("job-1", "product_label", "done", "paddleocr")
    assert row.confianza == 0.9
    assert row.processing_ms == 4200


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_a_job_still_running_is_not_audited_yet(client, db, coordinator, status):
    coordinator["job"] = {"job_id": "job-1", "status": status, "doc_type": "product_label", "result": None}

    client.get("/products/scan/job-1", headers=AUTH)

    assert rows(db) == []


def test_a_failed_job_is_audited_with_its_error(client, db, coordinator):
    coordinator["job"] = {"job_id": "job-2", "status": "failed", "doc_type": "receipt", "result": None,
                          "error": "No se pudo leer la imagen"}

    client.get("/products/scan/job-2", headers=AUTH)

    (row,) = rows(db)
    assert (row.status, row.doc_type, row.resumen) == ("failed", "receipt", "No se pudo leer la imagen")
    assert row.confianza is None


def test_a_receipt_counts_its_lines_not_its_fields(client, db, coordinator):
    coordinator["job"] = done_job(doc_type="receipt", items=[{"nombre_producto": {"value": "A"}}, {"nombre_producto": {"value": "B"}}])
    coordinator["job"]["doc_type"] = "receipt"

    client.get("/products/scan/job-1", headers=AUTH)

    assert rows(db)[0].campos == 2


# ── la auditoría nunca hace fallar un escaneo ─────────────────────────────────

def test_an_audit_error_does_not_cost_the_user_the_reading(client, db, coordinator, monkeypatch, caplog):
    def boom(self, *args, **kwargs):
        raise RuntimeError("la tabla no existe")

    monkeypatch.setattr(Session, "add", boom)

    resp = client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["result"]["draft"]["codigo_barras"] == "7790742000019"
    assert "No se pudo auditar el escaneo" in caplog.text


def test_a_token_without_email_is_audited_by_its_user_id(client, db, coordinator, monkeypatch):
    from app.core.security import get_current_user
    from app.main import app

    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: {"sub": TEST_USER_ID})

    client.post("/products/scan", files={"file": PHOTO}, data={"doc_type": "barcode"}, headers=AUTH)

    assert rows(db)[0].user_email == TEST_USER_ID


# ── resumen de la lectura ─────────────────────────────────────────────────────

def test_the_summary_is_trimmed_and_whitespace_collapsed():
    long_text = "palabra   " * 60

    summary = ocr_audit._resumen({"texto_legible": long_text}, None, "done")

    assert len(summary) == ocr_audit.RESUMEN_MAXIMO
    assert summary.endswith("…")
    assert "  " not in summary


@pytest.mark.parametrize("result, expected", [
    ({}, None),
    ({"fields": "no es un dict"}, None),
    ({"fields": {"a": {"value": "x"}, "b": {"value": None}, "c": "suelto"}}, 1),
    ({"items": [{}, {}, {}], "fields": {"a": {"value": "x"}}}, 3),
])
def test_how_many_things_were_read(result, expected):
    assert ocr_audit._campos(result) == expected


def test_metrics_with_unexpected_types_are_ignored():
    assert ocr_audit._confianza({"document_confidence": "alta"}) is None
    assert ocr_audit._entero("rápido") is None
    assert ocr_audit._resumen({}, None, "done") is None


def test_a_failing_duplicate_check_does_not_block_the_audit():
    """Si ni siquiera se puede consultar la tabla, se sigue: el intento de insertar ya decide qué hacer."""
    class BrokenDb:
        rolled_back = False

        def query(self, *args):
            raise SQLAlchemyError("la tabla no existe")

        def rollback(self):
            self.rolled_back = True

    db = BrokenDb()

    assert ocr_audit._ya_registrado(db, "job-1") is False
    assert db.rolled_back is True
