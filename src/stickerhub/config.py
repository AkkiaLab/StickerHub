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
    feishu_webhook_allowed_hosts: list[str] | None = Field(
        default=None,
        alias="FEISHU_WEBHOOK_ALLOWED_HOSTS",
        description=(
            "飞书 Webhook 域名白名单（JSON 格式，如 "
            '["open.feishu.cn","open.larksuite.com"]）。'
            "设为 null 或空列表 [] 禁用白名单校验。"
            "不设置时使用默认白名单。"
        ),
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_webhook_allowed_hosts(self) -> list[str] | None:
        """
        获取 webhook 域名白名单。
        - None: 使用默认白名单 ["open.feishu.cn", "open.larksuite.com"]
        - []: 禁用白名单校验
        - [...]: 使用自定义白名单
        """
        if self.feishu_webhook_allowed_hosts is None:
            return ["open.feishu.cn", "open.larksuite.com"]
        return self.feishu_webhook_allowed_hosts
