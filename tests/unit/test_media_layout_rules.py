import os
import uuid
from pathlib import Path

from src.media.layout_migration import LEGACY_KEY, Report, count_links, remove_links


def identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino)


def test_legacy_keys_are_recognised_and_flat_keys_are_not() -> None:
    owner = uuid.uuid7()
    asset = uuid.uuid7()

    assert LEGACY_KEY.fullmatch(f"users/{owner}/by-date/2026/11/03/{asset}.png")
    assert LEGACY_KEY.fullmatch(f"{asset.hex}.png")
    assert LEGACY_KEY.fullmatch(f"{asset}.png") is None


def test_remove_links_deletes_only_links_to_moved_files(tmp_path: Path) -> None:
    stored = tmp_path / f"{uuid.uuid7()}.png"
    stored.write_bytes(b"x")
    link = tmp_path / "users" / "u" / "avatar" / "a.png"
    link.parent.mkdir(parents=True)
    os.link(stored, link)
    copy = tmp_path / "users" / "u" / "copy.png"
    copy.write_bytes(b"x")
    report = Report()

    remove_links(tmp_path, {identity(stored)}, set(), report)

    assert not link.exists()
    assert copy.exists()
    assert report.links_removed == 1
    assert [path.name for path in report.leftover_files] == ["copy.png"]
    assert not (tmp_path / "users" / "u" / "avatar").exists()


def test_count_links_changes_nothing(tmp_path: Path) -> None:
    stored = tmp_path / f"{uuid.uuid7()}.png"
    stored.write_bytes(b"x")
    link = tmp_path / "users" / "u" / "a.png"
    link.parent.mkdir(parents=True)
    os.link(stored, link)
    report = Report()

    count_links(tmp_path, {identity(stored)}, set(), report)

    assert link.exists()
    assert report.links_removed == 1
    assert report.leftover_files == []
