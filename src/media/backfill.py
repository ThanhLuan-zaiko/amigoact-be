"""Backfill: move files stored before the account tree into it, and add missing links.

Dry run by default. With apply=True the files are moved, the rows updated, and the
links created in one database transaction. If the commit fails, the moved files are
put back.
"""

import os
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.media import placement, storage
from src.models.activities import Activity
from src.models.auth import User
from src.models.media import MediaAsset
from src.models.organizations import Organization, OrganizationMedia

LEGACY_KEY = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp|mp4|webm)")


@dataclass
class Report:
    moved: int = 0
    linked: int = 0
    missing_file: int = 0
    skipped: int = 0


def _candidate_uses(db: Session) -> Iterator[tuple[uuid.UUID | None, tuple[str, ...]]]:
    for asset_id in db.scalars(select(User.avatar_media_id)):
        yield asset_id, ("avatar",)
    for org_id, logo, cover in db.execute(
        select(Organization.id, Organization.logo_media_id, Organization.cover_media_id)
    ):
        folder = ("organizations", str(org_id))
        yield logo, (*folder, "logo")
        yield cover, (*folder, "cover")
    for org_id, asset_id in db.execute(
        select(OrganizationMedia.org_id, OrganizationMedia.asset_id)
    ):
        yield asset_id, ("organizations", str(org_id), "gallery")
    for activity_id, asset_id in db.execute(
        select(Activity.id, Activity.cover_media_id)
    ):
        yield asset_id, ("activities", str(activity_id), "cover")


def _uses(db: Session) -> Iterator[tuple[uuid.UUID, tuple[str, ...]]]:
    """Every place a picture is used now, with the folders its link belongs in."""
    for asset_id, folders in _candidate_uses(db):
        if asset_id is not None:
            yield asset_id, folders


def _move_flat_files(
    db: Session, root: Path, apply: bool, report: Report
) -> list[tuple[Path, Path]]:
    """Move each flat file into its uploader's by-date folder. Returns the moves done."""
    moves: list[tuple[Path, Path]] = []
    assets = db.scalars(
        select(MediaAsset).where(
            MediaAsset.storage_key.is_not(None),
            MediaAsset.uploader_id.is_not(None),
        )
    ).all()
    for asset in assets:
        key = asset.storage_key or ""
        if LEGACY_KEY.fullmatch(key) is None:
            continue
        source = root / key
        if (
            not source.is_file()
            or asset.created_at is None
            or asset.uploader_id is None
        ):
            report.missing_file += 1
            continue
        extension = key.rsplit(".", 1)[1]
        new_key = storage.new_storage_key(
            asset.uploader_id,
            asset.asset_id,
            extension,
            asset.created_at.astimezone(UTC),
        )
        report.moved += 1
        if apply:
            target = storage.file_path(root, new_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            moves.append((source, target))
            asset.storage_key = new_key
    return moves


def run(db: Session, root: Path, apply: bool) -> Report:
    report = Report()
    moves = _move_flat_files(db, root, apply, report)
    for asset_id, folders in _uses(db):
        asset = db.get(MediaAsset, asset_id)
        if asset is None or asset.storage_key is None or asset.uploader_id is None:
            report.skipped += 1
            continue
        if not storage.file_path(root, asset.storage_key).is_file():
            report.missing_file += 1
            continue
        if placement.target_path(root, asset, folders).exists():
            continue
        report.linked += 1
        if apply:
            placement.link(db, root, asset_id, *folders)
    if not apply:
        db.rollback()
        return report
    try:
        db.commit()
    except Exception:
        db.rollback()
        for source, target in moves:
            os.replace(target, source)
        raise
    return report
