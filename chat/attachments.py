"""Chat-owned files: stage uploads, resolve them for a message, discard them.

Chat attachments are media_assets rows with owner_type chat and owner_id = the
room id. Bytes sit under the org folder so an org hard delete still removes
them, but the rows never enter media_by_owner, so the org gallery never lists
them. A staged id is meant for one message from the same uploader in the same
room; deleting that message deletes its files.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING
from uuid import UUID

from chat.dtos import AttachmentBrief
from chat.interfaces import AttachmentClaimStore
from core.exceptions import ForbiddenError, NotFoundError
from core.ids import uuid7
from core.media import MediaStore
from core.media_rules import (
    ATTACHMENT_ROLE,
    CHAT_OWNER,
    asset_owner_type,
    prepare_upload,
)
from core.security import utcnow
from orgs.interfaces import MediaRepository

if TYPE_CHECKING:
    from admin.interfaces import ModerationStore


class ChatAttachments:
    """Owns the files chat messages carry; nothing else writes them."""

    def __init__(
        self,
        media: MediaRepository,
        store: MediaStore,
        claims: AttachmentClaimStore,
        max_image_bytes: int = 10 * 1024 * 1024,
        max_video_bytes: int = 100 * 1024 * 1024,
        moderation: "ModerationStore | None" = None,
    ) -> None:
        self._media = media
        self._store = store
        self._claims = claims
        self._max_image_bytes = max_image_bytes
        self._max_video_bytes = max_video_bytes
        self._moderation = moderation

    def stage(
        self,
        org_id: UUID,
        room_id: UUID,
        actor_id: UUID,
        filename: str,
        mime: str,
        content: bytes,
    ) -> AttachmentBrief:
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
            room_id,
            relative,
            prepared.mime,
            len(prepared.content),
            now,
            ATTACHMENT_ROLE,
            file_hash=prepared.file_hash,
            uploader_id=actor_id,
            original_name=filename,
            owner_type=CHAT_OWNER,
            owner_feed=False,
        )
        if self._moderation is not None:
            self._moderation.enqueue(uuid7(), asset_id, now)
        return AttachmentBrief(
            media_id=asset_id,
            url=f"/media/{relative}",
            mime=prepared.mime,
            name=filename,
            size_bytes=len(prepared.content),
        )

    def resolve(
        self,
        room_id: UUID,
        actor_id: UUID,
        attachment_ids: Iterable[UUID],
        message_id: UUID,
    ) -> list[AttachmentBrief]:
        """Each id must be a chat file the same actor staged in this room.

        Every validated id is then claimed for `message_id` (LWT): one
        file attaches to exactly one message, so a delete can never wipe
        bytes another message still renders.
        """
        out: list[AttachmentBrief] = []
        claimed: list[UUID] = []
        now = utcnow()
        try:
            for media_id in dict.fromkeys(attachment_ids):
                asset = self._media.get_asset(media_id)
                if asset is None:
                    raise NotFoundError("Attachment not found.")
                if (
                    asset_owner_type(asset) != CHAT_OWNER
                    or asset.owner_id != room_id
                    or asset.uploader_id != actor_id
                ):
                    raise ForbiddenError("Attachment does not belong here.")
                if not self._claims.claim_attachment(
                    media_id, room_id, message_id, now
                ):
                    raise ForbiddenError("Attachment was already sent.")
                claimed.append(media_id)
                out.append(
                    AttachmentBrief(
                        media_id=media_id,
                        url=f"/media/{asset.file_url}",
                        mime=asset.mime,
                        name=asset.original_name or "file",
                        size_bytes=int(asset.size_bytes or 0),
                    )
                )
        except Exception:
            for media_id in claimed:
                self._claims.release_attachment(media_id)
            raise
        return out

    def release_claims(self, attachments: Iterable[AttachmentBrief]) -> None:
        """Best-effort rollback when the message write fails after claims."""
        for item in attachments:
            try:
                self._claims.release_attachment(item.media_id)
            except Exception:  # noqa: BLE001 - rollback is best-effort
                pass

    def discard_staged(
        self, room_id: UUID, actor_id: UUID, media_id: UUID
    ) -> None:
        """Uploader drops one staged chip: deletes the file and its row.

        A claimed id is never touched: it belongs to a sent message and
        only the message delete path may remove it.
        """
        asset = self._media.get_asset(media_id)
        if asset is None:
            raise NotFoundError("Attachment not found.")
        if (
            asset_owner_type(asset) != CHAT_OWNER
            or asset.owner_id != room_id
            or asset.uploader_id != actor_id
        ):
            raise ForbiddenError("Attachment does not belong here.")
        if self._claims.claimed_attachment(media_id) is not None:
            raise ForbiddenError("Attachment was already sent.")
        self._media.delete_asset(media_id)
        try:
            self._store.delete_file(asset.file_url)
        except Exception:  # noqa: BLE001 - byte cleanup is best-effort
            pass

    def discard(
        self, room_id: UUID, attachments: Iterable[AttachmentBrief]
    ) -> int:
        """Drop metadata and bytes of this room's chat files; returns count."""
        removed = 0
        for item in attachments:
            asset = self._media.get_asset(item.media_id)
            if (
                asset is None
                or asset_owner_type(asset) != CHAT_OWNER
                or asset.owner_id != room_id
            ):
                continue
            self._media.delete_asset(item.media_id)
            self._claims.release_attachment(item.media_id)
            try:
                self._store.delete_file(asset.file_url)
            except Exception:  # noqa: BLE001 - byte cleanup is best-effort
                pass
            removed += 1
        return removed
