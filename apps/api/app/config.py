import re
from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
LOCAL_POSTGRES_SOCKET = ROOT_DIR / ".postgres-socket"
LOCAL_DATABASE_URL = f"postgresql+psycopg://health_guard@/health_guard?host={LOCAL_POSTGRES_SOCKET}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = LOCAL_DATABASE_URL
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Comma-separated exact origins. In production this must include the deployed frontend, or the
    # browser blocks every request to this API.
    cors_origins: str = "http://localhost:3000"
    # Optional regex for dynamic origins — Vercel gives every preview deployment its own hostname,
    # which cannot be enumerated ahead of time. Leave empty to allow only the exact list above.
    cors_origin_regex: str | None = None
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = 60
    prava_api_key: str | None = None
    prava_secret_key: str | None = None
    prava_api_base_url: AnyHttpUrl = "https://sandbox.api.prava.space"
    health_guard_sandbox_settlement_enabled: bool = False
    health_guard_ucp_profile_url: AnyHttpUrl | None = None
    # Which executor presents the one-time card at the merchant. "auto" prefers Prava's Browser
    # Harness (CLI) and falls back to Playwright. Anything unavailable settles DECLINED, never
    # APPROVED, so a misconfiguration can't be mistaken for a purchase.
    # "playwright" drives the merchant's own checkout in-process with headless Chromium.
    # "none" disables checkout entirely, so every charge settles DECLINED.
    merchant_checkout_backend: str = "playwright"
    # False opens a visible browser — useful for recording a demo of the decline.
    checkout_headless: bool = True
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: str = "medium"

    @field_validator("openai_model", mode="before")
    @classmethod
    def normalize_openai_model(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        aliases = {
            "gpt56sol": "gpt-5.6-sol",
            "gpt56terra": "gpt-5.6-terra",
            "gpt56luna": "gpt-5.6-luna",
        }
        return aliases.get(re.sub(r"[^a-z0-9]", "", cleaned.casefold()), cleaned)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
