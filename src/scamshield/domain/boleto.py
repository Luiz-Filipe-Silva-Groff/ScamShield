"""Cobrança FEBRABAN: 44/47 dígitos, sem interpretar o campo livre.

Referência: manual Sicredi, seção Boletos (links em docs/fontes.md).
Arrecadação é reconhecida, mas não validada por este parser.
"""

import re
from datetime import date, timedelta

from .models import Bank, Format, ParsedBoleto, Source


class InvalidBoleto(ValueError):
    """Erro de formato; mensagem nunca inclui a entrada recebida."""


def _digits(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise InvalidBoleto("São esperados dígitos ASCII.")


def normalize(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9. \t\r\n-]+", value):
        raise InvalidBoleto("Código de pagamento contém caracteres não permitidos.")
    digits = re.sub(r"[. \t\r\n-]", "", value)
    if len(digits) not in (44, 47, 48):
        raise InvalidBoleto("Código de pagamento deve ter 44, 47 ou 48 dígitos.")
    return digits


def modulo10(digits: str) -> int:
    _digits(digits)
    total = 0
    for index, char in enumerate(reversed(digits)):
        product = int(char) * (2 if index % 2 == 0 else 1)
        total += product // 10 + product % 10
    return (-total) % 10


def modulo11_barcode(digits_without_dv: str) -> int:
    _digits(digits_without_dv)
    if len(digits_without_dv) != 43:
        raise InvalidBoleto("O cálculo do DV geral exige 43 dígitos.")
    total = sum(int(char) * (2 + i % 8) for i, char in enumerate(reversed(digits_without_dv)))
    result = 11 - total % 11
    return 1 if result in (0, 10, 11) else result


def due_dates(factor: int) -> tuple[date, ...]:
    if type(factor) is not int or not 0 <= factor <= 9999:
        raise InvalidBoleto("Fator de vencimento fora do intervalo permitido.")
    if factor == 0:
        return ()
    old_cycle = date(1997, 10, 7) + timedelta(days=factor)
    if factor < 1000:
        return (old_cycle,)
    return (old_cycle, date(2025, 2, 22) + timedelta(days=factor - 1000))


def parse_boleto(
    value: str, *, source: Source = Source.PARTNER, banks: tuple[Bank, ...] = ()
) -> ParsedBoleto:
    source = Source(source)
    digits = normalize(value)
    if len(digits) == 48 or (len(digits) == 44 and digits.startswith("8")):
        return ParsedBoleto(format=Format.UNSUPPORTED, source=source)
    field_dvs = ()
    if len(digits) == 47:
        field_dvs = (
            modulo10(digits[:9]) == int(digits[9]),
            modulo10(digits[10:20]) == int(digits[20]),
            modulo10(digits[21:31]) == int(digits[31]),
        )
        barcode = (
            digits[:4] + digits[32] + digits[33:] + digits[4:9] + digits[10:20] + digits[21:31]
        )
    else:
        barcode = digits
    bank_code = barcode[:3]
    bank_name = next((bank.name for bank in banks if bank.code == bank_code), None)
    factor = int(barcode[5:9])
    return ParsedBoleto(
        format=Format.COLLECTION,
        source=source,
        barcode=barcode,
        bank_code=bank_code,
        bank_name=bank_name,
        currency=barcode[3],
        amount_cents=int(barcode[9:19]) or None,
        due_factor=factor,
        due_date_candidates=due_dates(factor),
        field_dvs=field_dvs,
        general_dv=modulo11_barcode(barcode[:4] + barcode[5:]) == int(barcode[4]),
    )


def to_digitable_line(barcode: str) -> str:
    """Converte sem corrigir o DV geral; não certifica validade do boleto."""
    digits = normalize(barcode)
    if len(digits) != 44 or digits.startswith("8"):
        raise InvalidBoleto("Conversão exige um código de barras de cobrança de 44 dígitos.")
    fields = (digits[:4] + digits[19:24], digits[24:34], digits[34:44])
    return "".join(part + str(modulo10(part)) for part in fields) + digits[4:19]
