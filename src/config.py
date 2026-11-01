"""Application settings read only from the .env file."""

from functools import lru_cache

from pydantic import Field
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


def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
