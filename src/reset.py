"""Reset the database named in DATABASE_URL by reloading schema.sql."""

from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.dialects import postgresql

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1"})
ADMIN_DATABASE = "postgres"

# Drops only the public schema of the target database, then recreates it empty.
RESET_SQL = "DROP SCHEMA public CASCADE;\nCREATE SCHEMA public;\n"

TABLE_LIST_SQL = text(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
    "ORDER BY table_name"
)

DATABASE_EXISTS_SQL = text("SELECT 1 FROM pg_database WHERE datname = :name")


def database_name(database_url: str) -> str:
    """Return the database name in the URL, refusing system databases."""
    name = make_url(database_url).database
    if not name:
        raise ValueError("DATABASE_URL does not name a database.")
    if name in PROTECTED_DATABASES:
        raise ValueError(f"Refusing to reset the system database '{name}'.")
    return name


def admin_database_url(database_url: str) -> URL:
    """Return the same connection URL pointed at the maintenance database."""
    return make_url(database_url).set(database=ADMIN_DATABASE)


def create_database_statement(name: str) -> str:
    """Return CREATE DATABASE with the name quoted as a PostgreSQL identifier."""
    quoted = postgresql.dialect().identifier_preparer.quote(name)
    return f"CREATE DATABASE {quoted}"


def database_exists(database_url: str) -> bool:
    """Return True if the server already has the database named in the URL."""
    name = database_name(database_url)
    engine = create_engine(admin_database_url(database_url))
    try:
        with engine.connect() as connection:
            row = connection.execute(DATABASE_EXISTS_SQL, {"name": name}).first()
    finally:
        engine.dispose()
    return row is not None


def create_database(database_url: str) -> None:
    """Create the database named in the URL. Does nothing if it already exists."""
    name = database_name(database_url)
    engine = create_engine(
        admin_database_url(database_url), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            row = connection.execute(DATABASE_EXISTS_SQL, {"name": name}).first()
            if row is None:
                connection.exec_driver_sql(create_database_statement(name))
    finally:
        engine.dispose()


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
