"""OCR draft matching against the inventory, and discharge from a receipt"""
import pytest

from app.api import products as products_api
from app.models.consumption import ConsumptionEvent
from app.models.product import Product
from app.schemas.ocr import ScanDocType
from app.services import ocr_client, ocr_draft
from tests.conftest import TEST_USER_ID

AUTH = {"Authorization": "Bearer token-de-prueba"}
OTRO_USUARIO = "00000000-0000-0000-0000-000000000000"


def field(value, confidence=0.95):
    """Un ExtractedField como lo devuelve el coordinador."""
    return {"value": value, "confidence": confidence}


def product(id=1, **overrides):
    """Un producto sin base: el emparejado sólo lee sus atributos."""
    data = dict(id=id, user_id=TEST_USER_ID, nombre="Leche entera", categoria="Lácteos", stock=10)
    data.update(overrides)
    return Product(**data)


def add_product(db, **overrides):
    data = dict(user_id=TEST_USER_ID, nombre="Leche entera", categoria="Lácteos", stock=10)
    data.update(overrides)
    row = Product(**data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def alerts(monkeypatch):
    """Registra qué productos pasaron por la evaluación de alertas."""
    evaluated = []

    async def record(product, user, profile, db, stock_increased=False):
        evaluated.append(product.id)

    monkeypatch.setattr(products_api, "_check_product_state", record)
    return evaluated


# ── el borrador, emparejado ───────────────────────────────────────────────────

def test_label_is_matched_against_the_inventory():
    inventory = [product(id=1, nombre="Yogur Ser", marca="Ser"), product(id=2, nombre="Detergente")]

    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {
        "fields": {"nombre_producto": field("YOGUR SER"), "marca": field("Ser")},
    }, inventory)

    assert result.draft.coincidencia_id == 1
    assert [m.nombre for m in result.draft.coincidencias] == ["Yogur Ser"]


def test_a_receipt_abbreviation_is_recognized():
    # Un ticket imprime "PAN ARTESANO BIMBÓ" y el inventario dice "Pan Artesano".
    inventory = [product(id=7, nombre="Pan Artesano", marca="Bimbo")]

    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {
        "fields": {"nombre_producto": field("PAN ARTESANO BIMBÓ")},
    }, inventory)

    assert result.draft.coincidencia_id == 7


def test_without_a_match_the_raw_text_is_kept_for_editing():
    inventory = [product(nombre="Detergente")]

    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {
        "fields": {"nombre_producto": field("Arroz largo fino doble carolina")},
    }, inventory)

    # El nombre entra recortado al máximo del alta, pero el texto completo viaja
    # aparte: el recorte no puede ser la única versión de lo que se leyó.
    assert result.draft.coincidencias == []
    assert result.draft.texto_leido == "Arroz largo fino doble carolina"


def test_a_barcode_matches_by_code_not_by_name():
    # Un código de barras no se parece a un producto: es ese producto.
    inventory = [
        product(id=1, nombre="Ibuprofeno", codigo_barras="7794640172021"),
        product(id=2, nombre="7794640172021"),
    ]

    result = ocr_draft.to_scan_result(ScanDocType.BARCODE, {
        "fields": {"codigo": field("7794640172021", 1.0)},
    }, inventory)

    assert [m.id for m in result.draft.coincidencias] == [1]
    assert result.draft.coincidencias[0].por_codigo is True


def test_a_receipt_counts_the_lines_it_could_not_match():
    inventory = [product(id=1, nombre="Leche entera"), product(id=2, nombre="Yogur Ser")]

    result = ocr_draft.to_scan_result(ScanDocType.RECEIPT, {
        "fields": {"comercio": field("Dia")},
        "items": [
            {"nombre_producto": field("LECHE ENTERA"), "cantidad": field(2)},
            {"nombre_producto": field("YOG SER"), "cantidad": field(1)},
            {"nombre_producto": field("ESPONJA COCINA"), "cantidad": field(3)},
        ],
    }, inventory)

    assert [bool(item.coincidencias) for item in result.items] == [True, True, False]
    # Es el número del aviso "no se pudieron cargar N productos".
    assert result.sin_coincidencia == 1


def test_without_an_inventory_the_draft_is_the_reading_alone():
    # Traducir campos no necesita la base: el inventario es opcional.
    result = ocr_draft.to_scan_result(ScanDocType.PRODUCT_LABEL, {
        "fields": {"nombre_producto": field("Leche entera")},
    })

    assert result.draft.nombre == "Leche entera"
    assert result.draft.coincidencias == []


# ── el endpoint devuelve el borrador emparejado ───────────────────────────────

