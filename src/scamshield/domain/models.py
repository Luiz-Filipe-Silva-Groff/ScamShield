"""Dados internos efêmeros; não serializar evidências em logs."""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Source(StrEnum):
    PARTNER = "partner"
    DOCUMENT = "document"


class Format(StrEnum):
    COLLECTION = "collection"
    UNSUPPORTED = "unsupported"


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class Status(StrEnum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"


class RegistryState(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class RegistryFailure(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    UNAVAILABLE = "unavailable"


class DocumentFailure(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    UNREADABLE = "unreadable"
    UNKNOWN_DEMO_DOCUMENT = "unknown_demo_document"


@dataclass(frozen=True)
class Bank:
    code: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Institution:
    cnpj: str
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, repr=False)
class ParsedBoleto:
    format: Format
    source: Source
    barcode: str = ""
    bank_code: str | None = None
    bank_name: str | None = None
    currency: str | None = None
    amount_cents: int | None = None
    due_factor: int | None = None
    due_date_candidates: tuple[date, ...] = ()
    field_dvs: tuple[bool, ...] = ()
    general_dv: bool | None = None

    @property
    def valid_dvs(self) -> bool:
        return self.general_dv is True and all(self.field_dvs)


@dataclass(frozen=True, repr=False)
class ExtractedDocument:
    beneficiary_name: str | None = None
    identifier: str | None = None
    identifier_type: str = "CNPJ"
    nominal_amount_cents: int | None = None
    due_date: date | None = None
    bank_name: str | None = None
    logo_name: str | None = None
    payment_code: str | None = None
    # Os adaptadores incluem aqui campos ilegíveis, ambíguos ou contraditórios.
    uncertain_fields: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, repr=False)
class RegistryResult:
    state: RegistryState
    cnpj: str | None = None
    legal_name: str | None = None
    trade_name: str | None = None
    situation: int | None = None
    failure: RegistryFailure = RegistryFailure.UNAVAILABLE


@dataclass(frozen=True, repr=False)
class AnalysisEvidence:
    boleto: ParsedBoleto | None = None
    document: ExtractedDocument | None = None
    registry: RegistryResult | None = None
    banks: tuple[Bank, ...] = ()
    institutions: tuple[Institution, ...] = ()
    document_failure: DocumentFailure | None = None


@dataclass(frozen=True)
class EvaluatedSignal:
    code: str
    outcome: Outcome
    group: str
    weight: int
    source: str
    explanation: str
    applied_weight: int = 0


@dataclass(frozen=True)
class Decision:
    status: Status
    score: int
    title: str
    explanation: str
    signals: tuple[EvaluatedSignal, ...]
    raw_score: int
    rules_version: str = "1.0"
    limitations: tuple[str, ...] = (
        "As verificações não confirmam o recebedor efetivo do pagamento.",
        "O score representa pesos de sinais, não probabilidade de fraude.",
    )
