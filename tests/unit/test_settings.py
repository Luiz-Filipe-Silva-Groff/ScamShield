import pytest
from pydantic import ValidationError

from scamshield.http.security import RateLimiter
from scamshield.settings import Settings


@pytest.mark.parametrize(
    "config",
    [
        {"api_keys": {}},
        {"api_keys": {"demo": ""}},
        {"api_keys": {"": "token"}},
        {"api_keys": {"a": "same", "b": "same"}},
        {"mode": "live"},
        {"mode": "live", "api_keys": {"bank": "x" * 32}},
    ],
)
def test_invalid_configuration_fails_at_startup(config):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **config)


def test_rate_window_recovers_at_boundary():
    now = [0.0]
    limiter = RateLimiter(1, 60, clock=lambda: now[0])
    assert limiter.check("partner") == 0
    assert limiter.check("partner") == 60
    now[0] = 60
    assert limiter.check("partner") == 0
