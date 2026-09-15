"""Orquestração com dependências explícitas e descarte no finally."""

import asyncio

from ..domain.boleto import InvalidBoleto, parse_boleto
from ..domain.decision import evaluate
from ..domain.identifiers import normalize_cnpj, valid_cnpj
from ..domain.models import (
    AnalysisEvidence,
    DocumentFailure,
    RegistryFailure,
    RegistryResult,
    RegistryState,
    Source,
)
from ..infrastructure.cache import TTLCache
from ..integrations.document_reader import DocumentReader, ReaderError, Registry
from ..settings import Settings
from .documents import inspect_document


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        reader: DocumentReader,
        registry: Registry,
        banks: tuple,
        institutions: tuple,
    ):
        self.settings, self.reader, self.registry = settings, reader, registry
        self.banks, self.institutions = banks, institutions

    async def analyze(self, line: str | None, content: bytes | None, mime_type: str | None):
        document = registry_result = boleto = failure = None
        cache = TTLCache[RegistryResult](ttl=self.settings.analysis_timeout, capacity=2)

        async def read_document():
            nonlocal document, failure
            if content is None:
                return
            try:
                async with asyncio.timeout(self.settings.reader_timeout):
                    inspect_document(content, mime_type, self.settings.max_pdf_pages)
                    document = await self.reader.read(content, mime_type)
            except TimeoutError:
                failure = DocumentFailure.TIMEOUT
            except ReaderError as exc:
                failure = exc.reason
            except Exception:
                failure = DocumentFailure.UNAVAILABLE

        async def parse_text():
            nonlocal boleto
            if line:
                boleto = parse_boleto(line, banks=self.banks)

        try:
            async with asyncio.timeout(self.settings.analysis_timeout):
                # A consulta cadastral DEPENDE do CNPJ; somente frentes independentes
                # saem juntas. TaskGroup garante cancelamento e término das irmãs.
                async with asyncio.TaskGroup() as tasks:
                    await asyncio.gather(
                        tasks.create_task(read_document()), tasks.create_task(parse_text())
                    )
                if document is not None:
                    if (
                        boleto is None
                        and document.payment_code
                        and "payment_code" not in document.uncertain_fields
                    ):
                        try:
                            boleto = parse_boleto(
                                document.payment_code, source=Source.DOCUMENT, banks=self.banks
                            )
                        except InvalidBoleto:
                            failure = DocumentFailure.UNREADABLE
                    if (
                        document.identifier_type == "CNPJ"
                        and "identifier" not in document.uncertain_fields
                        and valid_cnpj(document.identifier)
                    ):
                        try:
                            async with asyncio.timeout(self.settings.registry_timeout):
                                registry_result = await self.registry.lookup(
                                    normalize_cnpj(document.identifier), cache
                                )
                        except TimeoutError:
                            registry_result = RegistryResult(
                                RegistryState.UNAVAILABLE, failure=RegistryFailure.TIMEOUT
                            )
                        except Exception:
                            registry_result = RegistryResult(RegistryState.UNAVAILABLE)
            return evaluate(
                AnalysisEvidence(
                    boleto, document, registry_result, self.banks, self.institutions, failure
                )
            )
        except TimeoutError:
            if document is not None:
                registry_result = RegistryResult(
                    RegistryState.UNAVAILABLE, failure=RegistryFailure.TIMEOUT
                )
            else:
                failure = DocumentFailure.TIMEOUT
            return evaluate(
                AnalysisEvidence(
                    boleto, document, registry_result, self.banks, self.institutions, failure
                )
            )
        finally:
            # Nenhuma evidência continua em tarefas, caches compartilhados ou logs.
            # Remove referências; Python não garante apagamento físico do heap.
            cache.clear()
            content = line = document = registry_result = boleto = None
