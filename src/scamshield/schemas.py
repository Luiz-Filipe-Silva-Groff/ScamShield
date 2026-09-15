"""Contrato externo estrito; erros de validação nunca retornam o input."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain.models import ExtractedDocument, Status


class DocumentInput(BaseModel):
    """Arquivo do boleto. Um boleto por análise; URL e multipart não são aceitos."""

    model_config = ConfigDict(extra="forbid", strict=True)
    mime_type: Literal["application/pdf", "image/jpeg", "image/png"] = Field(
        description="Tipo do arquivo enviado em base64."
    )
    base64: str = Field(
        min_length=4,
        max_length=7 * 1024 * 1024,
        repr=False,
        description=(
            "Conteúdo do arquivo codificado em base64. O arquivo decodificado deve ter "
            "até 5 MiB; PDF até 3 páginas e imagem até 20 milhões de pixels. O limite "
            "desta string é maior porque base64 expande o tamanho original em cerca de "
            "um terço. Arquivo protegido, ilegível ou sem leitura suficiente gera WARNING."
        ),
    )


class AnalysisRequest(BaseModel):
    """Conteúdo da cobrança a analisar.

    Informe `linha_digitavel`, `documento` ou ambos; ao menos um é obrigatório.
    Enviar os dois é o que permite cruzar o que o documento diz com o que o código
    de pagamento codifica.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    linha_digitavel: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        repr=False,
        description=(
            "Linha digitável de 47 dígitos ou os 44 dígitos do código de barras. "
            "Espaços, pontos e hífens são aceitos. Sem documento, a análise fica em "
            "WARNING: o código sozinho não permite conferir o beneficiário. "
            "Arrecadação e convênio geram WARNING por escopo não suportado."
        ),
    )
    documento: DocumentInput | None = Field(
        default=None,
        repr=False,
        description="Arquivo do boleto em base64. Sem ele, não há como verificar quem cobra.",
    )

    @model_validator(mode="after")
    def require_input(self):
        if not self.linha_digitavel and self.documento is None:
            raise ValueError("Envie um documento e/ou linha digitável.")
        return self


FieldName = Literal[
    "beneficiary_name",
    "identifier",
    "nominal_amount_cents",
    "due_date",
    "bank_name",
    "logo_name",
    "payment_code",
]


class DocumentExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    beneficiary_name: str | None = Field(max_length=300, repr=False)
    identifier: str | None = Field(max_length=32, repr=False)
    identifier_type: Literal["CNPJ", "CPF", "UNKNOWN"]
    nominal_amount_cents: int | None = Field(ge=0, le=9999999999)
    due_date: date | None
    bank_name: str | None = Field(max_length=150)
    logo_name: str | None = Field(max_length=150)
    payment_code: str | None = Field(max_length=128, repr=False)
    uncertain_fields: list[FieldName] = Field(max_length=7)

    def to_domain(self) -> ExtractedDocument:
        fields = self.model_dump()
        fields["uncertain_fields"] = frozenset(self.uncertain_fields)
        return ExtractedDocument(**fields)


class SignalResponse(BaseModel):
    code: str
    outcome: str
    group: str
    weight: int
    applied_weight: int
    source: str
    explanation: str


class Details(BaseModel):
    mode: Literal["demo", "live"]
    rules_version: str
    raw_score: int
    signals: list[SignalResponse]
    limitations: list[str]


class AnalysisResponse(BaseModel):
    status: Status
    score: int = Field(ge=0, le=100)
    title: str
    explanation: str
    details: Details
    request_id: UUID


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: UUID
