import asyncio
import base64
import binascii
from dataclasses import asdict
from time import monotonic

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from ..domain.boleto import InvalidBoleto, normalize
from ..infrastructure.audit import record
from ..schemas import AnalysisRequest, AnalysisResponse, ErrorResponse
from .errors import APIError
from .security import authenticate

router = APIRouter()
request_schema = AnalysisRequest.model_json_schema(ref_template="#/components/schemas/{model}")
request_definitions = request_schema.pop("$defs", {})


def example(status, score, title, message):
    return {
        "value": {
            "status": status,
            "score": score,
            "title": title,
            "explanation": message,
            "details": {
                "mode": "demo",
                "rules_version": "1.0",
                "raw_score": score,
                "signals": [],
                "limitations": ["As verificações não confirmam o recebedor efetivo do pagamento."],
            },
            "request_id": "00000000-0000-4000-8000-000000000001",
        }
    }


@router.post(
    "/v1/analise",
    response_model=AnalysisResponse,
    tags=["Análise"],
    summary="Analisa documento e/ou código de um boleto",
    description="JPG, PNG ou PDF em base64. Em demo, use as fixtures fornecidas. SAFE não confirma o recebedor efetivo. A API nunca bloqueia pagamentos.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": request_schema}},
        }
    },
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "SAFE": example(
                            "SAFE",
                            0,
                            "Nenhuma inconsistência encontrada",
                            "Nenhuma inconsistência foi encontrada nas verificações realizadas.",
                        ),
                        "WARNING": example(
                            "WARNING",
                            25,
                            "Confira as informações do boleto",
                            "O nome no boleto difere do cadastro consultado; a cobrança pode envolver um intermediário.",
                        ),
                        "DANGER": example(
                            "DANGER",
                            60,
                            "Inconsistência importante no boleto",
                            "O valor informado no documento é diferente do valor do código de pagamento.",
                        ),
                    }
                }
            }
        },
        **{status: {"model": ErrorResponse} for status in [400, 401, 408, 413, 415, 422, 429, 500]},
    },
)
async def analyze(request: Request, partner: str = Depends(authenticate)):
    settings = request.app.state.settings
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise APIError(
            415,
            "unsupported_media_type",
            "Envie JSON com documento em base64 e/ou linha digitável.",
        )
    if request.headers.get("content-encoding", "identity") != "identity":
        raise APIError(415, "unsupported_encoding", "Corpo comprimido não é aceito.")
    if request.app.state.capacity.locked():
        raise APIError(429, "busy", "O serviço está ocupado. Tente novamente em instantes.", 1)
    await request.app.state.capacity.acquire()
    body = bytearray()
    payload = content = None
    started = monotonic()
    try:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                raise APIError(400, "invalid_length", "Tamanho do corpo inválido.") from None
            if length < 0:
                raise APIError(400, "invalid_length", "Tamanho do corpo inválido.")
            if length > settings.max_body_bytes:
                raise APIError(413, "body_too_large", "O corpo da requisição excede 7 MiB.")
        async with asyncio.timeout(settings.upload_timeout):
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.max_body_bytes:
                    raise APIError(
                        413, "body_too_large", "O corpo da requisição excede o limite permitido."
                    )
                body.extend(chunk)
        try:
            payload = AnalysisRequest.model_validate_json(body)
        except ValidationError:
            raise APIError(
                422,
                "invalid_request",
                "Informe documento válido e/ou linha digitável, seguindo o contrato em /docs.",
            ) from None
        if payload.linha_digitavel:
            try:
                normalize(payload.linha_digitavel)
            except InvalidBoleto:
                raise APIError(
                    422,
                    "invalid_payment_code",
                    "Código de pagamento com formato inválido. Confira os números.",
                ) from None
        mime_type = None
        if payload.documento:
            mime_type = payload.documento.mime_type
            try:
                content = base64.b64decode(payload.documento.base64, validate=True)
            except (ValueError, binascii.Error):
                raise APIError(
                    422, "invalid_base64", "O documento precisa estar codificado em base64 válido."
                ) from None
            if not content:
                raise APIError(422, "empty_document", "O documento está vazio.")
            if len(content) > settings.max_file_bytes:
                raise APIError(413, "file_too_large", "O arquivo excede 5 MiB.")
            payload.documento.base64 = ""  # Evita manter cópia adicional após decodificar.
        body.clear()
        decision = await request.app.state.service.analyze(
            payload.linha_digitavel, content, mime_type
        )
        response = AnalysisResponse(
            status=decision.status,
            score=decision.score,
            title=decision.title,
            explanation=decision.explanation,
            details={
                "mode": settings.mode,
                "rules_version": decision.rules_version,
                "raw_score": decision.raw_score,
                "signals": [asdict(s) for s in decision.signals],
                "limitations": list(decision.limitations),
            },
            request_id=request.state.request_id,
        )
        record(request.state.request_id, partner, decision, (monotonic() - started) * 1000)
        return response
    except TimeoutError:
        raise APIError(
            408, "upload_timeout", "O envio do documento não terminou a tempo."
        ) from None
    except ClientDisconnect:
        raise APIError(400, "disconnected", "O envio foi interrompido.") from None
    except APIError:
        raise
    except Exception:
        # Não deixar uvicorn/SDK imprimir traceback com argumentos ou dados enviados.
        raise APIError(
            500, "internal_error", "Não foi possível concluir a análise por um erro interno."
        ) from None
    finally:
        body.clear()
        payload = content = None
        request.app.state.capacity.release()
