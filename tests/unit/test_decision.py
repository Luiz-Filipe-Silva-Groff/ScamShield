import json
import socket
from dataclasses import asdict, replace
from datetime import date
from itertools import product

import pytest
from conftest import PUBLISHED_BARCODE, synthetic_barcode

from scamshield.domain.boleto import parse_boleto
from scamshield.domain.decision import evaluate, names_match, normalize_name
from scamshield.domain.models import (
    AnalysisEvidence,
    DocumentFailure,
    Institution,
    Outcome,
    RegistryFailure,
    RegistryResult,
    RegistryState,
    Source,
    Status,
)


def change_doc(evidence, **fields):
    return replace(evidence, document=replace(evidence.document, **fields))


def codes(result):
    return {s.code for s in result.signals}


def test_full_evidence_safe_and_deterministic(evidence):
    result = evaluate(evidence)
    assert result == evaluate(evidence)
    assert (result.status, result.score) == (Status.SAFE, 0)
    assert all(s.outcome == Outcome.PASS for s in result.signals)
    assert "não confirma o recebedor" in result.explanation


def test_no_evidence_never_safe():
    result = evaluate(AnalysisEvidence())
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert codes(result) == {"IDENTIFIER_UNREADABLE", "PAYMENT_CODE_MISSING"}


@pytest.mark.parametrize("failure", list(DocumentFailure))
def test_reader_failures_degrade_explicitly(evidence, failure):
    result = evaluate(replace(evidence, document_failure=failure))
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "DOCUMENT_" + failure.name in codes(result)


@pytest.mark.parametrize(
    "field",
    [
        "identifier",
        "beneficiary_name",
        "nominal_amount_cents",
        "due_date",
        "bank_name",
        "payment_code",
    ],
)
@pytest.mark.parametrize("mode", ["absent", "uncertain"])
def test_missing_or_ambiguous_required_field_is_warning(evidence, field, mode):
    changed = (
        change_doc(evidence, **{field: None})
        if mode == "absent"
        else change_doc(evidence, uncertain_fields=frozenset({field}))
    )
    result = evaluate(changed)
    assert (result.status, result.score) == (Status.WARNING, 10)


def test_text_without_document_is_warning(evidence):
    result = evaluate(replace(evidence, document=None))
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "DOCUMENT_MISSING" in codes(result)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("identifier_type", "CPF", "IDENTIFIER_UNSUPPORTED"),
        ("identifier_type", "UNKNOWN", "IDENTIFIER_UNSUPPORTED"),
        ("identifier", "12ABC34501DE34", "CNPJ_INVALID"),
        ("identifier", "", "IDENTIFIER_UNREADABLE"),
        ("payment_code", "ABC", "DOCUMENT_CODE_INVALID"),
        ("payment_code", "8" + "0" * 47, "DOCUMENT_CODE_INVALID"),
        ("payment_code", "8" + "0" * 43, "DOCUMENT_CODE_INVALID"),
        (
            "payment_code",
            PUBLISHED_BARCODE[:4] + "4" + PUBLISHED_BARCODE[5:],
            "DOCUMENT_CODE_INVALID",
        ),
        ("payment_code", synthetic_barcode(), "PAYMENT_CODE_MISMATCH"),
        ("nominal_amount_cents", -1, "AMOUNT_UNVERIFIED"),
        ("nominal_amount_cents", True, "AMOUNT_UNVERIFIED"),
        ("nominal_amount_cents", 100.0, "AMOUNT_UNVERIFIED"),
        ("due_date", "2007-12-31", "DUE_DATE_UNVERIFIED"),
    ],
)
def test_uncertain_inputs(evidence, field, value, expected):
    result = evaluate(change_doc(evidence, **{field: value}))
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert expected in codes(result)


@pytest.mark.parametrize(
    "state", [RegistryState.NOT_FOUND, RegistryState.INVALID, RegistryState.UNAVAILABLE]
)
def test_registry_states_are_not_fraud(evidence, state):
    result = evaluate(replace(evidence, registry=RegistryResult(state)))
    assert (result.status, result.score) == (Status.WARNING, 10)


@pytest.mark.parametrize("failure", list(RegistryFailure))
def test_registry_failure_reasons_are_explicit(evidence, failure):
    result = evaluate(
        replace(evidence, registry=RegistryResult(RegistryState.UNAVAILABLE, failure=failure))
    )
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "REGISTRY_" + failure.name in codes(result)


def test_registry_not_supplied(evidence):
    assert "REGISTRY_MISSING" in codes(evaluate(replace(evidence, registry=None)))


@pytest.mark.parametrize("cnpj", [None, "00000000000191", "malformed"])
def test_registry_must_match_requested_identifier(evidence, cnpj):
    result = evaluate(
        replace(evidence, registry=replace(evidence.registry, cnpj=cnpj, situation=8))
    )
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "REGISTRY_IDENTIFIER_MISMATCH" in codes(result)