def test_a_finished_scan_comes_back_matched_with_the_users_products(client, db, monkeypatch):
    mine = add_product(db, nombre="Yogur Ser", marca="Ser")
    add_product(db, nombre="Yogur Ser", marca="Ser", user_id=OTRO_USUARIO)

    async def fake_job(job_id, token):
        return {"job_id": job_id, "status": "done", "doc_type": "product_label", "result": {
            "fields": {"nombre_producto": field("YOGUR SER")},
        }}

    monkeypatch.setattr(ocr_client, "get_job", fake_job)

    draft = client.get("/products/scan/j-1", headers=AUTH).json()["result"]["draft"]

    # Sólo contra el inventario de quien escanea: el producto ajeno, idéntico,
    # no puede aparecer como candidato.
    assert [m["id"] for m in draft["coincidencias"]] == [mine.id]


def test_a_scanned_barcode_comes_back_resolved_to_its_product(client, db, monkeypatch):
    mine = add_product(db, nombre="Ibuprofeno", codigo_barras="7794640172021")

    async def fake_sync(**kwargs):
        return {"doc_type": "barcode", "result": {"fields": {"codigo": field("7794640172021", 1.0)}}}

    monkeypatch.setattr(ocr_client, "sync_scan", fake_sync)

    resp = client.post(
        "/products/scan",
        files={"file": ("codigo.jpg", b"\xff\xd8foto", "image/jpeg")},
        data={"doc_type": "barcode"},
        headers=AUTH,
    )

    assert resp.json()["result"]["draft"]["coincidencia_id"] == mine.id


# ── salida por comprobante ────────────────────────────────────────────────────

def test_salida_discharges_and_records_the_reason(client, db, alerts):
    leche = add_product(db, nombre="Leche entera", stock=10)
    yogur = add_product(db, nombre="Yogur Ser", stock=4)

    resp = client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 2}, {"product_id": yogur.id, "quantity": 1}],
        "comercio": "Dia",
    }, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"procesados": 2, "fallidos": 0, "errores": []}

    db.refresh(leche)
    db.refresh(yogur)
    assert (leche.stock, yogur.stock) == (8, 3)

    events = db.query(ConsumptionEvent).all()
    # Para el ledger y las métricas es un consumo como cualquier otro; lo que lo
    # distingue es el motivo, que es lo que después se ve en el historial.
    assert {e.event_type for e in events} == {"consumed"}
    assert all(e.note == "Documento Comercial - Dia" for e in events)


def test_salida_evaluates_the_alerts_of_each_discharged_product(client, db, alerts):
    # Es la diferencia con el mismo endpoint del backoffice, que no notifica: en
    # la app una salida por comprobante alerta igual que una salida normal.
    leche = add_product(db, nombre="Leche entera", stock=10)
    yogur = add_product(db, nombre="Yogur Ser", stock=4)

    client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 2}, {"product_id": yogur.id, "quantity": 1}],
    }, headers=AUTH)

    assert sorted(alerts) == sorted([leche.id, yogur.id])


def test_a_line_without_stock_does_not_block_the_rest(client, db, alerts):
    leche = add_product(db, nombre="Leche entera", stock=10)
    yogur = add_product(db, nombre="Yogur Ser", stock=1)

    body = client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 2}, {"product_id": yogur.id, "quantity": 5}],
    }, headers=AUTH).json()

    assert (body["procesados"], body["fallidos"]) == (1, 1)
    assert str(yogur.id) in body["errores"][0]
    db.refresh(leche)
    db.refresh(yogur)
    assert (leche.stock, yogur.stock) == (8, 1)
    # Sólo se alerta sobre lo que efectivamente bajó.
    assert alerts == [leche.id]


def test_cannot_discharge_another_users_product(client, db, alerts):
    foreign = add_product(db, user_id=OTRO_USUARIO, stock=5)

    body = client.post("/products/scan/salida", json={
        "items": [{"product_id": foreign.id, "quantity": 1}],
    }, headers=AUTH).json()

    assert body["procesados"] == 0
    assert "no encontrado" in body["errores"][0]
    db.refresh(foreign)
    assert foreign.stock == 5


def test_an_alert_failure_does_not_undo_the_discharge(client, db, monkeypatch):
    # Cuando se alerta, el stock ya bajó y el movimiento ya está en el ledger:
    # reportarlo como fallido haría que el usuario lo repita.
    async def broken(*args, **kwargs):
        raise RuntimeError("el servicio de notificaciones no responde")

    monkeypatch.setattr(products_api, "_check_product_state", broken)
    leche = add_product(db, stock=10)

    resp = client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 3}],
    }, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["procesados"] == 1
    db.refresh(leche)
    assert leche.stock == 7


@pytest.mark.parametrize("motivo", ["sold", "rented", "expired", "consumed"])
def test_salida_records_the_chosen_kind_of_exit(client, db, alerts, motivo):
    leche = add_product(db, stock=10)

    resp = client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 2}],
        "motivo": motivo,
    }, headers=AUTH)

    assert resp.status_code == 200
    assert db.query(ConsumptionEvent).one().event_type == motivo


