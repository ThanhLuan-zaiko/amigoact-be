"""Unit tests for LocalMediaStore (tmp dir, no I/O outside it)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import uuid_utils

from core.media import LocalMediaStore, extension_for, media_kind, normalize_image


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


def test_kind_and_extension_mapping() -> None:
    assert media_kind("image/jpeg") == "image"
    assert media_kind("video/mp4; charset=binary") == "video"
    # Documents (generated certificate PDFs) are saveable via save_typed
    # but never classified as image/video, so uploads stay gated.
    assert media_kind("application/pdf") is None
    assert extension_for("image/jpeg", "photo.jpeg") == ".jpg"
    assert extension_for("video/mp4", "clip.MP4") == ".mp4"
    assert extension_for("application/pdf", "doc.pdf") == ".pdf"


def test_save_resolve_delete_roundtrip(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "media")
    org, asset = _uid(), _uid()
    relative = store.save_typed(org, asset, "image/png", "pic.png", b"12345")
    assert relative == f"orgs/{org}/{asset}.png"
    absolute = store.resolve(relative)
    assert absolute.read_bytes() == b"12345"
    assert store.delete_file(relative) is True
    assert store.delete_file(relative) is False


def test_org_layout_and_orphan_sweep(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "media")
    alive, gone = _uid(), _uid()
    store.save_typed(alive, _uid(), "image/jpeg", "a.jpg", b"a")
    store.save_typed(gone, _uid(), "video/mp4", "b.mp4", b"b")
    assert store.delete_org_dir(alive) is True
    assert store.delete_org_dir(alive) is False
    assert store.sweep_orphans({str(alive)}) == 1
    assert store.sweep_orphans({str(alive)}) == 0


def test_resolve_rejects_escape(tmp_path: Path) -> None:
    store = LocalMediaStore(tmp_path / "media")
    with pytest.raises(ValueError):
        store.resolve("../outside.txt")
    with pytest.raises(ValueError):
        store.resolve("orgs/../../evil.txt")


def _encode(fmt: str, mode: str = "RGB") -> bytes:
    from io import BytesIO

    from PIL import Image

    if fmt == "HEIF":
        import pillow_heif

        pillow_heif.register_heif_opener()
    buf = BytesIO()
    Image.new(mode, (8, 8), (200, 30, 30, 128) if "A" in mode else (200, 30, 30)).save(
        buf, format=fmt
    )
    return buf.getvalue()


def test_normalize_image_passthrough_and_transcode() -> None:
    jpeg = _encode("JPEG")
    assert normalize_image(jpeg, "image/jpeg") == ("image/jpeg", jpeg)

    mime, out = normalize_image(_encode("TIFF"), "image/tiff")
    assert mime == "image/jpeg"
    assert out.startswith(b"\xff\xd8")

    mime, out = normalize_image(_encode("TIFF", "RGBA"), "image/tiff")
    assert mime == "image/png"
    assert out.startswith(b"\x89PNG")


def test_normalize_image_heic_and_undecodable() -> None:
    mime, out = normalize_image(_encode("HEIF"), "image/heic")
    assert mime == "image/jpeg"
    assert out.startswith(b"\xff\xd8")

    junk = b"not-an-image"
    assert normalize_image(junk, "image/heic") == ("image/heic", junk)
