import base64
import builtins
import io
import json
import logging
import socket
import tempfile
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scamshield.main import create_app
from scamshield.settings import DEMO_KEY, Settings

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {"X-API-Key": DEMO_KEY}
CASES = json.loads((ROOT / "src/scamshield/data/demo/manifest.json").read_text(encoding="utf-8"))


def load_request(case_id="safe"):
    return json.loads((ROOT / f"demo/requests/{case_id}.json").read_text(encoding="utf-8"))


@pytest.fixture
def client():
    with TestClient(create_app(Settings(_env_file=None, rate_limit=1000))) as client:
        yield client


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_demo_results_through_real_http_contract(client, case):
    response = client.post("/v1/analise", headers=HEADERS, json=load_request(case["id"]))
    assert response.status_code == 200, response.text
    result = response.json()
    assert list(result) == ["status", "score", "title", "explanation", "details", "request_id"]
    assert result["status"] == case["expected_status"]
    assert result["score"] == case["expected_score"]
    assert result["details"]["mode"] == "demo"
    assert response.headers["x-request-id"] == result["request_id"]
    assert UUID(result["request_id"]).version == 4
    assert response.headers["cache-control"] == "no-store"


def test_documents_without_line_and_line_without_document(client):
    payload = load_request()
    assert (
        client.post(
            "/v1/analise", headers=HEADERS, json={"documento": payload["documento"]}
        ).json()["status"]
        == "SAFE"
    )
    assert (
        client.post(
            "/v1/analise", headers=HEADERS, json={"linha_digitavel": payload["linha_digitavel"]}
        ).json()["status"]
        == "WARNING"
    )


@pytest.mark.parametrize("key", [None, "wrong", "x" * 600])
def test_authentication_before_payload_validation(client, key):
    headers = {"X-API-Key": key} if key else {}
    response = client.post("/v1/analise", headers=headers, content="invalid-json")
    assert response.status_code == 401
    assert "invalid-json" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"linha_digitavel": 123},
        {"linha_digitavel": "12"},
        {"status": "SAFE"},
        {"documento": {"mime_type": "text/plain", "base64": "AAAA"}},
        {"documento": {"mime_type": "application/pdf", "base64": "!!!!"}},
    ],
)
def test_invalid_contract(client, payload):
    response = client.post("/v1/analise", headers=HEADERS, json=payload)
    assert response.status_code == 422
    assert set(response.json()) == {"error", "message", "request_id"}


def test_invalid_json_is_not_echoed(client):
    response = client.post(
        "/v1/analise",
        headers=HEADERS | {"Content-Type": "application/json"},
        content='{"sensitive":"UNIQUE_PRIVATE_MARKER"',
    )
    assert response.status_code == 422
    assert "UNIQUE_PRIVATE_MARKER" not in response.text


def test_unsupported_media_and_encoding(client):
    assert client.post("/v1/analise", headers=HEADERS, content=b"raw pdf").status_code == 415
    assert (
        client.post(
            "/v1/analise", headers=HEADERS | {"Content-Encoding": "gzip"}, json=load_request()
        ).status_code
        == 415
    )


def test_size_limits_and_length_header():
    with TestClient(create_app(Settings(_env_file=None, max_body_bytes=1024))) as client:
        assert client.post("/v1/analise", headers=HEADERS, json=load_request()).status_code == 413
        # Chunked/unknown size cannot bypass the same limit.
        response = client.post(
            "/v1/analise",
            headers=HEADERS | {"Content-Type": "application/json"},
            content=iter([b" " * 700, b" " * 700]),
        )
        assert response.status_code == 413
        assert (
            client.post(
                "/v1/analise",
                headers=HEADERS | {"Content-Type": "application/json", "Content-Length": "-1"},
                content=b"{}",
            ).status_code
            == 400
        )
    with TestClient(create_app(Settings(_env_file=None, max_file_bytes=100))) as client:
        assert client.post("/v1/analise", headers=HEADERS, json=load_request()).status_code == 413


