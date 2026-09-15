"""Executar a aplicação localmente, sem logs de acesso com conteúdo do cliente."""

import argparse
import logging
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from scamshield.main import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        app = create_app()
    except ValidationError:
        raise SystemExit(
            "Configuração inválida. Confira as variáveis em .env.example; nenhum segredo foi exibido."
        ) from None
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
