from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_read_database_url_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+psycopg://user:secret@localhost:5432/db\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url == "postgresql+psycopg://user:secret@localhost:5432/db"


def test_settings_fail_when_env_file_has_no_database_url(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_VALUE=1\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)
