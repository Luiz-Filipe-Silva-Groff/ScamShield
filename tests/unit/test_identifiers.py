import pytest

from scamshield.domain.identifiers import normalize_cnpj, valid_cnpj


@pytest.mark.parametrize(
    "value",
    [
        "12.ABC.345/01DE-35",
        "12abc34501de35",
        "00000000000191",
        "60701190000104",
        "01027058000191",
        "08561701000101",
    ],
)
def test_official_and_public_identifiers(value):
    assert valid_cnpj(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        "0" * 14,
        "1" * 14,
        "12ABC34501DE34",
        "12ABC34501DE3Z",
        "12ÁBC34501DE35",
        "12ABC34501DE350",
        "12ABC34501DE3",
        "12ABC34501DE_35",
        "١" * 14,
    ],
)
def test_invalid_cnpj(value):
    assert not valid_cnpj(value)


def test_normalization_preserves_letters_and_leading_zeros():
    assert normalize_cnpj(" 00.000.000/0001-91 ") == "00000000000191"
    assert normalize_cnpj("12.abc.345/01de-35") == "12ABC34501DE35"


def test_versioned_exceptions_have_valid_exact_cnpj(institutions):
    assert all(valid_cnpj(item.cnpj) for item in institutions)
    assert len({item.cnpj for item in institutions}) == len(institutions)
