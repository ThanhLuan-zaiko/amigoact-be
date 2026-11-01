from sqlalchemy import inspect

from connector.config import get_settings
from connector.database import create_database_engine
from connector.models import auth  # noqa: F401  registers the auth tables
from connector.models.base import Base

AUTH_TABLES = [
    "users",
    "auth_refresh_tokens",
    "auth_sessions",
    "password_resets",
    "email_verifications",
    "auth_rate_limits",
]


def test_auth_models_match_database_columns() -> None:
    engine = create_database_engine(get_settings().database_url)
    try:
        inspector = inspect(engine)
        for name in AUTH_TABLES:
            assert inspector.has_table(name), name
            database_columns = {
                column["name"] for column in inspector.get_columns(name)
            }
            model_columns = set(Base.metadata.tables[name].columns.keys())
            assert model_columns == database_columns, name
    finally:
        engine.dispose()
