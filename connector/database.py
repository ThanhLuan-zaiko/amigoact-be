"""Database engine and connection helpers."""

from sqlalchemy import Engine, create_engine, text


def create_database_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def check_connection(engine: Engine) -> None:
    """Run a trivial query so that a bad URL or a stopped server fails fast."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
