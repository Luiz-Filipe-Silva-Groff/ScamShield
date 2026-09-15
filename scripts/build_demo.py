"""Gera somente artefatos sintéticos versionados para a apresentação."""

import base64
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src/scamshield/data/demo"
REQUESTS = ROOT / "demo/requests"


def cnpj(base):
    for _ in range(2):
        remainder = sum((ord(c) - 48) * (2 + i % 8) for i, c in enumerate(base[::-1])) % 11
        base += str(0 if remainder < 2 else 11 - remainder)
    return base


def barcode():
    factor = 1000 + (date(2026, 9, 20) - date(2025, 2, 22)).days
    digits = "0019" + f"{factor:04d}" + "0000015000" + "1234567890123456789012345"
    remainder = sum(int(c) * (2 + i % 8) for i, c in enumerate(digits[::-1])) % 11
    dv = 1 if remainder in (0, 1, 10) else 11 - remainder
    return digits[:4] + str(dv) + digits[4:]


def pdf(lines):
    # PDF textual mínimo com offsets corretos; geração de fixture, nunca upload real.
    escaped = [s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for s in lines]
    stream = (
        "BT /F1 13 Tf 45 760 Td 24 TL " + " ".join(f"({s}) Tj T*" for s in escaped) + " ET"
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{n} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.extend(f"{offset:010} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(out)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    REQUESTS.mkdir(parents=True, exist_ok=True)
    code = barcode()
    good_cnpj = cnpj("12ABC34501DE")
    extraction = dict(
        beneficiary_name="Horizonte Serviços",
        identifier=good_cnpj,
        identifier_type="CNPJ",
        nominal_amount_cents=15000,
        due_date="2026-09-20",
        bank_name="Banco do Brasil",
        logo_name="BB",
        payment_code=code,
        uncertain_fields=[],
    )
    registry = dict(
        state="found",
        cnpj=good_cnpj,
        legal_name="Horizonte Serviços Ltda",
        trade_name="Horizonte",
        situation=2,
    )
    definitions = [
        ("safe", "Informações compatíveis", "SAFE", 0, {}, {}, None),
        (
            "name_warning",
            "Nome diferente no cadastro",
            "WARNING",
            25,
            {"beneficiary_name": "Outra Empresa"},
            {},
            None,
        ),
        (
            "intermediary",
            "Cobrança com intermediário",
            "WARNING",
            10,
            {"identifier": "00000000000191", "beneficiary_name": "Condomínio Horizonte"},
            {
                "cnpj": "00000000000191",
                "legal_name": "Banco do Brasil S.A.",
                "trade_name": "Banco do Brasil",
            },
            None,
        ),
        (
            "amount_danger",
            "Valor adulterado",
            "DANGER",
            60,
            {"nominal_amount_cents": 95000},
            {},
            None,
        ),
        (
            "registry_danger",
            "Cadastro baixado",
            "DANGER",
            60,
            {"identifier": cnpj("12ABC34501DF")},
            {"cnpj": cnpj("12ABC34501DF"), "situation": 8},
            None,
        ),
        (
            "invalid_dv",
            "Erro nos dígitos verificadores",
            "DANGER",
            70,
            {"payment_code": code[:4] + str((int(code[4]) + 1) % 10) + code[5:]},
            {},
            None,
        ),
        ("unreadable", "Leitura indisponível", "WARNING", 10, {}, {}, "unreadable"),
        (
            "registry_timeout",
            "Consulta não terminou a tempo",
            "WARNING",
            10,
            {"identifier": cnpj("12ABC34501DG")},
            {"cnpj": cnpj("12ABC34501DG"), "state": "unavailable", "failure": "timeout"},
            None,
        ),
        (
            "trade_name",
            "Nome fantasia compatível",
            "SAFE",
            0,
            {"beneficiary_name": "Horizonte"},
            {},
            None,
        ),
    ]
    manifest = []
    http = ["@baseUrl = http://localhost:8000", "@apiKey = scamshield-demo-local", ""]
    for ident, label, status, score, changes, reg_changes, failure in definitions:
        fields = extraction | changes
        reg = registry | reg_changes
        file = f"{ident}.pdf"
        lines = [
            "SCAMSHIELD - DOCUMENTO SINTETICO DE DEMONSTRACAO",
            "SEM VALOR DE PAGAMENTO - NAO PAGAR",
            "",
            label,
            "Banco: Banco do Brasil (001)",
            f"Beneficiario: {fields['beneficiary_name']}",
            f"CNPJ: {fields['identifier']}",
            f"Valor nominal: R$ {fields['nominal_amount_cents'] / 100:.2f}",
            "Vencimento: 20/09/2026",
            "Codigo numerico de demonstracao:",
            fields["payment_code"],
            "",
            "Cadastro e leitura simulados no modo demo.",
        ]
        if failure:
            lines = lines[:4] + [
                "Conteudo intencionalmente omitido para simular leitura incompleta."
            ]
        content = pdf(lines)
        (DATA / file).write_bytes(content)
        line = fields["payment_code"]
        case = dict(
            id=ident,
            label=label,
            file=file,
            sha256=hashlib.sha256(content).hexdigest(),
            expected_status=status,
            expected_score=score,
            line=line,
            extraction=fields,
            registry=reg,
            reader_failure=failure,
        )
        manifest.append(case)
        request = {
            "linha_digitavel": line,
            "documento": {
                "mime_type": "application/pdf",
                "base64": base64.b64encode(content).decode(),
            },
        }
        (REQUESTS / f"{ident}.json").write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        http.extend(
            [
                f"### {label}: {status} / {score}",
                "POST {{baseUrl}}/v1/analise",
                "X-API-Key: {{apiKey}}",
                "Content-Type: application/json",
                "",
                f"< ./requests/{ident}.json",
                "",
            ]
        )
    (DATA / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "demo/requests.http").write_text("\n".join(http), encoding="utf-8")
    print(f"{len(manifest)} cenários sintéticos gerados.")


if __name__ == "__main__":
    main()
