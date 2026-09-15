from time import monotonic

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.identifiers import normalize_cnpj, valid_cnpj
from ..domain.models import RegistryFailure, RegistryResult, RegistryState
from ..infrastructure.cache import TTLCache
from .http_client import bounded_json, retry_seconds


class Company(BaseModel):
    model_config = ConfigDict(strict=True)
    cnpj: str
    razao_social: str = Field(min_length=1, max_length=300)
    nome_fantasia: str | None = Field(default=None, max_length=300)
    situacao_cadastral: int


class BrasilAPI:
    def __init__(self, client: httpx.AsyncClient, timeout: float):
        self.client, self.timeout = client, timeout
        self.cooldown_until = 0.0  # Somente metadado operacional, sem CNPJ.

    async def lookup(self, cnpj: str, cache: TTLCache[RegistryResult]) -> RegistryResult:
        if not valid_cnpj(cnpj):
            return RegistryResult(RegistryState.INVALID)
        cnpj = normalize_cnpj(cnpj)
        cached = cache.get(cnpj)
        if cached is not None:
            return cached
        if monotonic() < self.cooldown_until:
            return RegistryResult(RegistryState.UNAVAILABLE, failure=RegistryFailure.RATE_LIMITED)
        payload = None
        try:
            status, retry_after, payload = await bounded_json(
                self.client,
                "GET",
                f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
                timeout=self.timeout,
            )
            if status == 429:
                self.cooldown_until = monotonic() + retry_seconds(retry_after)
                return RegistryResult(
                    RegistryState.UNAVAILABLE, failure=RegistryFailure.RATE_LIMITED
                )
            if status == 404:
                return RegistryResult(RegistryState.NOT_FOUND)
            if status == 400:
                return RegistryResult(RegistryState.INVALID)
            if status != 200:
                return RegistryResult(RegistryState.UNAVAILABLE)
            company = Company.model_validate(payload)
            if normalize_cnpj(company.cnpj) != cnpj:
                return RegistryResult(
                    RegistryState.UNAVAILABLE, failure=RegistryFailure.INVALID_RESPONSE
                )
            result = RegistryResult(
                RegistryState.FOUND,
                cnpj,
                company.razao_social,
                company.nome_fantasia,
                company.situacao_cadastral,
            )
            cache.put(cnpj, result)
            return result
        except httpx.TimeoutException:
            return RegistryResult(RegistryState.UNAVAILABLE, failure=RegistryFailure.TIMEOUT)
        except httpx.HTTPError:
            return RegistryResult(RegistryState.UNAVAILABLE)
        except (ValueError, ValidationError):
            return RegistryResult(
                RegistryState.UNAVAILABLE, failure=RegistryFailure.INVALID_RESPONSE
            )
        finally:
            payload = None  # Não reter a resposta completa (sócios/endereço etc.).
