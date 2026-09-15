"""Configuração de implantação. Nenhuma credencial real no repositório."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_KEY = "scamshield-demo-local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCAMSHIELD_",
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )
    mode: Literal["demo", "live"] = "demo"
    api_keys: dict[str, SecretStr] = Field(default_factory=lambda: {"demo": SecretStr(DEMO_KEY)})
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    reader_timeout: float = Field(default=2.8, gt=0, le=30)
    registry_timeout: float = Field(default=1.2, gt=0, le=30)
    analysis_timeout: float = Field(default=4.5, gt=0, le=60)
    upload_timeout: float = Field(default=15, gt=0, le=60)
    rate_limit: int = Field(default=30, ge=1, le=10000)
    rate_window: float = Field(default=60, gt=0)
    max_concurrent: int = Field(default=8, ge=1, le=64)
    max_body_bytes: int = Field(default=7 * 1024 * 1024, ge=1024, le=8 * 1024 * 1024)
    max_file_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=5 * 1024 * 1024)
    max_pdf_pages: int = Field(default=3, ge=1, le=3)
    data_dir: Path = Path(__file__).resolve().parent / "data"
    web_dir: Path = Path(__file__).resolve().parent / "web"

    @model_validator(mode="after")
    def validate_live(self):
        if not self.api_keys or any(
            not k or not v.get_secret_value() for k, v in self.api_keys.items()
        ):
            raise ValueError("Configure ao menos uma chave e um identificador de parceiro.")
        if len({v.get_secret_value() for v in self.api_keys.values()}) != len(self.api_keys):
            raise ValueError("Cada parceiro deve ter uma chave distinta.")
        if self.mode == "live":
            if any(
                len(v.get_secret_value()) < 24 or v.get_secret_value() == DEMO_KEY
                for v in self.api_keys.values()
            ):
                raise ValueError("Modo live exige chaves próprias com ao menos 24 caracteres.")
            if not self.gemini_api_key.get_secret_value() or not self.gemini_model:
                raise ValueError("Configure credencial e modelo Gemini para modo live.")
        return self
