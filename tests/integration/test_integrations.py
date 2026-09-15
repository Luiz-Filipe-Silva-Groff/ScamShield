import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from scamshield.domain.models import DocumentFailure, RegistryFailure, RegistryResult, RegistryState
from scamshield.infrastructure.cache import TTLCache
from scamshield.integrations.brasilapi import BrasilAPI
from scamshield.integrations.document_reader import ReaderError
from scamshield.integrations.fakes import DemoCatalog, FakeDocumentReader, FakeRegistry
from scamshield.integrations.gemini_reader import GeminiReader
from scamshield.integrations.http_client import retry_seconds
from scamshield.services.analysis import AnalysisService
from scamshield.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
CN = "12ABC34501DE35"
COMPANY = {
    "cnpj": CN,
    "razao_social": "Empresa Exemplo Ltda",
    "nome_fantasia": "Empresa Exemplo",
    "situacao_cadastral": 2,
}


@pytest.mark.parametrize(
    ("status", "state", "failure"),
    [
        (400, RegistryState.INVALID, RegistryFailure.UNAVAILABLE),
        (404, RegistryState.NOT_FOUND, RegistryFailure.UNAVAILABLE),
        (429, RegistryState.UNAVAILABLE, RegistryFailure.RATE_LIMITED),
        (500, RegistryState.UNAVAILABLE, RegistryFailure.UNAVAILABLE),
        (503, RegistryState.UNAVAILABLE, RegistryFailure.UNAVAILABLE),
        (302, RegistryState.UNAVAILABLE, RegistryFailure.UNAVAILABLE),
    ],
)
async def test_registry_http_failures(status, state, failure):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, headers={"Retry-After": "12"})
        )
    ) as client:
        result = await BrasilAPI(client, 1).lookup(CN, TTLCache(10))
    assert (result.state, result.failure) == (state, failure)


async def test_registry_query_validation_bounded_response_and_request_scoped_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=COMPANY | {"qsa": [{"nome_socio": "PRIVATE_PARTNER_NAME"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BrasilAPI(client, 1)
        cache = TTLCache(5)
        result = await adapter.lookup(CN, cache)
        assert result.legal_name == COMPANY["razao_social"]
        assert await adapter.lookup(CN, cache) == result
        assert len(calls) == 1
        assert str(calls[0].url) == f"https://brasilapi.com.br/api/cnpj/v1/{CN}"
        cache.clear()
        await adapter.lookup(CN, cache)
        assert len(calls) == 2
        assert (await adapter.lookup("INVALID", cache)).state == RegistryState.INVALID
        assert len(calls) == 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        COMPANY | {"cnpj": "00000000000191"},
        COMPANY | {"situacao_cadastral": "2"},
        COMPANY | {"razao_social": ""},
    ],
)
async def test_registry_rejects_invalid_payload(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await BrasilAPI(client, 1).lookup(CN, TTLCache(5))
        assert result.failure == RegistryFailure.INVALID_RESPONSE


@pytest.mark.parametrize(
    "content", [b"invalid json", b" " * (128 * 1024 + 1)], ids=["malformed", "oversized"]
)
async def test_bounded_bad_registry_response(content):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=content))
    ) as client:
        assert (
            await BrasilAPI(client, 1).lookup(CN, TTLCache(5))
        ).failure == RegistryFailure.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (httpx.ReadTimeout, RegistryFailure.TIMEOUT),
        (httpx.ConnectError, RegistryFailure.UNAVAILABLE),
    ],
)
async def test_registry_transport_errors(error, failure):
    def handler(request):
        raise error("PRIVATE_URL")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (await BrasilAPI(client, 1).lookup(CN, TTLCache(5))).failure == failure


async def test_registry_429_cooldown():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = BrasilAPI(client, 1)
        for _ in range(2):
            assert (await adapter.lookup(CN, TTLCache(5))).failure == RegistryFailure.RATE_LIMITED
        assert len(calls) == 1


