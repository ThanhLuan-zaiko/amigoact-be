"""Shared media ownership rules: owner types, gallery membership, upload checks.

Every media_assets row names the bounded context that owns its file through
owner_type:

- ORG_OWNER: organization media. Only rows with a gallery, cover or logo role
  enter the org gallery feed (media_by_owner) and the public gallery.
- CHAT_OWNER: chat attachments, owner_id = room id. Never in the org feed.
- POST_OWNER: board-editor uploads, owner_id = org id. Never in the org feed.

Other owner types (activity, user, certificate) keep their own feeds. Each
feature stages its files through its own service, so gallery reads and
mutations go through is_gallery_asset() and never touch another context.

No FastAPI, no CQL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from core.exceptions import MediaTooLargeError, UnsupportedMediaError
from core.media import media_kind, normalize_image

ORG_OWNER = "organization"
CHAT_OWNER = "chat"
POST_OWNER = "post"
MEMBERSHIP_OWNER = "membership"
GALLERY_ROLES = ("gallery", "cover", "logo")
BRAND_ROLES = ("cover", "logo")
ATTACHMENT_ROLE = "attachment"


def asset_role(row: Any) -> str:
    return getattr(row, "role", None) or "gallery"


def asset_owner_type(row: Any) -> str:
    return getattr(row, "owner_type", None) or ORG_OWNER


def is_gallery_asset(row: Any, org_id: UUID) -> bool:
    return (
        row is not None
        and row.owner_id == org_id
        and asset_owner_type(row) == ORG_OWNER
        and asset_role(row) in GALLERY_ROLES
    )


@dataclass(frozen=True)
class PreparedUpload:
    """Validated, normalized bytes ready for storage."""

    kind: str
    mime: str
    content: bytes
    file_hash: str


def prepare_evidence_upload(mime: str, content: bytes, max_bytes: int) -> PreparedUpload:
    """Applicant evidence: one PDF or one image, never video."""
    clean = mime.split(";")[0].strip().lower()
    if clean == "application/pdf":
        if len(content) > max_bytes:
            raise MediaTooLargeError("File exceeds the size limit.")
        if not content.startswith(b"%PDF"):
            raise UnsupportedMediaError("File is not a valid PDF.")
        return PreparedUpload(
            kind="document",
            mime=clean,
            content=content,
            file_hash=hashlib.sha256(content).hexdigest(),
        )
    if media_kind(clean) != "image":
        raise UnsupportedMediaError("Only PDF or image files are allowed.")
    return prepare_upload(clean, content, max_bytes, max_bytes)


def prepare_upload(
    mime: str,
    content: bytes,
    max_image_bytes: int,
    max_video_bytes: int,
) -> PreparedUpload:
    kind = media_kind(mime)
    if kind is None:
        raise UnsupportedMediaError("Only images and videos are allowed.")
    limit = max_image_bytes if kind == "image" else max_video_bytes
    if len(content) > limit:
        raise MediaTooLargeError("File exceeds the size limit.")
    if kind == "image":
        try:
            mime, content = normalize_image(content, mime)
        except ValueError as exc:
            raise MediaTooLargeError("Image exceeds the pixel limit.") from exc
    return PreparedUpload(
        kind=kind,
        mime=mime,
        content=content,
        file_hash=hashlib.sha256(content).hexdigest(),
    )
