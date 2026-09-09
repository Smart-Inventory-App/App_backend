"""OCR scan endpoint tests"""
from datetime import date

import httpx
import pytest
from fastapi import HTTPException

from app.schemas.ocr import ScanDocType
from app.services import ocr_client, ocr_draft

AUTH = {"Authorization": "Bearer token-de-prueba"}


def field(value, confidence=0.95):
    """Un ExtractedField como lo devuelve el coordinador."""
    return {"value": value, "confidence": confidence}


@pytest.fixture
def ocr_transport(monkeypatch):
    """Reemplaza el cliente de httpx por uno con transporte de mentira."""
    def install(handler):
        captured = {}

        def record(request: httpx.Request) -> httpx.Response:
            captured["request"] = request
            return handler(request)

        class FakeClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(record)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(ocr_client.httpx, "AsyncClient", FakeClient)
        return captured

    return install


# ── draft: etiqueta ───────────────────────────────────────────────────────────

def test_label_fills_nombre_marca_and_descripcion():
    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {
        "fields": {
            "nombre_producto": field("Café Instantáneo", 0.97),
            "marca": field("La Virginia", 1.0),
            "detalles": field("Espuma instantánea en sobres", 0.83),
        },
        "needs_review": False,
        "document_confidence": 0.93,
    })

    assert result.draft.nombre == "Café Instantáneo"
    assert result.draft.marca == "La Virginia"
    assert result.draft.descripcion == "Espuma instantánea en sobres"
    assert result.needs_review is False
    assert result.confianza == 0.93
    assert result.draft.confianzas["nombre"] == 0.97


def test_draft_does_not_invent_categoria():
    # Rellenar un hueco con algo plausible es peor que dejarlo vacío: se confirma
    # el formulario sin releerlo y queda cargado un dato que nadie leyó.
    result = ocr_draft.to_scan_result(
        ScanDocType.PRODUCT_LABEL, {"fields": {"nombre_producto": field("Yogur")}}
    )

    assert result.draft.categoria is None
    assert result.draft.stock is None


def test_long_nombre_is_truncated_by_word_and_warned():
    result = ocr_draft.to_scan_result(
        ScanDocType.PRODUCT_LABEL,
        {"fields": {"nombre_producto": field("Café Instantáneo Clásico Batido")}},
    )

    assert result.draft.nombre == "Café Instantáneo"
    assert len(result.draft.nombre) <= ocr_draft.MAX_NOMBRE
    assert "nombre_recortado" in result.advertencias


def test_single_long_word_is_truncated_anyway():
    result = ocr_draft.to_scan_result(
        ScanDocType.PRODUCT_LABEL, {"fields": {"nombre_producto": field("A" * 40)}}
    )

    assert len(result.draft.nombre) == ocr_draft.MAX_NOMBRE


# ── draft: vencimiento y código de barras ─────────────────────────────────────

def test_expiry_fills_only_the_date():
    result = ocr_draft.to_scan_result(
        ScanDocType.EXPIRY_DATE,
        {"fields": {"fecha_vencimiento": field("2028-03-31", 0.91)}},
    )

    assert result.draft.vencimiento == date(2028, 3, 31)
    assert result.draft.nombre is None
    assert result.draft.confianzas == {"vencimiento": 0.91}


def test_a_date_that_is_not_a_date_does_not_break_the_draft():
    result = ocr_draft.to_scan_result(
        ScanDocType.EXPIRY_DATE, {"fields": {"fecha_vencimiento": field("31/03/28")}}
    )

    assert result.draft.vencimiento is None


def test_barcode_brings_the_gtin_and_its_country():
    result = ocr_draft.to_scan_result(ScanDocType.BARCODE, {
        "fields": {
            "codigo": field("7794640172021", 1.0),
            "simbologia": field("EAN-13", 1.0),
            "pais_registro": field("Argentina", 1.0),
        },
        "needs_review": False,
    })

    assert result.draft.codigo_barras == "7794640172021"
    assert result.draft.pais_registro == "Argentina"
    assert result.needs_review is False


# ── draft: comprobantes ───────────────────────────────────────────────────────

