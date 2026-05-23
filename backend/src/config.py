"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ─── API ──────────────────────────────────────────────────────────
    api_auth_key: str = Field(default="dev-key", alias="API_AUTH_KEY")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # ─── Database ─────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./app.db",
        alias="DATABASE_URL",
    )

    # ─── Vibe-Trading Agent ───────────────────────────────────────────
    vibe_trading_api_url: str = Field(
        default="http://localhost:8899",
        alias="VIBE_TRADING_API_URL",
    )

    # ─── CORS ─────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["http://localhost:5899", "http://localhost:3000"],
        alias="CORS_ORIGINS",
    )


settings = Settings()
