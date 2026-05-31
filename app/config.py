from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "store-intelligence-api"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", description="deployment environment")
    log_level: str = "INFO"
    log_json: bool = Field(default=False, description="emit JSON logs (auto-enabled in production)")

    database_url: str = Field(
        default="postgresql+asyncpg://si:si@localhost:5432/store_intelligence",
        description="async SQLAlchemy database URL",
    )
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    event_schema_version: str = "1.0.0"
    default_tenant_slug: str = "default"

    health_stale_feed_minutes: int = Field(
        default=15,
        description="Minutes without feed events before STALE_FEED is reported",
    )

    api_key: str = Field(
        default="",
        description="Shared secret for X-API-Key header on protected routes",
    )
    api_key_required: bool = Field(
        default=False,
        description="When true, ingest and store analytics routes require X-API-Key",
    )
    reviewer_mode: bool = Field(
        default=True,
        description="Purple Tech demo mode — accept purple-demo-key on all protected routes",
    )
    reviewer_api_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL embedded in reviewer API guide (override behind proxy)",
    )
    metrics_projector_enabled: bool = Field(
        default=True,
        description="Project footfall metrics into store_metrics after successful ingest",
    )
    metrics_projector_hours_back: int = Field(
        default=24,
        description="Rolling window for automatic footfall projection",
    )

    pos_csv_path: str = Field(
        default="data/pos/Brigade_Bangalore_10_April_26.csv",
        description="Default POS CSV for Brigade Road (ST1008)",
    )
    pos_auto_ingest: bool = Field(
        default=True,
        description="Ingest POS CSV on API startup (idempotent)",
    )
    pos_store_id: str = Field(
        default="00000000-0000-0000-0000-000000000101",
        description="Store UUID for POS CSV (Brigade Road)",
    )

    cctv_auto_bootstrap: bool = Field(
        default=True,
        description="Load committed YOLO bootstrap events when no CCTV data exists",
    )
    cctv_bootstrap_path: str = Field(
        default="data/reviewer/yolo_bootstrap_events.jsonl",
        description="JSONL snapshot of real YOLO events for first-boot demo",
    )
    cctv_bootstrap_min_events: int = Field(
        default=10,
        description="Skip bootstrap when at least this many vision events exist",
    )
    cctv_store_id: str = Field(
        default="00000000-0000-0000-0000-000000000101",
        description="Store UUID for CCTV bootstrap",
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def effective_api_key(self) -> str:
        """Key reviewers must send when auth is enabled."""
        if self.reviewer_mode:
            return "purple-demo-key"
        return (self.api_key or "").strip() or "purple-demo-key"

    @property
    def use_json_logs(self) -> bool:
        return self.log_json or self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
