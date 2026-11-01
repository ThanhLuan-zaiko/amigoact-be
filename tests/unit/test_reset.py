import pytest

from connector.reset import database_name


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
