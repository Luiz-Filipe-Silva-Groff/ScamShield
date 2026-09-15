"""Inspeção limitada em memória. Nunca abre caminhos do usuário."""

import io
import warnings

from PIL import Image
from pypdf import PdfReader

from ..domain.models import DocumentFailure
from ..integrations.document_reader import ReaderError


def inspect_document(content: bytes, mime_type: str, max_pages: int) -> None:
    try:
        if mime_type == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise ValueError("Formato inválido")
            with io.BytesIO(content) as stream:
                reader = PdfReader(stream, strict=True)
                if reader.is_encrypted or not 1 <= len(reader.pages) <= max_pages:
                    raise ValueError("PDF fora dos limites")
        else:
            expected = "PNG" if mime_type == "image/png" else "JPEG"
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != expected or image.width * image.height > 20_000_000:
                        raise ValueError("Imagem fora dos limites")
                    image.verify()
    except Exception:
        # Bibliotecas de PDF/imagem podem incluir trechos do documento nos erros.
        raise ReaderError(DocumentFailure.UNREADABLE) from None
