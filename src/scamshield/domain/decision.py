"""Único módulo de política: regras, fuzzy, pesos, faixas e mensagens.

Função pura: recebe evidências, não lê arquivos, não chama rede e não guarda dados.
Pesos máximos sem evidência forte: cadastro 25 + vencimento 10 + banco 10
+ incerteza 10 = 55. DANGER começa em 60; indisponibilidade nunca basta.
"""

import re
import unicodedata
from dataclasses import replace
from datetime import date
from difflib import SequenceMatcher

from .boleto import InvalidBoleto, parse_boleto
from .identifiers import normalize_cnpj, valid_cnpj
from .models import (
    AnalysisEvidence,
    Decision,
    DocumentFailure,
    EvaluatedSignal,
    ExtractedDocument,
    Format,
    Outcome,
    RegistryFailure,
    RegistryState,
    Source,
    Status,
)


def normalize_name(value: str) -> str:
    plain = "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )
    words = re.sub(r"[^a-z0-9]+", " ", plain).split()
    while words and words[-1] in {"sa", "ltda", "eireli", "limitada"}:
        words.pop()
    if words[-2:] == ["s", "a"]:
        words = words[:-2]
    return " ".join(words)


def names_match(name: str, candidates: tuple[str, ...]) -> bool:
    normalized = normalize_name(name)
    if not normalized:
        return False
    for candidate in candidates:
        other = normalize_name(candidate)
        if normalized == other:
            return True
        # Nomes curtos exigem correspondência exata; substring não prova vínculo.
        if (
            min(len(normalized), len(other)) > 5
            and SequenceMatcher(None, normalized, other, autojunk=False).ratio() >= 0.90
        ):
            return True
    return False


def _signal(
    code: str, outcome: Outcome, group: str, weight: int, message: str, source: str
) -> EvaluatedSignal:
    return EvaluatedSignal(code, outcome, group, weight, source, message)


def _unknown(code: str, message: str, source: str = "document") -> EvaluatedSignal:
    return _signal(code, Outcome.UNKNOWN, "incerteza", 10, message, source)


def _readable(doc: ExtractedDocument, name: str) -> bool:
    value = getattr(doc, name)
    return name not in doc.uncertain_fields and value is not None and value != ""


