from connector.config import get_settings
from connector.database import check_connection, create_database_engine


def test_database_accepts_connection_from_env_file() -> None:
    engine = create_database_engine(get_settings().database_url)
    try:
        check_connection(engine)
    finally:
        engine.dispose()
