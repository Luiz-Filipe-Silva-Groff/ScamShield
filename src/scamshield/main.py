import asyncio
import json
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from .domain.models import Bank, Institution
from .http.errors import APIError, RequestContextMiddleware, api_error
from .http.routes import request_definitions, router
from .http.security import RateLimiter
from .integrations.brasilapi import BrasilAPI
from .integrations.fakes import DemoCatalog, FakeDocumentReader, FakeRegistry
from .integrations.gemini_reader import GeminiReader
from .services.analysis import AnalysisService
from .settings import DEMO_KEY, Settings


def create_app(settings: Settings | None = None, *, reader=None, registry=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        # Logs destas bibliotecas podem incluir URL com CNPJ ou mensagens de PDF.
        for name in ("httpx", "httpcore", "pypdf"):
            logging.getLogger(name).disabled = True
            logging.getLogger(name).addHandler(logging.NullHandler())
            logging.getLogger(name).propagate = False
        config = settings.data_dir / "config"
        bank_data = json.loads((config / "banks.json").read_text(encoding="utf-8"))
        institution_data = json.loads((config / "institutions.json").read_text(encoding="utf-8"))
        banks = tuple(Bank(b["code"], b["name"], tuple(b["aliases"])) for b in bank_data["banks"])
        institutions = tuple(
            Institution(i["cnpj"], i["name"], tuple(i["aliases"]))
            for i in institution_data["institutions"]
        )
        async with httpx.AsyncClient(
            follow_redirects=False, trust_env=False, limits=httpx.Limits(max_connections=16)
        ) as client:
            if settings.mode == "demo":
                catalog = DemoCatalog(settings.data_dir / "demo")
                app.state.catalog = catalog
                actual_reader = reader or FakeDocumentReader(catalog)
                actual_registry = registry or FakeRegistry(catalog)
            else:
                actual_reader = reader or GeminiReader(
                    client,
                    settings.gemini_api_key.get_secret_value(),
                    settings.gemini_model,
                    settings.reader_timeout,
                )
                actual_registry = registry or BrasilAPI(client, settings.registry_timeout)
            app.state.service = AnalysisService(
                settings, actual_reader, actual_registry, banks, institutions
            )
            app.state.limiter = RateLimiter(settings.rate_limit, settings.rate_window)
            app.state.capacity = asyncio.Semaphore(settings.max_concurrent)
            yield
            app.state.service = None

    app = FastAPI(
        title="ScamShield",
        version="0.1.0",
        lifespan=lifespan,
        description="Risco documental de boletos. IA extrai; regras verificam; o parceiro decide.",
    )
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(APIError, api_error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return await api_error(
            request,
            APIError(422, "invalid_request", "Requisição fora do contrato. Consulte /docs."),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return await api_error(
            request, APIError(exc.status_code, "http_error", "Recurso ou método indisponível.")
        )

    app.include_router(router)

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, description=app.description, routes=app.routes
            )
            schema["components"]["schemas"].update(request_definitions)
            # O exemplo precisa refletir o modo real desta instância: publicado em
            # live, um exemplo fixo em "demo" contradiria toda resposta da API.
            examples = schema["paths"]["/v1/analise"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["examples"]
            for item in examples.values():
                item["value"]["details"]["mode"] = settings.mode
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi

    @app.get("/health", tags=["Operação"])
    async def health():
        return {"status": "ok", "mode": settings.mode, "version": "0.1.0"}

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(settings.web_dir / "index.html")

    app.mount("/static", StaticFiles(directory=settings.web_dir), name="static")

    @app.get("/demo/cases", include_in_schema=False)
    async def demo_cases(request: Request):
        if settings.mode != "demo":
            raise APIError(404, "not_found", "Demonstração indisponível neste modo.")
        return [
            {
                k: case[k]
                for k in ("id", "label", "file", "expected_status", "expected_score", "line")
            }
            for case in request.app.state.catalog.cases
        ]

    @app.get("/demo/access", include_in_schema=False)
    async def demo_access():
        # Em demo a credencial é pública por definição: a instância não chama serviço
        # externo nem gasta cota, e o regulamento pede a credencial divulgada. Por isso
        # uma chave usada numa demo pública não deve ser reaproveitada em live.
        if settings.mode != "demo":
            raise APIError(404, "not_found", "Demonstração indisponível neste modo.")
        # Settings mescla os dicionários de .env e das variáveis de ambiente em vez de
        # substituir um pelo outro, então mais de um parceiro pode chegar aqui. Publicar
        # a chave pública conhecida, quando existir, evita expor uma credencial própria.
        for partner, key in settings.api_keys.items():
            if key.get_secret_value() == DEMO_KEY:
                return {"partner": partner, "key": DEMO_KEY}
        partner, key = next(iter(settings.api_keys.items()))
        return {"partner": partner, "key": key.get_secret_value()}

    @app.get("/demo/files.zip", include_in_schema=False)
    async def demo_archive(request: Request):
        if settings.mode != "demo":
            raise APIError(404, "not_found", "Demonstração indisponível neste modo.")
        return Response(
            request.app.state.catalog.archive,
            media_type="application/zip",
            headers={"content-disposition": 'attachment; filename="scamshield-boletos-demo.zip"'},
        )

    @app.get("/demo/files/{case_id}", include_in_schema=False)
    async def demo_file(case_id: str, request: Request):
        if settings.mode != "demo":
            raise APIError(404, "not_found", "Demonstração indisponível neste modo.")
        for case in request.app.state.catalog.cases:
            if case["id"] == case_id:
                return FileResponse(
                    settings.data_dir / "demo" / case["file"],
                    media_type="application/pdf",
                    filename=case["file"],
                )
        raise APIError(404, "not_found", "Documento de demonstração não encontrado.")

    return app
