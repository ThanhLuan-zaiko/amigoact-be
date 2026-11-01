from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_ignore_os_environment_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression guard: DATABASE_URL must come only from .env, never from OS variables.
    monkeypatch.chdir(tmp_path)  # no .env file in this directory
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:secret@localhost:5432/db"
    )

    with pytest.raises(ValidationError):
        Settings()