def _identity(evidence: AnalysisEvidence) -> list[EvaluatedSignal]:
    doc, registry = evidence.document, evidence.registry
    if doc is None or not _readable(doc, "identifier"):
        return [
            _unknown(
                "IDENTIFIER_UNREADABLE",
                "Não foi possível ler a identificação de quem está cobrando.",
            )
        ]
    if doc.identifier_type != "CNPJ":
        return [
            _unknown(
                "IDENTIFIER_UNSUPPORTED",
                "Não foi possível consultar o cadastro de quem está cobrando.",
            )
        ]
    if not valid_cnpj(doc.identifier):
        return [
            _unknown(
                "CNPJ_INVALID", "Não foi possível confirmar a identificação impressa no boleto."
            )
        ]
    if registry is None:
        return [
            _unknown(
                "REGISTRY_MISSING",
                "O cadastro de quem está cobrando não foi consultado.",
                "registry",
            )
        ]
    if registry.state != RegistryState.FOUND:
        if registry.state == RegistryState.NOT_FOUND:
            return [
                _unknown(
                    "REGISTRY_NOT_FOUND",
                    "O cadastro não foi encontrado na base consultada.",
                    "registry",
                )
            ]
        if registry.state == RegistryState.INVALID:
            return [
                _unknown(
                    "REGISTRY_INVALID",
                    "Não foi possível consultar a identificação informada.",
                    "registry",
                )
            ]
        messages = {
            RegistryFailure.TIMEOUT: "A consulta ao cadastro não terminou a tempo.",
            RegistryFailure.RATE_LIMITED: "O serviço de consulta ao cadastro está temporariamente sobrecarregado.",
            RegistryFailure.INVALID_RESPONSE: "A consulta ao cadastro retornou informações que não foi possível conferir.",
            RegistryFailure.UNAVAILABLE: "O serviço de consulta ao cadastro está indisponível.",
        }
        return [
            _unknown("REGISTRY_" + registry.failure.name, messages[registry.failure], "registry")
        ]
    if normalize_cnpj(registry.cnpj) != normalize_cnpj(doc.identifier):
        return [
            _unknown(
                "REGISTRY_IDENTIFIER_MISMATCH",
                "A consulta não retornou o cadastro solicitado.",
                "registry",
            )
        ]
    signals = []
    if registry.situation in (1, 4, 8):
        signals.append(
            _signal(
                "REGISTRY_IRREGULAR",
                Outcome.FAIL,
                "cadastro",
                60,
                "O cadastro consultado de quem está cobrando consta como nulo, inapto ou baixado.",
                "registry",
            )
        )
    elif registry.situation == 3:
        signals.append(
            _signal(
                "REGISTRY_SUSPENDED",
                Outcome.FAIL,
                "cadastro",
                25,
                "O cadastro consultado de quem está cobrando consta como suspenso.",
                "registry",
            )
        )
    elif registry.situation == 2:
        signals.append(
            _signal(
                "REGISTRY_ACTIVE",
                Outcome.PASS,
                "cadastro",
                0,
                "O cadastro consultado consta como ativo.",
                "registry",
            )
        )
    else:
        signals.append(
            _unknown(
                "REGISTRY_SITUATION_UNKNOWN",
                "Não foi possível conferir a situação do cadastro.",
                "registry",
            )
        )
    if (
        not _readable(doc, "beneficiary_name")
        or not registry.legal_name
        or not normalize_name(registry.legal_name)
    ):
        signals.append(
            _unknown(
                "BENEFICIARY_UNREADABLE", "Não foi possível conferir o nome de quem está cobrando."
            )
        )
        return signals
    institution = next(
        (item for item in evidence.institutions if item.cnpj == normalize_cnpj(doc.identifier)),
        None,
    )
    candidates = (registry.legal_name, registry.trade_name or "")
    if institution is not None:
        candidates += institution.aliases
    if names_match(doc.beneficiary_name, candidates):
        signals.append(
            _signal(
                "BENEFICIARY_MATCH",
                Outcome.PASS,
                "cadastro",
                0,
                "O nome informado é compatível com o cadastro consultado.",
                "document+registry",
            )
        )
    elif institution is not None:
        signals.append(
            _signal(
                "KNOWN_INTERMEDIARY",
                Outcome.FAIL,
                "cadastro",
                10,
                "A cobrança pode envolver um intermediário conhecido; confirme quem está cobrando.",
                "document+registry",
            )
        )
    else:
        signals.append(
            _signal(
                "BENEFICIARY_MISMATCH",
                Outcome.FAIL,
                "cadastro",
                25,
                "O nome no boleto difere do cadastro consultado; a cobrança pode envolver um intermediário.",
                "document+registry",
            )
        )
    return signals