def test_receipt_gives_one_draft_per_line_and_the_header():
    result = ocr_draft.to_scan_result(ScanDocType.RECEIPT, {
        "fields": {
            "comercio": field("DIA ARGENTINA SA", 0.8),
            "fecha_compra": field("2026-08-22", 0.93),
            "total": field(16015.25, 1.0),
        },
        "items": [
            {"nombre_producto": field("PAN ARTESANO BIMBO"), "cantidad": field(1, 0.9)},
            {"nombre_producto": field("YOG FRUT 0% LACTOSA"), "cantidad": field(2, 0.9)},
        ],
        "needs_review": False,
        "document_confidence": 0.91,
    })

    assert result.draft is None
    assert [i.nombre for i in result.items] == ["PAN ARTESANO BIMBO", "YOG FRUT 0% LACTOSA"]
    assert [i.stock for i in result.items] == [1, 2]
    assert result.comprobante.comercio == "DIA ARGENTINA SA"
    assert result.comprobante.fecha_compra == date(2026, 8, 22)
    assert result.comprobante.total == 16015.25


def test_a_line_without_quantity_does_not_invent_stock():
    result = ocr_draft.to_scan_result(
        ScanDocType.RECEIPT,
        {"items": [{"nombre_producto": field("ACEITE"), "cantidad": field(None, 0.0)}]},
    )

    assert result.items[0].stock is None


def test_a_line_without_nombre_is_dropped():
    result = ocr_draft.to_scan_result(
        ScanDocType.RECEIPT,
        {"items": [{"nombre_producto": field(None), "cantidad": field(3)}]},
    )

    assert result.items == []


def test_coordinator_warnings_are_kept():
    # `respaldo_no_disponible` cambia cómo hay que leer una lectura pobre.
    result = ocr_draft.to_scan_result(
        ScanDocType.PRODUCT_LABEL,
        {"fields": {}, "warnings": ["respaldo_no_disponible:paddleocr"]},
    )

    assert "respaldo_no_disponible:paddleocr" in result.advertencias


def test_an_empty_reading_gives_an_empty_draft_needing_review():
    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {})

    assert result.draft.nombre is None
    assert result.needs_review is True
    assert result.confianza == 0.0


# ── cliente ───────────────────────────────────────────────────────────────────