def test_unknown_demo_document_and_corrupt_pdf(client):
    payload = load_request()
    raw = base64.b64decode(payload["documento"]["base64"])
    payload["documento"]["base64"] = base64.b64encode(raw + b"\n").decode()
    result = client.post("/v1/analise", headers=HEADERS, json=payload).json()
    assert result["status"] == "WARNING"
    assert any(s["code"] == "DOCUMENT_UNKNOWN_DEMO_DOCUMENT" for s in result["details"]["signals"])
    payload["documento"]["base64"] = base64.b64encode(b"%PDF-1.4\nUNIQUE_PRIVATE_PDF").decode()
    response = client.post("/v1/analise", headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "WARNING"
    assert "UNIQUE_PRIVATE_PDF" not in response.text


@pytest.mark.parametrize(("format", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_real_image_format_is_accepted_then_demo_degrades(client, format, mime):
    with io.BytesIO() as stream:
        Image.new("RGB", (16, 16), color="white").save(stream, format=format)
        payload = {
            "documento": {"mime_type": mime, "base64": base64.b64encode(stream.getvalue()).decode()}
        }
    response = client.post("/v1/analise", headers=HEADERS, json=payload)
    assert response.status_code == 200
    assert "DOCUMENT_UNKNOWN_DEMO_DOCUMENT" in {
        s["code"] for s in response.json()["details"]["signals"]
    }


def test_rate_limit_is_per_partner():
    settings = Settings(_env_file=None, api_keys={"one": "key-one", "two": "key-two"}, rate_limit=1)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/v1/analise", headers={"X-API-Key": "key-one"}, json=load_request()
            ).status_code
            == 200
        )
        response = client.post("/v1/analise", headers={"X-API-Key": "key-one"}, json=load_request())
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) >= 1
        assert (
            client.post(
                "/v1/analise", headers={"X-API-Key": "key-two"}, json=load_request()
            ).status_code
            == 200
        )


def test_static_demo_and_openapi(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/health").json()["mode"] == "demo"
    assert len(client.get("/demo/cases").json()) == len(CASES)
    assert client.get("/demo/files/safe").content.startswith(b"%PDF-")
    assert client.get("/demo/files/not-found").status_code == 404
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/v1/analise"]["post"]
    assert set(operation["responses"]["200"]["content"]["application/json"]["examples"]) == {
        "SAFE",
        "WARNING",
        "DANGER",
    }
    assert operation["security"] == [{"APIKeyHeader": []}]
    assert "DocumentInput" in schema["components"]["schemas"]


def test_live_never_exposes_demo_files():
    settings = Settings(
        _env_file=None,
        mode="live",
        api_keys={"bank": "x" * 32},
        gemini_api_key="test-only",
        gemini_model="test-model",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/demo/cases").status_code == 404
        assert client.get("/demo/files/safe").status_code == 404
        assert client.get("/health").json()["mode"] == "live"


def test_privacy_no_network_no_document_writes_no_sensitive_logs(client, monkeypatch, caplog):
    payload = load_request()

    def forbidden(*args, **kwargs):
        raise AssertionError("Documento não pode ser persistido ou enviado à rede na demo")

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            forbidden()
        return original_open(file, mode, *args, **kwargs)

    original_open = builtins.open
    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "TemporaryFile", forbidden)
    # socketpair do event loop não é afetado; proibir conexões externas.
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    with caplog.at_level(logging.INFO, logger="scamshield.audit"):
        response = client.post("/v1/analise", headers=HEADERS, json=payload)
    assert response.status_code == 200
    records = [r for r in caplog.records if r.name == "scamshield.audit"]
    assert len(records) == 1
    audit = json.loads(records[0].message)
    assert set(audit) == {
        "request_id",
        "timestamp",
        "partner_id",
        "status",
        "score",
        "signals",
        "latency_ms",
    }
    for private in ["12ABC34501DE35", "Horizonte", payload["documento"]["base64"], DEMO_KEY]:
        assert private not in records[0].message
        assert private not in response.text


def test_unexpected_internal_error_is_sanitized(client):
    async def broken(*args):
        raise RuntimeError("PRIVATE_STACKTRACE_INPUT")

    client.app.state.service.analyze = broken
    response = client.post("/v1/analise", headers=HEADERS, json=load_request())
    assert response.status_code == 500
    assert "PRIVATE_STACKTRACE_INPUT" not in response.text
    assert not client.app.state.capacity.locked()
