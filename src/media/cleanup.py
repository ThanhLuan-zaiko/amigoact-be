"""Remove uploaded files that nothing uses any more, and the folders left empty.

A file is in use when a foreign key points at its asset (see usage.py). A new upload
is kept for a grace period, because it is stored before it is attached. Nothing is
written unless apply_plan runs.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.media import storage
from src.media.service import ACTIVE
from src.media.usage import referenced_asset_ids
from src.models.media import MediaAsset

DELETED = "deleted"
# A stored file is named <asset_id>.<extension>. Anything else in the tree is ignored.
MEDIA_FILE = re.compile(r"([0-9a-f-]{36})\.(?:jpg|png|webp|mp4|webm)")


@dataclass
class Plan:
    """What a run changes. It is complete before the first write."""

    assets: list[uuid.UUID] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    folders: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def cutoff_for(now: datetime, min_age_days: int) -> datetime:
    return now - timedelta(days=min_age_days)


def file_asset_id(name: str) -> uuid.UUID | None:
    match = MEDIA_FILE.fullmatch(name)
    if match is None:
        return None
    try:
        return uuid.UUID(match.group(1))
    except ValueError:
        return None


def should_remove(
    asset_id: uuid.UUID,
    modified_at: datetime,
    cutoff: datetime,
    expired: set[uuid.UUID],
    active: set[uuid.UUID],
) -> bool:
    """Expired assets always go. Active assets stay. Other files go after the grace period.

    Other files are rows already marked deleted, and files with no row at all.
    """
    if asset_id in expired:
        return True
    if asset_id in active:
        return False
    return modified_at < cutoff


def empty_folders(base: Path, doomed: set[Path]) -> list[Path]:
    """Folders under base that are empty once the doomed files are gone, deepest first."""
    if not base.is_dir():
        return []
    gone = set(doomed)
    removable: list[Path] = []
    folders = sorted(
        (path for path in base.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for folder in folders:
        if all(child in gone for child in folder.iterdir()):
            gone.add(folder)
            removable.append(folder)
    return removable


def media_files(base: Path) -> Iterator[tuple[uuid.UUID, Path]]:
    if not base.is_dir():
        return
    for path in base.rglob("*"):
        asset_id = file_asset_id(path.name)
        if asset_id is not None and path.is_file():
            yield asset_id, path


def modified_at(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def expired_assets(
    db: Session,
    cutoff: datetime,
    uploader_id: uuid.UUID | None,
    in_use: set[uuid.UUID],
) -> list[uuid.UUID]:
    """Active uploads that are older than the cutoff and that nothing points at."""
    query = select(MediaAsset.asset_id).where(
        MediaAsset.upload_status == ACTIVE, MediaAsset.created_at < cutoff
    )
    if uploader_id is not None:
        query = query.where(MediaAsset.uploader_id == uploader_id)
    return [asset_id for asset_id in db.scalars(query) if asset_id not in in_use]


def plan_cleanup(
    db: Session, root: Path, cutoff: datetime, uploader_id: uuid.UUID | None
) -> Plan:
    """Read-only. Scope to one uploader by passing uploader_id, or cover every account."""
    expired = set(expired_assets(db, cutoff, uploader_id, referenced_asset_ids(db)))
    active = set(
        db.scalars(
            select(MediaAsset.asset_id).where(MediaAsset.upload_status == ACTIVE)
        )
    )
    base = (
        root / "users" if uploader_id is None else storage.user_dir(root, uploader_id)
    )
    files = [
        path
        for asset_id, path in media_files(base)
        if should_remove(asset_id, modified_at(path), cutoff, expired, active)
    ]
    return Plan(
        assets=sorted(expired),
        files=files,
        folders=empty_folders(base, set(files)),
    )


def still_unused(db: Session, asset_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Lock the rows, then check again that nothing points at them.

    The plan may be older than the lock. An upload attached since then is kept. Attaching
    locks the same row (see media.service), so the check cannot race with an attach.
    """
    if not asset_ids:
        return []
    locked = db.scalars(
        select(MediaAsset.asset_id)
        .where(MediaAsset.asset_id.in_(asset_ids), MediaAsset.upload_status == ACTIVE)
        .order_by(MediaAsset.asset_id)
        .with_for_update()
    ).all()
    in_use = referenced_asset_ids(db)
    return [asset_id for asset_id in locked if asset_id not in in_use]


def apply_plan(db: Session, plan: Plan, now: datetime) -> None:
    """Lock and re-check the expired rows, mark them, commit, then delete the files.

    A file that cannot be deleted is reported and left for the next run. Its row is
    already marked deleted, so the next run removes the file as well.
    """
    expired = still_unused(db, plan.assets)
    kept = set(plan.assets) - set(expired)
    plan.assets = expired
    plan.files = [path for path in plan.files if file_asset_id(path.name) not in kept]
    if expired:
        db.execute(
            update(MediaAsset)
            .where(MediaAsset.asset_id.in_(expired))
            .values(upload_status=DELETED, deleted_at=now, file_hash=None)
        )
    db.commit()
    for path in plan.files:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            plan.errors.append(f"{path}: {error}")
    for folder in plan.folders:
        with suppress(OSError):
            folder.rmdir()


def run(
    db: Session,
    root: Path,
    *,
    now: datetime,
    min_age_days: int,
    uploader_id: uuid.UUID | None = None,
    apply: bool = False,
) -> Plan:
    plan = plan_cleanup(db, root, cutoff_for(now, min_age_days), uploader_id)
    if apply:
        apply_plan(db, plan, now)
    return plan
