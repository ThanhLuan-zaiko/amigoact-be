"""Application settings loaded from environment (.env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of runtime configuration (see README for variables)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    scylla_hosts: str = "127.0.0.1"
    scylla_port: int = 9042
    scylla_datacenter: str = "datacenter1"
    scylla_keyspace: str = "amigoact"
    jwt_secret: str  # Required: no default so boot fails fast without a secret.
    jwt_access_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 14
    verification_code_ttl_minutes: int = 15
    reset_code_ttl_minutes: int = 15
    login_max_attempts: int = 5
    login_window_seconds: int = 60
    code_max_attempts: int = 5
    code_window_seconds: int = 300
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = "no-reply@amigoact.local"
    frontend_urls: str = "http://localhost:5173"
    env: str = "dev"
    media_root: str = "./media"
    media_max_image_mb: int = 10
    media_max_video_mb: int = 100
    ws_ticket_ttl_seconds: int = Field(default=60, ge=5, le=300)
    ws_heartbeat_seconds: int = Field(default=25, ge=1, le=120)
    ws_pong_timeout_seconds: int = Field(default=10, ge=1, le=120)
    ws_max_frame_bytes: int = Field(default=65536, ge=1024, le=1048576)
    ws_ticket_per_min: int = Field(default=10, ge=1, le=100)
    ws_frame_per_sec: int = Field(default=20, ge=1, le=100)

    @property
    def frontend_urls_list(self) -> list[str]:
        """Split comma-separated frontend origins for CORS allow-list."""
        return [u.strip() for u in self.frontend_urls.split(",") if u.strip()]

    @property
    def scylla_hosts_list(self) -> list[str]:
        """Split comma-separated hosts into a clean list."""
        hosts = [h.strip() for h in self.scylla_hosts.split(",") if h.strip()]
        return hosts or ["127.0.0.1"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance (created once per process)."""
    return Settings()
