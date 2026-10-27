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
    # Empty username = no auth (local dev); set both on secured clusters.
    scylla_username: str = ""
    scylla_password: str = ""
    scylla_connect_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    scylla_request_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    # Threadpool size for sync endpoints and the slow-request log threshold.
    worker_threads: int = Field(default=200, ge=10, le=1000)
    slow_request_ms: float = Field(default=500.0, ge=1.0)
    jwt_secret: str  # Required: no default so boot fails fast without a secret.
    # Base64 32-byte AES key for chat bodies at rest; empty derives one
    # from jwt_secret (documented fallback, rotate via this field).
    chat_message_key: str = ""
    jwt_access_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 14
    verification_code_ttl_minutes: int = 15
    reset_code_ttl_minutes: int = 15
    login_max_attempts: int = 5
    login_window_seconds: int = 60
    refresh_max_attempts: int = 30
    refresh_window_seconds: int = 60
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
    # Edge guard: the second wall behind the CDN. A bounded in-flight pool
    # sheds overload (503) and a per-IP fixed-window counter in ScyllaDB
    # rate-limits floods (429); see core/guard.py.
    guard_enabled: bool = True
    guard_max_concurrent: int = Field(default=256, ge=0)
    guard_queue_ms: int = Field(default=250, ge=0, le=10_000)
    guard_ip_max_hits: int = Field(default=300, ge=0)
    guard_ip_window_seconds: int = Field(default=60, ge=1, le=3600)
    guard_max_body_mb: int = Field(default=128, ge=0)
    # Header carrying the real client IP behind a trusted edge proxy
    # (Cloudflare sends cf-connecting-ip). Empty string trusts the TCP peer.
    guard_client_ip_header: str = "cf-connecting-ip"
    guard_exempt_paths: str = ""
    # Comma-separated emails that always count as platform admins. This is
    # the bootstrap path; additional admins live in platform_user_roles.
    platform_admin_emails: str = ""

    @property
    def frontend_urls_list(self) -> list[str]:
        """Split comma-separated frontend origins for CORS allow-list."""
        return [u.strip() for u in self.frontend_urls.split(",") if u.strip()]

    @property
    def guard_exempt_paths_set(self) -> frozenset[str]:
        """Extra guard-exempt paths beyond the built-in probe/doc set."""
        return frozenset(
            p.strip() for p in self.guard_exempt_paths.split(",") if p.strip()
        )

    @property
    def platform_admin_emails_set(self) -> frozenset[str]:
        """Lowercased bootstrap admin emails (env-sourced, not stored)."""
        return frozenset(
            e.strip().lower()
            for e in self.platform_admin_emails.split(",")
            if e.strip()
        )

    @property
    def scylla_hosts_list(self) -> list[str]:
        """Split comma-separated hosts into a clean list."""
        hosts = [h.strip() for h in self.scylla_hosts.split(",") if h.strip()]
        return hosts or ["127.0.0.1"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance (created once per process)."""
    return Settings()
