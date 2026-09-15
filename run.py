"""Executar a aplicação localmente, sem logs de acesso com conteúdo do cliente."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
import uvicorn
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from scamshield.integrations.gemini_reader import GeminiReader
from scamshield.main import create_app
from scamshield.settings import Settings


def preflight(settings: Settings) -> None:
    """Confere credencial e modelo antes de abrir a porta.

    Erro de configuração não se resolve sozinho: em produção ele se disfarçaria de
    sinal de incerteza e o serviço responderia WARNING a todo boleto, aparentando
    funcionar. Fica aqui, e não em create_app, para a suíte continuar sem rede.
    """
    if settings.mode != "live":
        return

    # O lifespan só silencia estes loggers depois; o preflight roda antes dele.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).propagate = False

    async def check():
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            await GeminiReader(
                client,
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_model,
                settings.reader_timeout,
            ).verify()

    asyncio.run(check())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit(
            "Configuração inválida. Confira as variáveis em .env.example; nenhum segredo foi exibido."
        ) from None
    try:
        preflight(settings)
    except ValueError as exc:
        raise SystemExit(f"Configuração inválida: {exc}") from None
    app = create_app(settings)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
