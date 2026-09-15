"""Respostas externas limitadas e erros sem URL/CNPJ/corpo."""

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


async def bounded_json(
    client: httpx.AsyncClient, method: str, url: str, *, limit: int = 128 * 1024, **kwargs
):
    data = bytearray()
    try:
        async with client.stream(method, url, **kwargs) as response:
            if response.status_code != 200:
                return response.status_code, response.headers.get("retry-after"), None
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > limit:
                    raise ValueError("Resposta externa excedeu o limite.")
                data.extend(chunk)
            return 200, None, json.loads(data)
    finally:
        data.clear()


def retry_seconds(value: str | None) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            seconds = 30
    return max(1, min(seconds, 300))
