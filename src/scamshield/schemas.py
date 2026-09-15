"""Contrato externo estrito; erros de validação nunca retornam o input."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain.models import ExtractedDocument, Status


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mime_type: Literal["application/pdf", "image/jpeg", "image/png"]
    base64: str = Field(min_length=4, max_length=7 * 1024 * 1024, repr=False)


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    linha_digitavel: str | None = Field(default=None, min_length=1, max_length=128, repr=False)
    documento: DocumentInput | None = Field(default=None, repr=False)

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
