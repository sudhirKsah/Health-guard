from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl
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
    cors_origins: str = "http://localhost:3000"
    prava_api_key: str | None = None
    prava_secret_key: str | None = None
    prava_api_base_url: AnyHttpUrl = "https://sandbox.api.prava.space"
    health_guard_ucp_profile_url: AnyHttpUrl | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
