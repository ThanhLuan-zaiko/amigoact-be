"""cqlengine persistence for chat attachment claims (single-use files)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from chat.interfaces import AttachmentClaimStore
from chat.model import OrgChatAttachmentClaim


class CqlClaimStore(AttachmentClaimStore):
    """Claim rows keyed by media id; the insert is a raw-CQL LWT because
    cqlengine cannot surface IF NOT EXISTS results (same justification
    as the dm pair claim in repository.py)."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def claim_attachment(
        self, media_id: UUID, room_id: UUID, message_id: UUID, now: datetime
    ) -> bool:
        session = get_session()
        outcome = session.execute(
            f"INSERT INTO {self._keyspace}.chat_attachment_claims"
            " (media_id, room_id, message_id, created_at)"
            " VALUES (%s, %s, %s, %s) IF NOT EXISTS",
            [media_id, room_id, message_id, now],
        )
        return bool(getattr(outcome, "was_applied", False))

    def claimed_attachment(
        self, media_id: UUID
    ) -> OrgChatAttachmentClaim | None:
        return OrgChatAttachmentClaim.objects(media_id=media_id).first()

    def release_attachment(self, media_id: UUID) -> None:
        OrgChatAttachmentClaim.objects(media_id=media_id).delete()
