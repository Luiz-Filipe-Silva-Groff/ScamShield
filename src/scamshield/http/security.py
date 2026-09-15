import hashlib
import hmac
import math
from collections import deque
from time import monotonic

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from .errors import APIError

key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class RateLimiter:
    def __init__(self, limit: int, window: float, clock=monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.events: dict[str, deque] = {}

    def check(self, partner: str) -> int:
        now = self.clock()
        queue = self.events.setdefault(partner, deque())
        while queue and queue[0] <= now - self.window:
            queue.popleft()
        if len(queue) >= self.limit:
            return max(1, math.ceil(queue[0] + self.window - now))
        queue.append(now)
        return 0


async def authenticate(request: Request, key: str | None = Depends(key_header)) -> str:
    if key is None or len(key) > 512:
        raise APIError(401, "unauthorized", "Chave de acesso ausente ou inválida.")
    provided = hashlib.sha256(key.encode()).digest()
    partner = None
    for name, secret in request.app.state.settings.api_keys.items():
        if hmac.compare_digest(
            provided, hashlib.sha256(secret.get_secret_value().encode()).digest()
        ):
            partner = name
    if partner is None:
        raise APIError(401, "unauthorized", "Chave de acesso ausente ou inválida.")
    retry = request.app.state.limiter.check(partner)
    if retry:
        raise APIError(
            429,
            "rate_limited",
            "Limite de requisições atingido. Tente novamente em instantes.",
            retry,
        )
    return partner
