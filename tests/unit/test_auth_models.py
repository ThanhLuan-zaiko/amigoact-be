from sqlalchemy.dialects.postgresql import CITEXT

from connector.models import auth  # noqa: F401  registers the auth tables
from connector.models.auth import User
from connector.models.base import Base

AUTH_TABLES = {
    "users",
    "auth_refresh_tokens",
    "auth_sessions",
    "password_resets",
    "email_verifications",
    "auth_rate_limits",
}


def test_auth_models_register_all_auth_tables() -> None:
    assert AUTH_TABLES <= set(Base.metadata.tables)


def test_user_email_uses_case_insensitive_citext() -> None:
    assert isinstance(User.__table__.c.email.type, CITEXT)
