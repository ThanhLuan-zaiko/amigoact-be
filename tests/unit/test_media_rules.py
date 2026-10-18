"""Unit tests for core.media_rules: upload preparation and gallery membership."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from core.exceptions import MediaTooLargeError, UnsupportedMediaError
from core.ids import uuid7
from core.media_rules import is_gallery_asset, prepare_upload

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
MB = 1024 * 1024


def test_unsupported_mime_rejected() -> None:
    with pytest.raises(UnsupportedMediaError):
        prepare_upload("application/pdf", b"%PDF", 10 * MB, 100 * MB)


def test_oversize_image_rejected() -> None:
    with pytest.raises(MediaTooLargeError):
        prepare_upload("image/png", b"1" * (MB + 1), MB, 100 * MB)


def test_oversize_video_rejected() -> None:
    with pytest.raises(MediaTooLargeError):
        prepare_upload("video/mp4", b"1" * (MB + 1), 10 * MB, MB)


def test_web_safe_png_passes_through_with_hash() -> None:
    prepared = prepare_upload("image/png", PNG, 10 * MB, 100 * MB)
    assert prepared.kind == "image"
    assert prepared.mime == "image/png"
    assert prepared.content == PNG
    assert prepared.file_hash == hashlib.sha256(PNG).hexdigest()


def test_video_keeps_kind_and_mime() -> None:
    prepared = prepare_upload("video/mp4", b"1" * 16, 10 * MB, 100 * MB)
    assert prepared.kind == "video"
    assert prepared.mime == "video/mp4"


def _row(owner_id, owner_type="organization", role="gallery"):  # noqa: ANN001, ANN202
    return SimpleNamespace(
        asset_id=uuid7(), owner_id=owner_id, owner_type=owner_type, role=role
    )


@pytest.mark.parametrize("role", ["gallery", "cover", "logo"])
def test_org_gallery_roles_are_gallery_assets(role: str) -> None:
    org = uuid7()
    assert is_gallery_asset(_row(org, role=role), org)


@pytest.mark.parametrize("role", ["attachment", "avatar"])
def test_org_other_roles_are_not_gallery_assets(role: str) -> None:
    org = uuid7()
    assert not is_gallery_asset(_row(org, role=role), org)


@pytest.mark.parametrize("owner_type", ["chat", "post", "certificate"])
def test_other_owner_types_are_never_gallery_assets(owner_type: str) -> None:
    org = uuid7()
    assert not is_gallery_asset(
        _row(org, owner_type=owner_type, role="gallery"), org
    )


def test_other_org_is_not_gallery_asset() -> None:
    assert not is_gallery_asset(_row(uuid7()), uuid7())


def test_missing_row_is_not_gallery_asset() -> None:
    assert not is_gallery_asset(None, uuid7())
