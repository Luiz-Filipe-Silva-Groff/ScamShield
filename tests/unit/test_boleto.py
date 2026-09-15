from datetime import date

import pytest
from conftest import PUBLISHED_BARCODE, PUBLISHED_LINE, synthetic_barcode

from scamshield.domain.boleto import (
    InvalidBoleto,
    due_dates,
    modulo10,
    modulo11_barcode,
    normalize,
    parse_boleto,
    to_digitable_line,
)
from scamshield.domain.models import Format, Source


def test_published_bb_vector(banks):
    boleto = parse_boleto(PUBLISHED_LINE, banks=banks)
    assert boleto.barcode == PUBLISHED_BARCODE
    assert boleto.bank_code == "001"
    assert boleto.bank_name == "Banco do Brasil S.A."
    assert boleto.currency == "9"
    assert boleto.amount_cents == 100
    assert boleto.due_factor == 3737
    assert boleto.due_date_candidates[0] == date(2007, 12, 31)
    assert boleto.field_dvs == (True, True, True)
    assert boleto.general_dv is True
    assert boleto.valid_dvs
    assert to_digitable_line(PUBLISHED_BARCODE) == normalize(PUBLISHED_LINE)


def test_barcode_without_line_has_only_general_dv():
    boleto = parse_boleto(PUBLISHED_BARCODE, source="document")
    assert boleto.source == Source.DOCUMENT
    assert boleto.field_dvs == ()
    assert boleto.valid_dvs
    assert boleto.bank_name is None


@pytest.mark.parametrize("index", [9, 20, 31])
def test_independent_line_dvs(index):
    digits = normalize(PUBLISHED_LINE)
    bad = digits[:index] + str((int(digits[index]) + 1) % 10) + digits[index + 1 :]
    boleto = parse_boleto(bad)
    assert not boleto.valid_dvs
    assert sum(boleto.field_dvs) == 2
    assert boleto.general_dv is True


def test_invalid_general_dv_is_not_repaired():
    bad = PUBLISHED_BARCODE[:4] + "4" + PUBLISHED_BARCODE[5:]
    assert not parse_boleto(bad).valid_dvs
    assert not parse_boleto(to_digitable_line(bad)).general_dv


@pytest.mark.parametrize("raw", ["8" + "0" * 43, "8" + "0" * 47, "1" * 48])
def test_unsupported_format(raw):
    parsed = parse_boleto(raw)
    assert parsed.format == Format.UNSUPPORTED
    assert parsed.amount_cents is None
    assert not parsed.valid_dvs


@pytest.mark.parametrize(
    "raw",
    [
        None,
        123,
        "",
        "abc",
        "1" * 43,
        "1" * 45,
        "1" * 46,
        "1" * 49,
        "١" * 44,
        "１" * 44,
        "0" * 43 + "/",
        "0" * 43 + "\x00",
        ". -\t",
    ],
)
def test_rejects_bad_inputs_without_echo(raw):
    with pytest.raises(InvalidBoleto) as caught:
        parse_boleto(raw)
    if raw:
        assert str(raw) not in str(caught.value)


def test_accepts_only_documented_separators():
    assert normalize("\n\t " + PUBLISHED_LINE + " -\r\n") == normalize(PUBLISHED_LINE)


@pytest.mark.parametrize("raw", ["", "a", "١", None])
def test_modulo_rejects_non_digits(raw):
    with pytest.raises(InvalidBoleto):
        modulo10(raw)


@pytest.mark.parametrize(
    ("digits", "expected"),
    [("001905009", 5), ("4014481606", 9), ("0680935031", 4), ("0", 0), ("9", 1)],
)
def test_modulo10_vectors(digits, expected):
    assert modulo10(digits) == expected


@pytest.mark.parametrize(("last", "expected"), [("0", 1), ("1", 9), ("5", 1), ("6", 1), ("2", 7)])
def test_modulo11_remainders(last, expected):
    assert modulo11_barcode("0" * 42 + last) == expected


def test_modulo11_requires_43_digits():
    with pytest.raises(InvalidBoleto):
        modulo11_barcode("123")


@pytest.mark.parametrize("factor", [-1, 10000, True, "1000", 1.5])
def test_bad_factors(factor):
    with pytest.raises(InvalidBoleto):
        due_dates(factor)


def test_both_due_date_cycles():
    assert due_dates(0) == ()
    assert due_dates(1) == (date(1997, 10, 8),)
    assert due_dates(999) == (date(2000, 7, 2),)
    assert due_dates(1000) == (date(2000, 7, 3), date(2025, 2, 22))
    assert due_dates(1001)[1] == date(2025, 2, 23)
    assert due_dates(9999) == (date(2025, 2, 21), date(2049, 10, 13))


@pytest.mark.parametrize("amount", [0, 1, 9999999999])
def test_amount_and_factor_boundaries(amount):
    parsed = parse_boleto(synthetic_barcode(amount=amount, factor=0))
    assert parsed.amount_cents == (amount or None)
    assert parsed.due_date_candidates == ()


@pytest.mark.parametrize("raw", [PUBLISHED_LINE, "8" + "0" * 43, "1" * 48])
def test_conversion_does_not_accept_other_formats(raw):
    with pytest.raises(InvalidBoleto):
        to_digitable_line(raw)


@pytest.mark.parametrize("factor", [0, 999, 1000, 1001, 9999])
@pytest.mark.parametrize("bank", ["001", "104", "237", "341", "748"])
def test_synthetic_round_trip(bank, factor):
    barcode = synthetic_barcode(bank=bank, factor=factor)
    assert parse_boleto(to_digitable_line(barcode)).barcode == barcode
    assert parse_boleto(barcode).valid_dvs
