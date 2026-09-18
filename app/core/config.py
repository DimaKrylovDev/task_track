from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Task Tracker API"
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker"
    replica_database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:5433/tracker"
    shard_database_urls: list[str] = Field(
        default_factory=lambda: [
            f"postgresql+asyncpg://tracker:tracker@localhost:{port}/tracker"
            for port in range(56540, 56544)
        ]
    )
    jwt_secret: str = Field(
        default="unsafe-development-secret-change-this-value", min_length=32
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=30, ge=1)
    sql_echo: bool = False
    partition_alert_webhook_url: str | None = None
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    celery_broker_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
