"""Centralised configuration loaded from environment / .env file.

Single source of truth for every other module – nobody reads os.environ
directly. Use `get_settings()` so values are cached for the process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to /workspace/strategy_app/.env regardless of CWD
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """All runtime configuration."""

    # ---- LLM ----
    llm_provider: str = Field(default="openai")
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="")
    llm_model: str = Field(default="gpt-4o-mini")

    # ---- News providers ----
    fmp_api_key: str = Field(default="")
    cryptopanic_auth_token: str = Field(default="")

    # ---- Behaviour ----
    use_mock: bool = Field(default=True)
    cache_ttl_minutes: int = Field(default=360)
    default_feed_limit: int = Field(default=20)

    # ---- Server ----
    backend_host: str = Field(default="127.0.0.1")
    backend_port: int = Field(default=8088)

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH) if _ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Convenience ----
    @property
    def has_llm(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_fmp(self) -> bool:
        return bool(self.fmp_api_key)

    @property
    def has_cryptopanic(self) -> bool:
        return bool(self.cryptopanic_auth_token)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton."""
    return Settings()
