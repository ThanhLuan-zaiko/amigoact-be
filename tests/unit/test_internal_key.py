from pathlib import Path

import pytest
from pydantic import ValidationError

from src.internal_key import HEADER, InternalKeySettings, header_value, key_matches

KEY = "k" * 40


def test_key_matches_only_the_exact_key() -> None:
    assert key_matches(KEY, KEY)
    assert not key_matches(KEY, KEY + "x")
    assert not key_matches(KEY, KEY[:-1])
    assert not key_matches(KEY, KEY.upper())


def test_missing_or_empty_key_never_matches() -> None:
    assert not key_matches(KEY, None)
    assert not key_matches(KEY, "")


def test_non_ascii_key_does_not_crash() -> None:
    assert not key_matches(KEY, chr(233) * 40)


def test_header_value_reads_the_lowercase_header() -> None:
    scope = {"headers": [(b"accept", b"*/*"), (HEADER.encode(), KEY.encode())]}
    assert header_value(scope) == KEY


def test_header_value_is_none_without_the_header() -> None:
    assert header_value({"headers": [(b"accept", b"*/*")]}) is None
    assert header_value({}) is None


def test_settings_read_the_key_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"INTERNAL_API_KEY={KEY}\n", encoding="utf-8")
    settings = InternalKeySettings(_env_file=env_file)  # type: ignore[call-arg]
    assert settings.internal_api_key == KEY


@pytest.mark.parametrize("line", ["", "INTERNAL_API_KEY=short\n"])
def test_settings_refuse_a_missing_or_short_key(tmp_path: Path, line: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(line, encoding="utf-8")
    with pytest.raises(ValidationError):
        InternalKeySettings(_env_file=env_file)  # type: ignore[call-arg]
