import pytest

from src.reset import admin_database_url, create_database_statement, database_name


def test_database_name_returns_the_name_in_the_url() -> None:
    assert (
        database_name("postgresql+psycopg://user:secret@localhost:5432/mydb") == "mydb"
    )


@pytest.mark.parametrize("name", ["postgres", "template0", "template1"])
def test_system_databases_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="system database"):
        database_name(f"postgresql+psycopg://user:secret@localhost:5432/{name}")


def test_url_without_a_database_name_is_refused() -> None:
    with pytest.raises(ValueError, match="does not name a database"):
        database_name("postgresql+psycopg://user:secret@localhost:5432")


def test_admin_url_points_at_the_maintenance_database() -> None:
    url = admin_database_url("postgresql+psycopg://user:secret@localhost:5432/mydb")
    assert url.database == "postgres"
    assert url.host == "localhost"
    assert url.port == 5432
    assert url.username == "user"


def test_create_statement_leaves_a_plain_name_unquoted() -> None:
    assert create_database_statement("amigoact") == "CREATE DATABASE amigoact"


def test_create_statement_quotes_names_that_need_it() -> None:
    assert create_database_statement("my-db") == 'CREATE DATABASE "my-db"'
    assert create_database_statement('a"b') == 'CREATE DATABASE "a""b"'
