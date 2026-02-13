from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_api_token: str = Field(
        default="",
        min_length=1,
        alias="TELEGRAM_BOT_API_TOKEN",
    )
    feishu_app_id: str = Field(
        default="",
        alias="FEISHU_APP_ID",
    )
    feishu_app_secret: str = Field(
        default="",
        alias="FEISHU_APP_SECRET",
    )
    binding_db_path: str = Field(
        default="data/stickerhub.db",
        validation_alias=AliasChoices("BINDING_DB_PATH", "BINDING_STORE_PATH"),
    )
    bind_magic_ttl_seconds: int = Field(default=600, alias="BIND_MAGIC_TTL_SECONDS")
    feishu_webhook_allowed_hosts: list[str] = Field(
        default=["open.feishu.cn", "open.larksuite.com"],
        alias="FEISHU_WEBHOOK_ALLOWED_HOSTS",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
