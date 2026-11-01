"""Reset the database named in DATABASE_URL by reloading schema.sql."""

from pathlib import Path

from sqlalchemy import Engine, make_url, text

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})

# Drops only the public schema of the target database, then recreates it empty.
RESET_SQL = "DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"

TABLE_LIST_SQL = text(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
    "ORDER BY table_name"
)


def database_name(database_url: str) -> str:
    """Return the database name in the URL, refusing system databases."""
    name = make_url(database_url).database
    if not name:
        raise ValueError("DATABASE_URL does not name a database.")
    if name in PROTECTED_DATABASES:
        raise ValueError(f"Refusing to reset the system database '{name}'.")
    return name


def list_public_tables(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return [row[0] for row in connection.execute(TABLE_LIST_SQL)]


def reset_database(engine: Engine, schema_sql: str) -> None:
    """Drop and recreate the public schema, then load schema_sql, in one transaction."""
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(RESET_SQL)
        cursor.execute(schema_sql)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