async def test_scan_sends_the_photo_and_forwards_the_token(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    captured = ocr_transport(
        lambda _: httpx.Response(202, json={"job_id": "abc", "status": "queued"})
    )

    created = await ocr_client.scan(
        content=b"\xff\xd8foto",
        filename="envase.jpg",
        content_type="image/jpeg",
        doc_type="product_label",
        token="token-del-usuario",
    )

    assert created["job_id"] == "abc"
    request = captured["request"]
    assert str(request.url) == "http://ocr:8003/ocr/scan"
    assert request.headers["authorization"] == "Bearer token-del-usuario"
    assert b"product_label" in request.content
    assert b"envase.jpg" in request.content
    assert b"\xff\xd8foto" in request.content


async def test_coordinator_error_keeps_its_status_code(ocr_transport, monkeypatch):
    # Un 400 por foto inválida es accionable para el usuario; un 502 no lo es.
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    ocr_transport(lambda _: httpx.Response(400, json={"detail": "El archivo está vacío"}))

    with pytest.raises(HTTPException) as exc:
        await ocr_client.scan(
            content=b"x", filename="x.jpg", content_type="image/jpeg",
            doc_type="product_label", token="t",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "El archivo está vacío"


async def test_an_unreachable_coordinator_is_reported_as_unavailable(
    ocr_transport, monkeypatch
):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")

    def down(request):
        raise httpx.ConnectError("connection refused")

    ocr_transport(down)

    with pytest.raises(ocr_client.OCRUnavailable):
        await ocr_client.get_job("abc", "t")


async def test_without_a_configured_url_the_scan_is_unavailable(monkeypatch):
    # El alta manual no depende del OCR y no debe caerse con él.
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "")

    with pytest.raises(ocr_client.OCRUnavailable):
        await ocr_client.get_job("abc", "t")


# ── endpoints ─────────────────────────────────────────────────────────────────

def test_upload_returns_the_scan_id(client, monkeypatch):
    async def fake_scan(**kwargs):
        assert kwargs["doc_type"] == "expiry_date"
        assert kwargs["token"] == "token-de-prueba"
        return {"job_id": "job-1", "status": "queued"}

    monkeypatch.setattr(ocr_client, "scan", fake_scan)

    resp = client.post(
        "/products/scan",
        files={"file": ("sello.jpg", b"\xff\xd8foto", "image/jpeg")},
        data={"doc_type": "expiry_date"},
        headers=AUTH,
    )

    assert resp.status_code == 202
    assert resp.json() == {"job_id": "job-1", "status": "queued"}


def test_unsupported_format_is_rejected_before_the_network(client):
    resp = client.post(
        "/products/scan",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        headers=AUTH,
    )

    assert resp.status_code == 400
    assert "no permitido" in resp.json()["detail"]


def test_empty_file_is_rejected(client):
    resp = client.post(
        "/products/scan",
        files={"file": ("vacia.jpg", b"", "image/jpeg")},
        headers=AUTH,
    )

    assert resp.status_code == 400


def test_finished_scan_returns_the_draft(client, monkeypatch):
    async def fake_job(job_id, token):
        return {
            "job_id": job_id,
            "status": "done",
            "doc_type": "product_label",
            "result": {
                "fields": {
                    "nombre_producto": field("Ibuprofeno 400 mg", 0.99),
                    "marca": field("IbuEvanol", 0.9),
                },
                "needs_review": False,
                "document_confidence": 0.95,
                "texto_legible": "IbuEvanol Ibuprofeno 400 mg",
            },
            "created_at": "2026-09-09T10:00:00",
            "updated_at": "2026-09-09T10:00:04",
        }

    monkeypatch.setattr(ocr_client, "get_job", fake_job)

    data = client.get("/products/scan/job-1", headers=AUTH).json()

    assert data["status"] == "done"
    assert data["result"]["draft"]["nombre"] == "Ibuprofeno 400 mg"
    assert data["result"]["draft"]["marca"] == "IbuEvanol"
    assert data["result"]["needs_review"] is False


def test_scan_in_progress_has_no_result_yet(client, monkeypatch):
    async def fake_job(job_id, token):
        return {
            "job_id": job_id,
            "status": "processing",
            "doc_type": "receipt",
            "result": None,
            "created_at": "2026-09-09T10:00:00",
            "updated_at": "2026-09-09T10:00:01",
        }

    monkeypatch.setattr(ocr_client, "get_job", fake_job)

    data = client.get("/products/scan/job-1", headers=AUTH).json()

    assert data["status"] == "processing"
    assert data["result"] is None


def test_failed_scan_says_why(client, monkeypatch):
    async def fake_job(job_id, token):
        return {
            "job_id": job_id,
            "status": "failed",
            "doc_type": "product_label",
            "result": None,
            "error": "El motor OCR no está disponible",
            "created_at": "2026-09-09T10:00:00",
            "updated_at": "2026-09-09T10:00:01",
        }

    monkeypatch.setattr(ocr_client, "get_job", fake_job)

    data = client.get("/products/scan/job-1", headers=AUTH).json()

    assert data["status"] == "failed"
    assert data["error"] == "El motor OCR no está disponible"


def test_scan_returns_503_when_the_ocr_module_is_down(client, monkeypatch):
    async def down(**kwargs):
        raise ocr_client.OCRUnavailable("connection refused")

    monkeypatch.setattr(ocr_client, "scan", down)

    resp = client.post(
        "/products/scan",
        files={"file": ("f.jpg", b"\xff\xd8foto", "image/jpeg")},
        headers=AUTH,
    )

    assert resp.status_code == 503


def test_scan_route_does_not_shadow_get_product_by_id(client, db):
    # El router del escaneo se registra antes que el de productos: si ganara
    # /products/{product_id}, esto daría 422 por no poder convertir "scan" a int.
    resp = client.get("/products/9999", headers=AUTH)

    assert resp.status_code == 404