@pytest.mark.parametrize(
    ("situation", "score", "status"),
    [
        (1, 60, Status.DANGER),
        (4, 60, Status.DANGER),
        (8, 60, Status.DANGER),
        (3, 25, Status.WARNING),
        (None, 10, Status.WARNING),
        (99, 10, Status.WARNING),
    ],
)
def test_registry_situations(evidence, situation, score, status):
    result = evaluate(replace(evidence, registry=replace(evidence.registry, situation=situation)))
    assert (result.status, result.score) == (status, score)


@pytest.mark.parametrize("name", [None, "", "S.A."])
def test_registry_missing_legal_name(evidence, name):
    result = evaluate(replace(evidence, registry=replace(evidence.registry, legal_name=name)))
    assert (result.status, result.score) == (Status.WARNING, 10)


def test_trade_name_can_establish_compatibility(evidence):
    evidence = change_doc(evidence, beneficiary_name="Marca Comercial")
    evidence = replace(evidence, registry=replace(evidence.registry, trade_name="Marca Comercial"))
    assert evaluate(evidence).status == Status.SAFE


def test_legal_name_without_trade_name(evidence):
    assert (
        evaluate(replace(evidence, registry=replace(evidence.registry, trade_name=None))).status
        == Status.SAFE
    )


def test_name_mismatch_alone_is_warning(evidence):
    result = evaluate(change_doc(evidence, beneficiary_name="Outra Organização"))
    assert (result.status, result.score) == (Status.WARNING, 25)
    assert "intermediário" in result.explanation


def test_known_intermediary_only_reduces_name_weight(evidence, institutions):
    intermediary = institutions[0]
    evidence = change_doc(evidence, identifier=intermediary.cnpj, beneficiary_name="Seller Exemplo")
    evidence = replace(
        evidence,
        registry=replace(evidence.registry, cnpj=intermediary.cnpj, legal_name=intermediary.name),
        institutions=institutions,
    )
    assert evaluate(evidence).score == 10
    assert evaluate(change_doc(evidence, nominal_amount_cents=200)).score == 70
    irregular = replace(evidence, registry=replace(evidence.registry, situation=8))
    result = evaluate(irregular)
    assert (result.status, result.score) == (Status.DANGER, 60)
    assert next(s for s in result.signals if s.code == "KNOWN_INTERMEDIARY").applied_weight == 0


def test_institution_alias_is_exactly_scoped(evidence):
    item = Institution("12ABC34501DE35", "Empresa Exemplo", ("Marca Documentada",))
    evidence = change_doc(evidence, beneficiary_name="Marca Documentada")
    assert evaluate(replace(evidence, institutions=(item,))).status == Status.SAFE
    other = replace(item, cnpj="00000000000191")
    assert evaluate(replace(evidence, institutions=(other,))).score == 25


def test_higher_signal_wins_even_when_added_later(evidence):
    # Cadastro ativo tem peso zero e precede a divergência nominal de peso 25.
    result = evaluate(change_doc(evidence, beneficiary_name="Outra Empresa"))
    applied = {s.code: s.applied_weight for s in result.signals}
    assert applied["REGISTRY_ACTIVE"] == 0
    assert applied["BENEFICIARY_MISMATCH"] == 25


def test_amount_signal_and_combinations(evidence):
    evidence = change_doc(evidence, nominal_amount_cents=200)
    assert evaluate(evidence).score == 60
    evidence = change_doc(evidence, beneficiary_name="Outra Empresa")
    assert evaluate(evidence).score == 85
    evidence = change_doc(evidence, bank_name="Itaú")
    assert evaluate(evidence).score == 95
    evidence = change_doc(evidence, due_date=date(2026, 1, 1))
    result = evaluate(evidence)
    assert result.score == 100
    assert result.raw_score == 105


@pytest.mark.parametrize("source", list(Source))
def test_bad_dv_preserves_provenance_and_suppresses_cross_checks(evidence, source):
    invalid = PUBLISHED_BARCODE[:4] + "4" + PUBLISHED_BARCODE[5:]
    evidence = replace(evidence, boleto=parse_boleto(invalid, source=source))
    evidence = change_doc(
        evidence, nominal_amount_cents=900, bank_name="Outro", due_date=date(2026, 1, 1)
    )
    result = evaluate(evidence)
    assert result.status == (Status.DANGER if source == Source.PARTNER else Status.WARNING)
    assert not {"AMOUNT_MISMATCH", "DUE_DATE_MISMATCH", "BANK_MISMATCH"} & codes(result)


def test_document_only_can_be_evaluated_after_extraction(evidence):
    evidence = replace(evidence, boleto=parse_boleto(PUBLISHED_BARCODE, source=Source.DOCUMENT))
    assert evaluate(evidence).status == Status.SAFE


def test_uncertain_extracted_code_cannot_support_strong_value_signal(evidence):
    evidence = replace(evidence, boleto=parse_boleto(PUBLISHED_BARCODE, source=Source.DOCUMENT))
    evidence = change_doc(
        evidence, uncertain_fields=frozenset({"payment_code"}), nominal_amount_cents=900
    )
    result = evaluate(evidence)
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "AMOUNT_MISMATCH" not in codes(result)