def _payment(evidence: AnalysisEvidence) -> list[EvaluatedSignal]:
    boleto, doc = evidence.boleto, evidence.document
    if boleto is None:
        return [
            _unknown(
                "PAYMENT_CODE_MISSING", "Não foi possível obter um código de pagamento legível."
            )
        ]
    if boleto.format != Format.COLLECTION:
        return [
            _unknown(
                "PAYMENT_FORMAT_UNSUPPORTED",
                "Este tipo de conta ainda não é verificado pelo serviço.",
                "parser",
            )
        ]
    if (
        boleto.source == Source.DOCUMENT
        and doc is not None
        and "payment_code" in doc.uncertain_fields
    ):
        return [
            _unknown(
                "DOCUMENT_CODE_UNREADABLE",
                "A leitura do código está incerta; não foi possível conferir valor, vencimento e banco.",
            )
        ]
    signals = []
    if not boleto.valid_dvs:
        if boleto.source == Source.PARTNER:
            signals.append(
                _signal(
                    "INVALID_DV",
                    Outcome.FAIL,
                    "integridade",
                    60,
                    "O código de pagamento informado contém um erro; confira os números.",
                    "parser",
                )
            )
        else:
            signals.append(
                _unknown(
                    "EXTRACTED_DV_INVALID", "Não foi possível confirmar os números lidos no boleto."
                )
            )
        signals.append(
            _unknown(
                "PAYMENT_FIELDS_UNVERIFIED",
                "Não foi possível conferir valor, vencimento e banco pelo código de pagamento.",
                "parser",
            )
        )
        return signals
    signals.append(
        _signal(
            "VALID_DV",
            Outcome.PASS,
            "integridade",
            0,
            "Os dígitos verificadores do código conferem.",
            "parser",
        )
    )
    if boleto.currency != "9":
        signals.append(
            _unknown(
                "CURRENCY_UNSUPPORTED",
                "A moeda deste código de pagamento não é suportada.",
                "parser",
            )
        )
        return signals
    if doc is None:
        signals.append(
            _unknown(
                "DOCUMENT_MISSING",
                "Envie o documento para conferir quem está cobrando, o valor e o vencimento.",
            )
        )
        return signals
    if doc.uncertain_fields:
        signals.append(
            _unknown(
                "DOCUMENT_UNCERTAIN",
                "Há informações do documento que não puderam ser lidas com segurança.",
            )
        )
    if boleto.source == Source.PARTNER:
        signals.extend(_compare_codes(evidence))
    if (
        boleto.amount_cents is None
        or not _readable(doc, "nominal_amount_cents")
        or type(doc.nominal_amount_cents) is not int
        or doc.nominal_amount_cents < 0
    ):
        signals.append(
            _unknown(
                "AMOUNT_UNVERIFIED",
                "Não foi possível comparar o valor nominal do boleto com o código de pagamento.",
            )
        )
    elif boleto.amount_cents != doc.nominal_amount_cents:
        signals.append(
            _signal(
                "AMOUNT_MISMATCH",
                Outcome.FAIL,
                "valor",
                60,
                "O valor informado no documento é diferente do valor do código de pagamento.",
                "document+parser",
            )
        )
    else:
        signals.append(
            _signal(
                "AMOUNT_MATCH",
                Outcome.PASS,
                "valor",
                0,
                "Os valores nominais conferem.",
                "document+parser",
            )
        )
    if (
        not boleto.due_date_candidates
        or not _readable(doc, "due_date")
        or type(doc.due_date) is not date
    ):
        signals.append(
            _unknown(
                "DUE_DATE_UNVERIFIED", "Não foi possível confirmar a data de vencimento do boleto."
            )
        )
    elif doc.due_date not in boleto.due_date_candidates:
        signals.append(
            _signal(
                "DUE_DATE_MISMATCH",
                Outcome.FAIL,
                "vencimento",
                10,
                "A data de vencimento informada não corresponde ao código de pagamento.",
                "document+parser",
            )
        )
    else:
        signals.append(
            _signal(
                "DUE_DATE_MATCH",
                Outcome.PASS,
                "vencimento",
                0,
                "A data exibida é compatível com o código de pagamento.",
                "document+parser",
            )
        )
    bank = next((item for item in evidence.banks if item.code == boleto.bank_code), None)
    if bank is None or not _readable(doc, "bank_name"):
        signals.append(
            _unknown("BANK_UNVERIFIED", "Não foi possível conferir o banco informado no boleto.")
        )
    else:
        bank_names = {normalize_name(name) for name in (bank.name, *bank.aliases)}
        displayed = [doc.bank_name]
        if _readable(doc, "logo_name"):
            displayed.append(doc.logo_name)
        if all(normalize_name(name) in bank_names for name in displayed):
            signals.append(
                _signal(
                    "BANK_MATCH",
                    Outcome.PASS,
                    "banco",
                    0,
                    "O banco exibido é compatível com o código.",
                    "document+parser",
                )
            )
        else:
            signals.append(
                _signal(
                    "BANK_MISMATCH",
                    Outcome.FAIL,
                    "banco",
                    10,
                    "O banco ou logotipo exibido difere do banco do código de pagamento.",
                    "document+parser",
                )
            )
    return signals


