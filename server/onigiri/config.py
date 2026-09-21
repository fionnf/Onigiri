"""Application configuration, loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- core ---
    app_name: str = "Onigiri"
    environment: Literal["dev", "prod", "test"] = "dev"
    secret_key: str = "dev-insecure-secret-change-me"
    base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # --- database ---
    database_url: str = "postgresql+asyncpg://onigiri:onigiri@127.0.0.1:5432/onigiri"

    # --- owner bootstrap (single-user app) ---
    owner_email: str = "owner@localhost"
    owner_password: str = "changeme"

    # --- job backend ---
    job_backend: Literal["inline", "arq"] = "inline"
    redis_url: str = "redis://127.0.0.1:6379"

    # --- object storage (S3 API: Cloudflare R2, MinIO, AWS) ---
    s3_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_bucket: str = "onigiri"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_public_base_url: str | None = None
    media_dir: str = "./.media"  # used when S3 is not configured

    # --- OpenAI ---
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_extract_model: str = "gpt-4.1"
    openai_vision_model: str = "gpt-4.1"
    openai_stt_model: str = "whisper-1"
    openai_embed_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # --- Apify (Instagram) ---
    apify_token: str | None = None
    apify_instagram_actor: str = "apify~instagram-scraper"
    apify_timeout_s: int = 180
    ytdlp_instagram_fallback: bool = False

    # --- pipeline limits ---
    max_upload_mb: int = 512
    max_keyframes: int = 60
    keyframe_interval_s: float = 2.0
    max_video_seconds: int = 3600
    transcribe_chunk_seconds: int = 600
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # --- cost guardrails ---
    monthly_job_cap: int = 500

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Accept the plain libpq URL that hosting providers hand out.
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2").replace(
            "postgresql+psycopg2", "postgresql"
        )

    @property
    def use_s3(self) -> bool:
        return bool(self.s3_access_key_id and self.s3_secret_access_key)

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
