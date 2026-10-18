"""Board-editor uploads: post-owned files that never enter the org gallery.

Files are stored under the org folder (so an org hard delete removes them)
with owner_type post and owner_id = org id. Their rows skip media_by_owner,
so the gallery, public surfaces and member media list never show them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.ids import uuid7
from core.media import MediaStore
from core.media_rules import ATTACHMENT_ROLE, POST_OWNER, prepare_upload
from core.security import utcnow
from orgs.interfaces import MediaRepository, MemberRepository, OrgRepository
from posts.dtos import PostUploadSnapshot
from posts.guards import BoardGuard
from rbac.interfaces import AccessControl

if TYPE_CHECKING:
    from admin.interfaces import ModerationStore


class PostUploads:
    """Stages one board-editor file for a member of a live org."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        access: AccessControl,
        media: MediaRepository,
        store: MediaStore,
        max_image_bytes: int = 10 * 1024 * 1024,
        max_video_bytes: int = 100 * 1024 * 1024,
        moderation: "ModerationStore | None" = None,
    ) -> None:
        self._guard = BoardGuard(orgs, members, access)
        self._access = access
        self._media = media
        self._store = store
        self._max_image_bytes = max_image_bytes
        self._max_video_bytes = max_video_bytes
        self._moderation = moderation

    def upload(
        self,
        org_id: UUID,
        actor_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ) -> PostUploadSnapshot:
        self._guard.require_member(org_id, actor_id, "post.upload")
        prepared = prepare_upload(
            mime, content, self._max_image_bytes, self._max_video_bytes
        )
        asset_id = uuid7()
        relative = self._store.save_typed(
            org_id, asset_id, prepared.mime, filename, prepared.content
        )
        now = utcnow()
        self._media.create_asset(
            asset_id,
            org_id,
            relative,
            prepared.mime,
            len(prepared.content),
            now,
            ATTACHMENT_ROLE,
            file_hash=prepared.file_hash,
            uploader_id=actor_id,
            original_name=filename,
            owner_type=POST_OWNER,
            owner_feed=False,
        )
        if self._moderation is not None:
            self._moderation.enqueue(uuid7(), asset_id, now)
        self._access.record(
            org_id, actor_id, "post.upload", "post", asset_id, "allowed"
        )
        return PostUploadSnapshot(
            id=asset_id,
            org_id=org_id,
            kind=prepared.kind,
            mime=prepared.mime,
            size_bytes=len(prepared.content),
            file_url=f"/media/{relative}",
            original_name=filename,
        )