def gemini_response(extraction):
    return {
        "candidates": [
            {"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(extraction)}]}}
        ]
    }


@pytest.fixture
def extraction():
    return json.loads(
        (ROOT / "src/scamshield/data/demo/manifest.json").read_text(encoding="utf-8")
    )[0]["extraction"]


async def test_gemini_uses_inline_document_schema_header_and_configured_model(extraction):
    def handler(request):
        assert request.headers["x-goog-api-key"] == "test-only"
        assert request.url.path.endswith("/models/configured-model:generateContent")
        assert not request.url.query
        body = json.loads(request.content)
        assert (
            base64.b64decode(body["contents"][0]["parts"][0]["inlineData"]["data"]) == b"document"
        )
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "status" not in body["generationConfig"]["responseJsonSchema"]["properties"]
        assert body["store"] is False
        assert "tools" not in body
        return httpx.Response(200, json=gemini_response(extraction))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GeminiReader(client, "test-only", "configured-model", 1).read(
            b"document", "application/pdf"
        )
    assert result.identifier == CN
    assert result.due_date.isoformat() == "2026-09-20"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (429, DocumentFailure.RATE_LIMITED),
        (500, DocumentFailure.UNAVAILABLE),
        (401, DocumentFailure.UNAVAILABLE),
    ],
)
async def test_gemini_http_failures(status, reason):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = GeminiReader(client, "test-only", "model", 1)
        with pytest.raises(ReaderError) as caught:
            await adapter.read(b"test", "application/pdf")
        assert caught.value.reason == reason
        if status == 429:
            with pytest.raises(ReaderError):
                await adapter.read(b"test", "application/pdf")
            assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"finishReason": "MAX_TOKENS"}]},
        gemini_response({"status": "SAFE"}),
        {"candidates": None},
    ],
)
async def test_gemini_invalid_or_truncated_output(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ReaderError) as caught:
            await GeminiReader(client, "test-only", "model", 1).read(b"test", "application/pdf")
        assert caught.value.reason == DocumentFailure.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (httpx.ReadTimeout, DocumentFailure.TIMEOUT),
        (httpx.ConnectError, DocumentFailure.UNAVAILABLE),
    ],
)
async def test_gemini_transport_failure(error, reason):
    def handler(request):
        raise error("PRIVATE_DOCUMENT")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ReaderError) as caught:
            await GeminiReader(client, "test-only", "model", 1).read(b"test", "application/pdf")
        assert caught.value.reason == reason
        assert "PRIVATE_DOCUMENT" not in str(caught.value)


@pytest.mark.parametrize("model", ["../other", "https://example.com", "", "model?key=x"])
def test_gemini_model_is_not_a_url(model):
    with pytest.raises(ValueError):
        GeminiReader(None, "test-only", model, 1)


def test_ttl_expiry_capacity_and_clear():
    now = [0.0]
    cache = TTLCache(ttl=5, capacity=2, clock=lambda: now[0])
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    cache.put("b", 4)
    assert cache.get("b") == 4
    now[0] = 5
    assert cache.get("b") is None
    cache.clear()
    assert cache.get("c") is None


@pytest.mark.parametrize(
    "value", [None, "invalid", "0", "-9", "900", "Mon, 14 Sep 2026 12:00:00 GMT"]
)
def test_retry_after_is_bounded(value):
    assert 1 <= retry_seconds(value) <= 300


async def test_deadline_cancels_reader_without_background_work(banks, institutions):
    stopped = asyncio.Event()

    class SlowReader:
        async def read(self, *args):
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

    catalog = DemoCatalog(ROOT / "src/scamshield/data/demo")
    settings = Settings(_env_file=None, analysis_timeout=0.05, reader_timeout=1)
    service = AnalysisService(settings, SlowReader(), FakeRegistry(catalog), banks, institutions)
    raw = (catalog.directory / "safe.pdf").read_bytes()
    result = await service.analyze(catalog.cases[0]["line"], raw, "application/pdf")
    assert result.status == "WARNING"
    assert stopped.is_set()
    assert "DOCUMENT_TIMEOUT" in {s.code for s in result.signals}


async def test_registry_waits_for_extraction_and_cache_is_discarded(banks, institutions):
    catalog = DemoCatalog(ROOT / "src/scamshield/data/demo")
    events = []

    class Reader(FakeDocumentReader):
        async def read(self, *args):
            events.append("read")
            return await super().read(*args)

    class Registry(FakeRegistry):
        async def lookup(self, cnpj, cache):
            events.append("registry")
            self.cache = cache
            cache.put(cnpj, RegistryResult(RegistryState.FOUND))
            return await super().lookup(cnpj, cache)

    registry = Registry(catalog)
    service = AnalysisService(
        Settings(_env_file=None), Reader(catalog), registry, banks, institutions
    )
    await service.analyze(None, (catalog.directory / "safe.pdf").read_bytes(), "application/pdf")
    assert events == ["read", "registry"]
    assert registry.cache.get(CN) is None


async def test_registry_timeout_preserves_verified_amount_signal(banks, institutions):
    catalog = DemoCatalog(ROOT / "src/scamshield/data/demo")

    class SlowRegistry:
        async def lookup(self, cnpj, cache):
            await asyncio.sleep(10)

    settings = Settings(_env_file=None, registry_timeout=0.01)
    service = AnalysisService(
        settings, FakeDocumentReader(catalog), SlowRegistry(), banks, institutions
    )
    result = await service.analyze(
        None, (catalog.directory / "amount_danger.pdf").read_bytes(), "application/pdf"
    )
    assert (result.status, result.score) == ("DANGER", 70)
    assert "REGISTRY_TIMEOUT" in {s.code for s in result.signals}


async def test_external_registry_bug_degrades_without_content(banks, institutions):
    catalog = DemoCatalog(ROOT / "src/scamshield/data/demo")

    class BrokenRegistry:
        async def lookup(self, *args):
            raise RuntimeError("PRIVATE_INPUT")

    service = AnalysisService(
        Settings(_env_file=None), FakeDocumentReader(catalog), BrokenRegistry(), banks, institutions
    )
    result = await service.analyze(
        None, (catalog.directory / "safe.pdf").read_bytes(), "application/pdf"
    )
    assert result.status == "WARNING"
    assert "PRIVATE_INPUT" not in result.explanation
