"""Evidence files applicants attach to a membership application.

A file is staged by one applicant for one org (owner_type membership,
owner_id = org id, uploader = applicant). Applying references it by media id;
only that org's reviewers can read it back, through an authenticated route.
The files never enter the public /media folder or any org feed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from core.exceptions import NotFoundError
from core.ids import uuid7
from core.media import MediaStore
from core.media_rules import (
    ATTACHMENT_ROLE,
    MEMBERSHIP_OWNER,
    asset_owner_type,
    prepare_evidence_upload,
)
from core.security import utcnow
from orgs.interfaces import MediaRepository

MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class EvidenceFile:
    """What a reviewer or applicant needs to show one staged file."""

    media_id: UUID
    name: str
    mime: str
    size_bytes: int


def is_attached(asset: Any, org_id: UUID, user_id: UUID) -> bool:
    """True when the asset is an evidence file this applicant staged for this org."""
    return (
        asset is not None
        and asset_owner_type(asset) == MEMBERSHIP_OWNER
        and asset.owner_id == org_id
        and asset.uploader_id == user_id
    )


def as_evidence(asset: Any) -> EvidenceFile:
    return EvidenceFile(
        media_id=asset.asset_id,
        name=asset.original_name or "file",
        mime=asset.mime,
        size_bytes=int(asset.size_bytes or 0),
    )


class MembershipFiles:
    """Stages applicant uploads and opens them for reviewers."""

    def __init__(
        self,
        media: MediaRepository,
        store: MediaStore,
        max_bytes: int = MAX_EVIDENCE_BYTES,
    ) -> None:
        self._media = media
        self._store = store
        self._max_bytes = max_bytes

    def stage(
        self,
        org_id: UUID,
        actor_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ) -> EvidenceFile:
        prepared = prepare_evidence_upload(mime, content, self._max_bytes)
        asset_id = uuid7()
        relative = self._store.save_typed(
            org_id, asset_id, prepared.mime, filename, prepared.content
        )
        self._media.create_asset(
            asset_id,
            org_id,
            relative,
            prepared.mime,
            len(prepared.content),
            utcnow(),
            ATTACHMENT_ROLE,
            file_hash=prepared.file_hash,
            uploader_id=actor_id,
            original_name=filename,
            owner_type=MEMBERSHIP_OWNER,
            owner_feed=False,
        )
        return EvidenceFile(
            media_id=asset_id,
            name=filename,
            mime=prepared.mime,
            size_bytes=len(prepared.content),
        )

    def describe(self, org_id: UUID, media_id: UUID) -> EvidenceFile | None:
        """Metadata of one of this org's evidence files, None when unknown."""
        asset = self._media.get_asset(media_id)
        if (
            asset is None
            or asset_owner_type(asset) != MEMBERSHIP_OWNER
            or asset.owner_id != org_id
        ):
            return None
        return as_evidence(asset)

    def open(self, org_id: UUID, media_id: UUID) -> tuple[EvidenceFile, Path]:
        """Metadata plus the on-disk path; only files of this org resolve."""
        asset = self._media.get_asset(media_id)
        if (
            asset is None
            or asset_owner_type(asset) != MEMBERSHIP_OWNER
            or asset.owner_id != org_id
        ):
            raise NotFoundError("File not found.")
        try:
            path = self._store.resolve(asset.file_url)
        except ValueError as exc:
            raise NotFoundError("File not found.") from exc
        if not path.is_file():
            raise NotFoundError("File not found.")
        return as_evidence(asset), path
