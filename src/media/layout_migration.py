"""Move files from the account tree, or from older names, into the flat media root.

Every stored file becomes <media_root>/<asset_id>.<ext>, and its row gets the same
storage_key. Hard links that the account tree kept are removed once their file has moved,
and folders left empty are removed too. Files there that are not such links are reported,
not touched.

Dry run by default. Run it with the application stopped, because the moves and the row
updates must not race with an upload. The moves and the row updates share one database
transaction. If the commit fails, the moved files are put back.
"""

import os
import re
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.media import storage
from src.models.media import MediaAsset

# Keys written before the flat layout: the account tree, or a bare 32-hex name.
LEGACY_KEY = re.compile(
    r"(users/[0-9a-f-]{36}/by-date/[0-9]{4}/[0-9]{2}/[0-9]{2}/[0-9a-f-]{36}|[0-9a-f]{32})"
    r"\.(jpg|png|webp|mp4|webm)"
)
ACCOUNT_TREE = "users"


@dataclass
class Move:
    asset_id: uuid.UUID
    source: Path
    target: Path
    new_key: str
    # (device, inode) of the stored file. Hard links in the account tree share it.
    identity: tuple[int, int]


@dataclass
class Report:
    moved: int = 0
    already_flat: int = 0
    missing_file: int = 0
    conflicts: int = 0
    skipped: int = 0
    links_removed: int = 0
    leftover_files: list[Path] = field(default_factory=list)


def _identity(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino)


def plan_moves(db: Session, root: Path, report: Report) -> list[Move]:
    """Read-only. Decide where each legacy file goes, and count what cannot move."""
    moves: list[Move] = []
    targets: set[Path] = set()
    assets = db.scalars(
        select(MediaAsset).where(MediaAsset.storage_key.is_not(None))
    ).all()
    for asset in assets:
        key = asset.storage_key or ""
        if storage.STORAGE_KEY.fullmatch(key) is not None:
            report.already_flat += 1
            continue
        if LEGACY_KEY.fullmatch(key) is None:
            report.skipped += 1
            continue
        source = root / key
        if not source.is_file():
            report.missing_file += 1
            continue
        extension = key.rsplit(".", 1)[1]
        new_key = storage.new_storage_key(asset.asset_id, extension)
        target = root / new_key
        if target.exists() or target in targets:
            report.conflicts += 1
            continue
        targets.add(target)
        moves.append(Move(asset.asset_id, source, target, new_key, _identity(source)))
    return moves


def _account_tree_files(root: Path) -> list[Path]:
    tree = root / ACCOUNT_TREE
    if not tree.is_dir():
        return []
    return [path for path in tree.rglob("*") if path.is_file()]


def remove_links(
    root: Path,
    identities: set[tuple[int, int]],
    sources: set[Path],
    report: Report,
) -> None:
    """Delete the account tree's hard links to moved files, then the empty folders."""
    for path in _account_tree_files(root):
        if path in sources:
            continue
        if _identity(path) in identities:
            path.unlink()
            report.links_removed += 1
        else:
            report.leftover_files.append(path)
    tree = root / ACCOUNT_TREE
    if not tree.is_dir():
        return
    folders = sorted(
        (path for path in tree.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for folder in [*folders, tree]:
        with suppress(OSError):
            folder.rmdir()


def count_links(
    root: Path,
    identities: set[tuple[int, int]],
    sources: set[Path],
    report: Report,
) -> None:
    """The dry-run twin of remove_links: counts only, changes nothing."""
    for path in _account_tree_files(root):
        if path in sources:
            continue
        if _identity(path) in identities:
            report.links_removed += 1
        else:
            report.leftover_files.append(path)


def apply_moves(db: Session, moves: list[Move], report: Report) -> None:
    """Move the files and update their rows in one transaction, then drop the links."""
    done: list[Move] = []
    try:
        for move in moves:
            os.replace(move.source, move.target)
            done.append(move)
            asset = db.get(MediaAsset, move.asset_id)
            if asset is not None:
                asset.storage_key = move.new_key
        db.commit()
    except Exception:
        db.rollback()
        for move in reversed(done):
            os.replace(move.target, move.source)
        raise
    report.moved = len(done)


def run(db: Session, root: Path, apply: bool) -> Report:
    report = Report()
    moves = plan_moves(db, root, report)
    identities = {move.identity for move in moves}
    # The stored copies that are about to move are not links, so they are never counted.
    sources = {move.source for move in moves}
    if not apply:
        report.moved = len(moves)
        count_links(root, identities, sources, report)
        return report
    apply_moves(db, moves, report)
    remove_links(root, identities, sources, report)
    return report
