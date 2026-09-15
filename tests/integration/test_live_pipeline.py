"""Mesmo endpoint com adaptadores reais e transporte externo mockado."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from scamshield.integrations.brasilapi import BrasilAPI
from scamshield.integrations.gemini_reader import GeminiReader
from scamshield.main import create_app
from scamshield.settings import Settings

from .test_http import CASES, load_request


@pytest.mark.parametrize(
    ("registry_status", "expected"),
    [(200, "SAFE"), (404, "WARNING"), (429, "WARNING"), (503, "WARNING")],
)
def test_live_http_pipeline(registry_status, expected):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [{"text": json.dumps(CASES[0]["extraction"])}],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(
            registry_status,
            json={
                "cnpj": "12ABC34501DE35",
                "razao_social": "Horizonte Serviços Ltda",
                "nome_fantasia": "Horizonte",
                "situacao_cadastral": 2,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings(
        _env_file=None,
        mode="live",
        api_keys={"bank": "x" * 32},
        gemini_api_key="test-only",
        gemini_model="mock-model",
    )
    app = create_app(
        settings,
        reader=GeminiReader(client, "test-only", "mock-model", 1),
        registry=BrasilAPI(client, 1),
    )
    with TestClient(app) as api:
        response = api.post("/v1/analise", headers={"X-API-Key": "x" * 32}, json=load_request())
        assert response.status_code == 200
        assert response.json()["status"] == expected
        assert response.json()["details"]["mode"] == "live"
    assert calls == ["generativelanguage.googleapis.com", "brasilapi.com.br"]
