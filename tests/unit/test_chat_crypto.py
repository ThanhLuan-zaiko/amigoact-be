import base64
import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.chat.crypto import PREFIX, CipherError, open_text, seal
from src.config import ChatSettings


def test_sealed_text_opens_for_the_same_row() -> None:
    row = uuid.uuid7()

    token = seal("Xin chao \u0111\u1ea5y", row)

    assert open_text(token, row) == "Xin chao \u0111\u1ea5y"


def test_sealed_text_never_shows_the_plain_text() -> None:
    token = seal("bi mat rat nhieu", uuid.uuid7())

    assert token.startswith(PREFIX)
    assert "bi mat" not in token


def test_each_seal_uses_a_fresh_nonce() -> None:
    row = uuid.uuid7()

    assert seal("giong nhau", row) != seal("giong nhau", row)


def test_a_ciphertext_does_not_open_for_another_row() -> None:
    token = seal("rieng cho mot tin", uuid.uuid7())

    with pytest.raises(CipherError):
        open_text(token, uuid.uuid7())


def test_a_changed_ciphertext_is_rejected() -> None:
    row = uuid.uuid7()
    raw = bytearray(base64.b64decode(seal("nguyen ven", row)[len(PREFIX) :]))
    raw[-1] ^= 0x01
    tampered = PREFIX + base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(CipherError):
        open_text(tampered, row)


@pytest.mark.parametrize("token", ["plain text", "v1gcm:not base64!!", "v2gcm:xx"])
def test_text_without_a_valid_format_is_rejected(token: str) -> None:
    with pytest.raises(CipherError):
        open_text(token, uuid.uuid7())


def test_settings_need_a_key_that_is_base64_of_32_bytes(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    env_file.write_text("OTHER=1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        ChatSettings(_env_file=env_file)

    env_file.write_text(
        "CHAT_ENCRYPTION_KEY=" + base64.b64encode(os.urandom(16)).decode() + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        ChatSettings(_env_file=env_file)

    env_file.write_text("CHAT_ENCRYPTION_KEY=not-base64-at-all!!\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        ChatSettings(_env_file=env_file)

    key = base64.b64encode(os.urandom(32)).decode()
    env_file.write_text(f"CHAT_ENCRYPTION_KEY={key}\n", encoding="utf-8")
    assert ChatSettings(_env_file=env_file).chat_encryption_key == key
