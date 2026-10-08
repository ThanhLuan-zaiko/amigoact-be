"""Application settings loaded from environment (.env)."""

from __future__ import annotations

from functools import lru_cache

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
    env: str = "dev"

    @property
    def scylla_hosts_list(self) -> list[str]:
        """Split comma-separated hosts into a clean list."""
        hosts = [h.strip() for h in self.scylla_hosts.split(",") if h.strip()]
        return hosts or ["127.0.0.1"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance (created once per process)."""
    return Settings()
