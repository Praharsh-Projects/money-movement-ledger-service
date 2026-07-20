from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/money_movement"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = Field(default="local-development-key", min_length=16)
    event_stream: str = "money_movement.events.v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
