"""Unit tests for LocalMediaStore (tmp dir, no I/O outside it)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import uuid_utils

from core.media import LocalMediaStore, extension_for, media_kind


def _uid() -> UUID:
    return UUID(str(uuid_utils.uuid7()))


def test_kind_and_extension_mapping() -> None:
    assert media_kind("image/jpeg") == "image"
    assert media_kind("video/mp4; charset=binary") == "video"
    assert media_kind("application/pdf") is None
    assert extension_for("image/jpeg", "photo.jpeg") == ".jpg"
    assert extension_for("video/mp4", "clip.MP4") == ".mp4"
    assert extension_for("application/pdf", "doc.pdf") is None


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
