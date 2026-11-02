"""Application settings read only from the .env file."""

import base64
import binascii
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class DotenvSettings(BaseSettings):
    """Base class. Values come only from `.env`, never from code or OS variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (dotenv_settings,)


class Settings(DotenvSettings):
    """Runtime settings needed to reach the database."""

    database_url: str


class AuthSettings(DotenvSettings):
    """Settings for tokens and account emails."""

    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    password_reset_minutes: int = 60
    email_verification_hours: int = 24
    frontend_url: str = "http://localhost:3000"
    # Without an SMTP host, emails are written to the application log.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@amigoact.local"


class MediaSettings(DotenvSettings):
    """Where uploaded files are kept on the local disk."""

    # Relative paths are resolved from the directory the server starts in.
    media_dir: Path = Path("media")


@lru_cache
def get_media_settings() -> MediaSettings:
    return MediaSettings()


class ChatSettings(DotenvSettings):
    """Key that encrypts chat messages. Losing it makes the stored messages unreadable."""

    # Base64 of 32 random bytes, for example from: openssl rand -base64 32
    chat_encryption_key: str

    @field_validator("chat_encryption_key")
    @classmethod
    def _must_be_a_256_bit_key(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("CHAT_ENCRYPTION_KEY must be base64") from exc
        if len(raw) != 32:
            raise ValueError("CHAT_ENCRYPTION_KEY must decode to 32 bytes")
        return value


@lru_cache
def get_chat_settings() -> ChatSettings:
    return ChatSettings()


def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
