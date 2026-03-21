"""
Централизованная конфигурация. Все сервисы импортируют:
  from shared.config import settings
"""
from __future__ import annotations
import random
from functools import lru_cache
from typing import Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "astana_prices"
    postgres_user: str = "ap_user"
    postgres_password: str = ""
    database_url: str = ""
    database_pool_size: int = 20
    database_max_overflow: int = 10

    @model_validator(mode="after")
    def build_db_url(self) -> "Settings":
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_celery_broker: str = "redis://redis:6379/1"
    redis_celery_results: str = "redis://redis:6379/2"
    redis_cache: str = "redis://redis:6379/3"
    redis_stream_maxlen: int = 100_000

    # Celery
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_timezone: str = "Asia/Almaty"
    celery_worker_concurrency: int = 4
    celery_task_soft_time_limit: int = 2400
    celery_task_time_limit: int = 2700

    # Gemini — 2 аккаунта (бесплатный тир)
    gemini_api_key_1: str = ""
    gemini_api_key_2: str = ""
    gemini_model_normalize: str = "gemini-2.0-flash"
    gemini_model_generate: str = "gemini-1.5-pro-latest"
    gemini_embedding_model: str = "text-embedding-004"
    gemini_flash_rpm_limit: int = 15    # на 1 аккаунт
    gemini_flash_rpd_limit: int = 1500
    gemini_pro_rpm_limit: int = 2
    gemini_pro_rpd_limit: int = 50
    gemini_normalize_batch_size: int = 30

    @property
    def gemini_keys(self) -> list[str]:
        return [k for k in [self.gemini_api_key_1, self.gemini_api_key_2] if k]

    @property
    def gemini_flash_rpm_total(self) -> int:
        """RPM с учётом всех аккаунтов"""
        return self.gemini_flash_rpm_limit * len(self.gemini_keys)

    # Telegram
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    telegram_channel_numeric_id: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    telegram_admin_chat_id: str = ""
    telegram_dry_run: bool = True  # True = посты в личку, не в канал

    # Scraping (без прокси — статический IP)
    scraper_request_delay_min_ms: int = 1500
    scraper_request_delay_max_ms: int = 4000
    scraper_timeout_seconds: int = 45
    scraper_max_retries: int = 3
    scraper_concurrency: int = 2
    playwright_headless: bool = True
    scraper_active_hours_start: int = 7    # Астана (UTC+5)
    scraper_active_hours_end: int = 23

    scraper_user_agents: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    @property
    def user_agent_list(self) -> list[str]:
        return [ua.strip() for ua in self.scraper_user_agents.split(",") if ua.strip()]

    @property
    def random_user_agent(self) -> str:
        return random.choice(self.user_agent_list)

    @property
    def random_delay_ms(self) -> int:
        return random.randint(self.scraper_request_delay_min_ms, self.scraper_request_delay_max_ms)

    # Магазины
    magnum_base_url: str = "https://magnum.kz"
    arbuz_base_url: str = "https://arbuz.kz"
    arbuz_graphql_url: str = "https://arbuz.kz/ru/almaty/api/graphql"
    small_base_url: str = "https://small.kz"
    galmart_base_url: str = "https://galmart.kz"
    astore_base_url: str = "https://a-store.kz"
    anvar_base_url:  str = "https://www.anvar.kz"

    # API
    api_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 720
    cors_origins: str = "http://localhost:3000"
    debug: bool = False
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Frontend
    next_public_api_url: str = ""
    next_public_tg_bot_username: str = ""
    next_public_site_url: str = ""

    # Мониторинг
    grafana_admin_user: str = "admin"
    grafana_admin_password: str = ""
    prometheus_retention_days: int = 30
    sentry_dsn: Optional[str] = None

    # Сервер
    domain: str = "localhost"
    server_ip: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
