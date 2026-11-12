from pathlib import Path

import pytest
from pydantic import ValidationError

from src.cors import CorsSettings, origin_allowed, parse_origins


def test_parse_origins_splits_and_trims() -> None:
    text = " http://localhost:3000 , https://amigoact.example ,"
    assert parse_origins(text) == ["http://localhost:3000", "https://amigoact.example"]


def test_empty_value_allows_nothing() -> None:
    assert parse_origins("") == []
    assert parse_origins(" , ") == []


@pytest.mark.parametrize(
    "bad",
    [
        "*",
        "https://*.example.com",
        "http://localhost:3000/",
        "https://amigoact.example/path",
        "ftp://amigoact.example",
        "amigoact.example",
        "javascript:alert(1)",
    ],
)
def test_parse_origins_refuses_bad_entries(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_origins(bad)


def test_settings_read_origins_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORS_ORIGINS=http://localhost:3000,https://a.example\n", encoding="utf-8"
    )
    settings = CorsSettings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.origins == ["http://localhost:3000", "https://a.example"]


def test_settings_default_to_no_origin(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    assert CorsSettings(_env_file=env_file).origins == []  # type: ignore[call-arg]


def test_settings_refuse_a_wildcard(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CORS_ORIGINS=*\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        CorsSettings(_env_file=env_file)  # type: ignore[call-arg]


def test_origin_allowed() -> None:
    allowed = ["http://localhost:3000"]
    assert origin_allowed("http://localhost:3000", allowed)
    assert origin_allowed(None, allowed)
    assert not origin_allowed("http://evil.test", allowed)
    assert not origin_allowed("http://localhost:3000", [])
