"""TTL limitado; cadastro só pode usar uma instância local à requisição."""

from collections import OrderedDict
from collections.abc import Callable
from time import monotonic
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl: float, capacity: int = 128, clock: Callable[[], float] = monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._values: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        entry = self._values.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires <= self.clock():
            del self._values[key]
            return None
        return value

    def put(self, key: str, value: T) -> None:
        self._values.pop(key, None)
        self._values[key] = (self.clock() + self.ttl, value)
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)

    def clear(self) -> None:
        self._values.clear()
