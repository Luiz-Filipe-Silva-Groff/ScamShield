from typing import Protocol

from ..domain.models import DocumentFailure, ExtractedDocument, RegistryResult
from ..infrastructure.cache import TTLCache


class ReaderError(Exception):
    def __init__(self, reason: DocumentFailure):
        self.reason = reason
        super().__init__(reason.value)


class DocumentReader(Protocol):
    async def read(self, content: bytes, mime_type: str) -> ExtractedDocument: ...


class Registry(Protocol):
    async def lookup(self, cnpj: str, cache: TTLCache[RegistryResult]) -> RegistryResult: ...
