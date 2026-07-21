from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/money_movement"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = Field(default="local-development-key", min_length=16)
    event_stream: str = "money_movement.events.v1"
    risk_review_mode: Literal["policy_baseline", "openai_compatible"] = "policy_baseline"
    ai_base_url: str = "http://localhost:11434/v1"
    ai_model: str = "qwen2.5:7b-instruct"
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    ai_max_output_tokens: int = Field(default=500, ge=100, le=2_000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
