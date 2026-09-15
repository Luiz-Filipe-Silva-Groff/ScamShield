import json
from datetime import date
from pathlib import Path

import pytest

from scamshield.domain.boleto import parse_boleto
from scamshield.domain.models import (
    AnalysisEvidence,
    Bank,
    ExtractedDocument,
    Institution,
    RegistryResult,
    RegistryState,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_LINE = "00190.50095 40144.816069 06809.350314 3 37370000000100"
PUBLISHED_BARCODE = "00193373700000001000500940144816060680935031"


@pytest.fixture
def banks():
    data = json.loads((ROOT / "src/scamshield/data/config/banks.json").read_text(encoding="utf-8"))
    return tuple(Bank(b["code"], b["name"], tuple(b["aliases"])) for b in data["banks"])


@pytest.fixture
def institutions():
    data = json.loads(
        (ROOT / "src/scamshield/data/config/institutions.json").read_text(encoding="utf-8")
    )
    return tuple(
        Institution(i["cnpj"], i["name"], tuple(i["aliases"])) for i in data["institutions"]
    )


@pytest.fixture
def evidence(banks):
    # Identificador do exemplo oficial Serpro; não representa consulta real.
    return AnalysisEvidence(
        boleto=parse_boleto(PUBLISHED_LINE, banks=banks),
        document=ExtractedDocument(
            beneficiary_name="Empresa Exemplo",
            identifier="12.ABC.345/01DE-35",
            nominal_amount_cents=100,
            due_date=date(2007, 12, 31),
            bank_name="Banco do Brasil",
            logo_name="BB",
            payment_code=PUBLISHED_LINE,
        ),
        registry=RegistryResult(
            RegistryState.FOUND, "12ABC34501DE35", "Empresa Exemplo Ltda", "Empresa Exemplo", 2
        ),
        banks=banks,
    )


def synthetic_barcode(*, bank="001", currency="9", factor=1000, amount=100):
    # Vetor sintético independente; algoritmo de produção não gera o seu próprio oráculo.
    digits = bank + currency + f"{factor:04}{amount:010}" + "1234567890123456789012345"
    weights = [2, 3, 4, 5, 6, 7, 8, 9] * 6
    remainder = sum(int(n) * w for n, w in zip(digits[::-1], weights)) % 11
    dv = str(1 if remainder in (0, 1, 10) else 11 - remainder)
    return digits[:4] + dv + digits[4:]
