"""Pictures and videos sent in a room, and who may read them back.

A file is uploaded with POST /media first and stays private. Sending it records a claim
(one message per file) and an org_room_media row (its place in the album). The file
stays private on the media table: people read it because they can enter the room.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.chat.rooms import Room, readable_by
from src.chat.schemas import AttachmentResponse
from src.media import service as media_service
from src.media.sniff import is_video
from src.models.chat import ChatAttachmentClaim, OrgRoomMedia, OrgRoomMessage
from src.models.media import MediaAsset
from src.validation import validation_failure

IMAGE = "image"
VIDEO = "video"


def kind_of(mime: str | None) -> str:
    return VIDEO if is_video(mime) else IMAGE


def link_attachments(
    db: Session,
    room: Room,
    message: OrgRoomMessage,
    user_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
) -> None:
    """Only the uploader sends a file, and a file goes into one message only.

    The asset rows are locked until the caller commits, so the cleanup cannot remove a
    file between this check and the commit.
    """
    for index, asset_id in enumerate(asset_ids):
        asset = media_service.owned_asset(db, asset_id, user_id, allow_video=True)
        if db.get(ChatAttachmentClaim, asset_id) is not None:
            raise validation_failure({"attachment_ids": "attachment_in_use"})
        db.add(
            ChatAttachmentClaim(
                media_id=asset_id,
                room_id=room.room_id,
                message_id=message.message_id,
            )
        )
        db.add(
            OrgRoomMedia(
                message_id=message.message_id,
                item_index=index,
                room_id=room.room_id,
                kind=kind_of(asset.mime),
                author_id=user_id,
                media_id=asset_id,
                mime=asset.mime,
                name=asset.original_name,
                size_bytes=asset.size_bytes,
            )
        )


def has_attachments(db: Session, message_id: uuid.UUID) -> bool:
    row = db.scalar(
        select(OrgRoomMedia.item_index)
        .where(OrgRoomMedia.message_id == message_id)
        .limit(1)
    )
    return row is not None


def attachments_for(
    db: Session, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[AttachmentResponse]]:
    """Every file of these messages, in album order. A removed file is left out."""
    found: dict[uuid.UUID, list[AttachmentResponse]] = defaultdict(list)
    if not message_ids:
        return found
    rows = db.execute(
        select(OrgRoomMedia, MediaAsset.upload_status)
        .join(MediaAsset, MediaAsset.asset_id == OrgRoomMedia.media_id)
        .where(OrgRoomMedia.message_id.in_(message_ids))
        .order_by(OrgRoomMedia.message_id, OrgRoomMedia.item_index)
    ).all()
    for item, upload_status in rows:
        if item.media_id is None or upload_status != media_service.ACTIVE:
            continue
        found[item.message_id].append(
            AttachmentResponse(
                id=item.media_id,
                url=f"/media/{item.media_id}/file",
                kind=item.kind,
                mime=item.mime or "application/octet-stream",
                size_bytes=item.size_bytes or 0,
                name=item.name,
            )
        )
    return found


def can_view(db: Session, asset: MediaAsset, viewer_id: uuid.UUID | None) -> bool:
    """A sent file opens for everyone who can enter its room, and for nobody else.

    A claim without a message is a staged upload, which stays with its uploader.
    """
    if viewer_id is None:
        return False
    claim = db.get(ChatAttachmentClaim, asset.asset_id)
    if claim is None or claim.message_id is None:
        return False
    return readable_by(db, claim.room_id, viewer_id)
