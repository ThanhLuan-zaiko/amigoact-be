from connector.database import create_database_engine


def test_engine_uses_postgresql_dialect() -> None:
    engine = create_database_engine(
        "postgresql+psycopg://user:secret@localhost:5432/db"
    )

    assert engine.dialect.name == "postgresql"
    engine.dispose()
