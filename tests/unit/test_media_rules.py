from pathlib import Path

import pytest

from src.media.service import clean_filename
from src.media.sniff import JPEG, MAX_UPLOAD_BYTES, PNG, WEBP, detect_image
from src.media.storage import file_path, new_storage_key


def test_detects_each_supported_image_by_its_first_bytes() -> None:
    assert detect_image(b"\xff\xd8\xff\xe0rest") == JPEG
    assert detect_image(b"\x89PNG\r\n\x1a\nrest") == PNG
    assert detect_image(b"RIFF\x00\x00\x00\x00WEBPrest") == WEBP


def test_rejects_other_content_even_with_an_image_name() -> None:
    assert detect_image(b"hello, this is text") is None
    assert detect_image(b"GIF89a") is None
    assert detect_image(b"") is None


def test_riff_without_webp_is_not_an_image() -> None:
    assert detect_image(b"RIFF\x00\x00\x00\x00WAVEfmt ") is None


def test_upload_limit_is_five_megabytes() -> None:
    assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024


def test_generated_key_is_accepted_and_stays_in_the_root(tmp_path: Path) -> None:
    key = new_storage_key("png")
    assert file_path(tmp_path, key) == tmp_path / key


@pytest.mark.parametrize(
    "key",
    ["../secret.png", "photo.png", "a" * 32 + ".exe", "sub/" + "a" * 32 + ".png"],
)
def test_keys_outside_the_generated_shape_are_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        file_path(tmp_path, key)


def test_filename_loses_nul_and_control_characters() -> None:
    assert clean_filename("a\x00b\x1f.png") == "ab.png"


def test_filename_is_cut_to_the_column_size() -> None:
    cleaned = clean_filename("x" * 400)
    assert cleaned is not None
    assert len(cleaned) == 255


def test_missing_or_blank_filename_becomes_none() -> None:
    assert clean_filename(None) is None
    assert clean_filename("\x00  ") is None
