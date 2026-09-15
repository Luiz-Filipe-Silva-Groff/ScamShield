"""DV numérico/alfanumérico do CNPJ conforme Receita/Serpro.

Validade matemática não comprova existência cadastral.
"""

import re


def normalize_cnpj(value: str) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Za-z./ -]+", value):
        return None
    normalized = re.sub(r"[./ -]", "", value).upper()
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", normalized):
        return None
    return normalized


def valid_cnpj(value: str) -> bool:
    normalized = normalize_cnpj(value)
    if normalized is None or len(set(normalized)) == 1:
        return False
    base = normalized[:12]
    for _ in range(2):
        total = sum((ord(char) - 48) * (2 + i % 8) for i, char in enumerate(reversed(base)))
        remainder = total % 11
        base += str(0 if remainder < 2 else 11 - remainder)
    return normalized == base