def test_salida_rejects_an_unknown_kind_of_exit(client, db, alerts):
    leche = add_product(db, stock=10)

    resp = client.post("/products/scan/salida", json={
        "items": [{"product_id": leche.id, "quantity": 2}],
        "motivo": "restocked",
    }, headers=AUTH)

    assert resp.status_code == 422


# ── entrada por comprobante ───────────────────────────────────────────────────

def test_entrada_adds_the_stock_and_records_the_entries(client, db, alerts):
    leche = add_product(db, nombre="Leche entera", stock=10)
    yogur = add_product(db, nombre="Yogur Ser", stock=4)

    resp = client.post("/products/scan/entrada", json={
        "items": [{"product_id": leche.id, "quantity": 5}, {"product_id": yogur.id, "quantity": 1}],
        "comercio": "Dia",
    }, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"procesados": 2, "fallidos": 0, "errores": []}
    db.refresh(leche)
    db.refresh(yogur)
    assert (leche.stock, yogur.stock) == (15, 5)
    events = db.query(ConsumptionEvent).all()
    assert {e.event_type for e in events} == {"restocked"}
    assert all(e.note == "Documento Comercial - Dia" for e in events)


def test_entrada_without_a_shop_keeps_only_the_reason_in_the_note(client, db, alerts):
    leche = add_product(db, stock=1)

    client.post("/products/scan/entrada", json={"items": [{"product_id": leche.id, "quantity": 1}]}, headers=AUTH)

    assert db.query(ConsumptionEvent).one().note == "Documento Comercial"


def test_entrada_evaluates_the_alerts_as_a_stock_increase(client, db, monkeypatch):
    calls = []

    async def record(product, user, profile, db, stock_increased=False):
        calls.append((product.id, stock_increased))

    monkeypatch.setattr(products_api, "_check_product_state", record)
    leche = add_product(db, stock=1)

    client.post("/products/scan/entrada", json={"items": [{"product_id": leche.id, "quantity": 2}]}, headers=AUTH)

    assert calls == [(leche.id, True)]


def test_entrada_reports_a_missing_product_and_a_stock_beyond_the_limit_without_stopping(client, db, alerts):
    full = add_product(db, nombre="Lleno", stock=999999)
    ok = add_product(db, nombre="Bien", stock=1)
    foreign = add_product(db, nombre="Ajeno", stock=5, user_id=OTRO_USUARIO)

    body = client.post("/products/scan/entrada", json={
        "items": [
            {"product_id": full.id, "quantity": 1},
            {"product_id": foreign.id, "quantity": 1},
            {"product_id": ok.id, "quantity": 3},
        ],
    }, headers=AUTH).json()

    assert (body["procesados"], body["fallidos"]) == (1, 2)
    assert any("no puede superar" in e for e in body["errores"])
    assert any("no encontrado" in e for e in body["errores"])
    db.refresh(ok)
    db.refresh(full)
    db.refresh(foreign)
    assert (ok.stock, full.stock, foreign.stock) == (4, 999999, 5)


def test_an_alert_failure_does_not_undo_the_entrada(client, db, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("el servicio de notificaciones no responde")

    monkeypatch.setattr(products_api, "_check_product_state", broken)
    leche = add_product(db, stock=1)

    resp = client.post("/products/scan/entrada", json={"items": [{"product_id": leche.id, "quantity": 2}]}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json()["procesados"] == 1
    db.refresh(leche)
    assert leche.stock == 3


def test_an_empty_entrada_is_rejected(client, db):
    resp = client.post("/products/scan/entrada", json={"items": []}, headers=AUTH)

    assert resp.status_code == 422


def test_an_empty_receipt_is_rejected(client, db):
    resp = client.post("/products/scan/salida", json={"items": []}, headers=AUTH)

    assert resp.status_code == 422


def test_with_several_lots_of_the_same_barcode_the_earliest_expiry_comes_first():
    from datetime import date

    inventory = [
        product(id=1, nombre="Ibuprofeno", codigo_barras="7794640172021", vencimiento=date(2028, 6, 1)),
        product(id=2, nombre="Ibuprofeno", codigo_barras="7794640172021", vencimiento=None),
        product(id=3, nombre="Ibuprofeno", codigo_barras="7794640172021", vencimiento=date(2026, 12, 1)),
    ]

    result = ocr_draft.to_scan_result(ScanDocType.BARCODE, {
        "fields": {"codigo": field("7794640172021", 1.0)},
    }, inventory)

    assert [m.id for m in result.draft.coincidencias] == [3, 1, 2]
    assert result.draft.coincidencia_id == 3