def test_extracted_code_without_document_remains_incomplete(evidence):
    evidence = replace(
        evidence, boleto=parse_boleto(PUBLISHED_BARCODE, source=Source.DOCUMENT), document=None
    )
    assert evaluate(evidence).status == Status.WARNING


def test_out_of_scope_payment_and_currency(evidence):
    result = evaluate(replace(evidence, boleto=parse_boleto("8" + "0" * 47)))
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "PAYMENT_FORMAT_UNSUPPORTED" in codes(result)
    result = evaluate(replace(evidence, boleto=parse_boleto(synthetic_barcode(currency="0"))))
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert "CURRENCY_UNSUPPORTED" in codes(result)


def test_open_amount_and_absent_due_date(evidence):
    barcode = synthetic_barcode(amount=0, factor=0)
    evidence = replace(evidence, boleto=parse_boleto(barcode, source=Source.DOCUMENT))
    result = evaluate(evidence)
    assert (result.status, result.score) == (Status.WARNING, 10)
    assert {"AMOUNT_UNVERIFIED", "DUE_DATE_UNVERIFIED"} <= codes(result)


def test_2025_reset_selects_compatible_candidate(evidence):
    evidence = replace(
        evidence, boleto=parse_boleto(synthetic_barcode(factor=1000), source=Source.DOCUMENT)
    )
    assert evaluate(change_doc(evidence, due_date=date(2025, 2, 22))).status == Status.SAFE
    assert evaluate(change_doc(evidence, due_date=date(2000, 7, 3))).status == Status.SAFE
    assert evaluate(change_doc(evidence, due_date=None)).status == Status.WARNING


def test_unknown_bank_and_optional_logo(evidence):
    assert evaluate(replace(evidence, banks=())).score == 10
    assert evaluate(change_doc(evidence, logo_name=None)).status == Status.SAFE
    assert evaluate(change_doc(evidence, logo_name="Outra Marca")).score == 10


@pytest.mark.parametrize("field", ["bank_name", "logo_name"])
def test_bank_comparison_does_not_compare_to_beneficiary(evidence, field):
    assert evaluate(change_doc(evidence, **{field: "Empresa Exemplo"})).score == 10


def test_all_soft_combinations_stay_below_danger(evidence):
    for name, bank, due, uncertainty in product([False, True], repeat=4):
        current = change_doc(
            evidence,
            beneficiary_name="Outra Empresa" if name else evidence.document.beneficiary_name,
            bank_name="Outro Banco" if bank else evidence.document.bank_name,
            due_date=date(2026, 1, 1) if due else evidence.document.due_date,
            uncertain_fields=frozenset({"logo_name"}) if uncertainty else frozenset(),
        )
        result = evaluate(current)
        assert result.score == 25 * name + 10 * bank + 10 * due + 10 * uncertainty
        assert result.status != Status.DANGER


def test_strong_signal_survives_external_failure(evidence):
    evidence = change_doc(evidence, nominal_amount_cents=200)
    evidence = replace(
        evidence,
        registry=RegistryResult(RegistryState.UNAVAILABLE, failure=RegistryFailure.TIMEOUT),
    )
    result = evaluate(evidence)
    assert (result.status, result.score) == (Status.DANGER, 70)
    assert "não terminou a tempo" in result.explanation
    assert "valor" in result.explanation


@pytest.mark.parametrize(
    ("name", "other", "match"),
    [
        ("Claro", "CLARO S.A.", True),
        ("CLARO S/A", "claro", True),
        ("CLARO", "CLARO NXT TELECOMUNICACOES LTDA", False),
        ("Empresa Exemplo", "Empresa Exempol Ltda", True),
        ("Acme", "Acne", False),
        ("Empresa Azul", "Empresa Vermelha", False),
        ("", "Empresa", False),
        ("S.A.", "S.A.", False),
        ("Ação Comércio Ltda", "ACAO COMERCIO", True),
        ("Qualquer", "", False),
    ],
)
def test_fuzzy_is_conservative(name, other, match):
    assert names_match(name, (other,)) is match


def test_normalization_only_removes_legal_suffixes():
    assert normalize_name("Exemplo LTDA") == "exemplo"
    assert normalize_name("Exemplo S.A.") == "exemplo"
    assert normalize_name("LTDA Comércio") == "ltda comercio"
    assert normalize_name("") == ""


def test_no_network_or_sensitive_output(evidence, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("O núcleo não pode acessar a rede")

    monkeypatch.setattr(socket, "socket", forbidden)
    result = evaluate(evidence)
    serialized = json.dumps(asdict(result), ensure_ascii=False)
    for private in (
        evidence.document.identifier,
        evidence.document.beneficiary_name,
        evidence.document.payment_code,
        evidence.registry.legal_name,
    ):
        assert private not in serialized
        assert private not in repr(evidence)
        assert private not in repr(evidence.document)
        assert private not in repr(evidence.registry)
    assert PUBLISHED_BARCODE not in repr(evidence.boleto)
