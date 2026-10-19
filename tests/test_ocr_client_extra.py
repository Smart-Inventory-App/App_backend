"""Ramas de `ocr_client` que `test_scan.py` no ejercita: el cliente memoizado,
`sync_scan` en su propia llamada (no a través del endpoint), un `get_job`
que sí termina bien, y el caso en que el coordinador no responde JSON."""
import httpx
import pytest
from app.services import ocr_client

@pytest.fixture
def ocr_transport(monkeypatch):
    def install(handler):
        ocr_client._client = None

        def record(request: httpx.Request) -> httpx.Response:
            return handler(request)

        class FakeClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(record)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(ocr_client.httpx, "AsyncClient", FakeClient)

    return install


async def test_close_disposes_of_the_memoized_client(monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    ocr_client._client = None

    created = ocr_client._http()

    assert ocr_client._client is created
    await ocr_client.close()
    assert ocr_client._client is None


async def test_close_is_a_no_op_when_nothing_was_ever_opened():
    ocr_client._client = None

    await ocr_client.close()

    assert ocr_client._client is None


async def test_scan_reports_unavailable_when_the_coordinator_is_unreachable(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")

    def down(request):
        raise httpx.ConnectError("nope")

    ocr_transport(down)

    with pytest.raises(ocr_client.OCRUnavailable):
        await ocr_client.scan(content=b"x", filename="a.jpg", content_type="image/jpeg", doc_type="product_label", token="t")


async def test_sync_scan_sends_the_photo_and_forwards_the_token(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    captured = {}

    def handler(request):
        captured["request"] = request
        return httpx.Response(200, json={"doc_type": "barcode", "result": {}})

    ocr_transport(handler)

    result = await ocr_client.sync_scan(
        content=b"\xff\xd8foto", filename="codigo.jpg", content_type="image/jpeg",
        doc_type="barcode", token="tok",
    )

    assert result["doc_type"] == "barcode"
    request = captured["request"]
    assert str(request.url) == "http://ocr:8003/ocr/sync/upload"
    assert request.headers["authorization"] == "Bearer tok"


async def test_sync_scan_reports_unavailable_when_the_coordinator_is_unreachable(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")

    def down(request):
        raise httpx.ConnectError("nope")

    ocr_transport(down)

    with pytest.raises(ocr_client.OCRUnavailable):
        await ocr_client.sync_scan(content=b"x", filename="a.jpg", content_type="image/jpeg", doc_type="barcode", token="t")


async def test_get_job_returns_the_job_when_the_coordinator_answers(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    ocr_transport(lambda req: httpx.Response(200, json={"job_id": "j1", "status": "done"}))

    result = await ocr_client.get_job("j1", "tok")

    assert result == {"job_id": "j1", "status": "done"}


async def test_a_non_json_error_response_falls_back_to_raw_text(ocr_transport, monkeypatch):
    monkeypatch.setattr(ocr_client.settings, "OCR_SERVICE_URL", "http://ocr:8003")
    ocr_transport(lambda req: httpx.Response(500, text="Internal Server Error"))

    with pytest.raises(Exception) as exc:
        await ocr_client.get_job("j1", "tok")

    assert exc.value.status_code == 500
    assert exc.value.detail == "Internal Server Error"


async def test_close_does_not_fail_when_the_connections_belong_to_a_loop_that_is_already_closed():
    class BrokenClient:
        async def aclose(self):
            raise RuntimeError("Event loop is closed")

    ocr_client._client = BrokenClient()

    await ocr_client.close()

    assert ocr_client._client is None