def _compare_codes(evidence: AnalysisEvidence) -> list[EvaluatedSignal]:
    doc = evidence.document
    if not _readable(doc, "payment_code"):
        return [
            _unknown(
                "DOCUMENT_CODE_UNREADABLE",
                "Não foi possível comparar o código informado com os números no documento.",
            )
        ]
    try:
        extracted = parse_boleto(doc.payment_code, source=Source.DOCUMENT)
    except InvalidBoleto:
        return [
            _unknown(
                "DOCUMENT_CODE_INVALID", "Não foi possível confirmar os números lidos no documento."
            )
        ]
    if extracted.format != Format.COLLECTION or not extracted.valid_dvs:
        return [
            _unknown(
                "DOCUMENT_CODE_INVALID", "Não foi possível confirmar os números lidos no documento."
            )
        ]
    if extracted.barcode != evidence.boleto.barcode:
        return [
            _unknown(
                "PAYMENT_CODE_MISMATCH", "O código informado difere dos números lidos no documento."
            )
        ]
    return [
        _signal(
            "PAYMENT_CODE_MATCH",
            Outcome.PASS,
            "integridade",
            0,
            "O código informado corresponde aos números lidos no documento.",
            "document+parser",
        )
    ]


def evaluate(evidence: AnalysisEvidence) -> Decision:
    """Produz sinais sanitizados; não devolve nem retém campos do documento."""
    signals = _identity(evidence) + _payment(evidence)
    if evidence.document_failure is not None:
        messages = {
            DocumentFailure.TIMEOUT: "A leitura do documento não terminou a tempo.",
            DocumentFailure.RATE_LIMITED: "O serviço de leitura está temporariamente sobrecarregado.",
            DocumentFailure.UNAVAILABLE: "O serviço de leitura do documento está indisponível.",
            DocumentFailure.INVALID_RESPONSE: "Não foi possível conferir os dados retornados pela leitura do documento.",
            DocumentFailure.UNREADABLE: "O arquivo está ilegível, protegido ou fora dos limites de leitura.",
            DocumentFailure.UNKNOWN_DEMO_DOCUMENT: "No modo de demonstração, use um dos documentos sintéticos fornecidos.",
        }
        signals.append(
            _unknown(
                "DOCUMENT_" + evidence.document_failure.name, messages[evidence.document_failure]
            )
        )
    # Maior sinal de cada grupo; desempate pela ordem estável das regras.
    winners: dict[str, int] = {}
    for index, signal in enumerate(signals):
        current = winners.get(signal.group)
        if current is None or signal.weight > signals[current].weight:
            winners[signal.group] = index
    applied = tuple(
        replace(signal, applied_weight=signal.weight if winners[signal.group] == index else 0)
        for index, signal in enumerate(signals)
    )
    raw_score = sum(signal.applied_weight for signal in applied)
    score = min(100, raw_score)
    if score == 0:
        status, title = Status.SAFE, "Nenhuma inconsistência encontrada"
        explanation = "Nenhuma inconsistência foi encontrada nas verificações realizadas. Isso não confirma o recebedor do pagamento."
    else:
        if score >= 60:
            status, title = Status.DANGER, "Inconsistência importante no boleto"
        else:
            status, title = Status.WARNING, "Confira as informações do boleto"
        # Não omitir causas de degradação quando há sinal forte simultâneo.
        ordered = sorted((s for s in applied if s.weight), key=lambda s: -s.weight)
        explanation = " ".join(dict.fromkeys(s.explanation for s in ordered))
    return Decision(status, score, title, explanation, applied, raw_score)
