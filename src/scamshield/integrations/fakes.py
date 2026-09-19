"""Demo reconhece SHA-256 de fixtures sintéticas; não simula leitura arbitrária."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

from ..domain.models import DocumentFailure, RegistryFailure, RegistryResult, RegistryState
from ..schemas import DocumentExtraction
from .document_reader import ReaderError


class DemoCatalog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.cases = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.by_digest = {case["sha256"]: case for case in self.cases}
        self.archive = self.build_archive()

    def build_archive(self) -> bytes:
        """Montado uma vez na subida: o endpoint serve bytes prontos, sem trabalho por requisição."""
        notes = [
            "Boletos sintéticos do ScamShield, para testar a demonstração.",
            "Nenhum deles tem valor de pagamento.",
            "",
            "Envie o PDF na página inicial. A demonstração reconhece o nome do arquivo",
            "e preenche automaticamente os dados necessários para o cenário.",
            "",
        ]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for case in self.cases:
                archive.write(self.directory / case["file"], case["file"])
                notes.append(f"{case['file']} — {case['label']}")
                notes.append(f"  esperado: {case['expected_status']} / {case['expected_score']}")
                notes.append("")
            archive.writestr("LEIA-ME.txt", "\n".join(notes))
        return buffer.getvalue()


class FakeDocumentReader:
    def __init__(self, catalog: DemoCatalog):
        self.catalog = catalog

    async def read(self, content: bytes, mime_type: str):
        case = self.catalog.by_digest.get(hashlib.sha256(content).hexdigest())
        if case is None:
            raise ReaderError(DocumentFailure.UNKNOWN_DEMO_DOCUMENT)
        if case.get("reader_failure"):
            raise ReaderError(DocumentFailure(case["reader_failure"]))
        return DocumentExtraction.model_validate_json(json.dumps(case["extraction"])).to_domain()


class FakeRegistry:
    def __init__(self, catalog: DemoCatalog):
        self.results = {
            case["registry"]["cnpj"]: case["registry"]
            for case in catalog.cases
            if case.get("registry")
        }

    async def lookup(self, cnpj, cache):
        item = self.results.get(cnpj)
        if item is None:
            return RegistryResult(RegistryState.NOT_FOUND)
        return RegistryResult(
            RegistryState(item["state"]),
            cnpj,
            item.get("legal_name"),
            item.get("trade_name"),
            item.get("situation"),
            RegistryFailure(item.get("failure", "unavailable")),
        )
