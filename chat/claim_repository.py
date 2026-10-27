"""cqlengine persistence for chat attachment claims (single-use files)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


from chat.interfaces import AttachmentClaimStore
from chat.model import OrgChatAttachmentClaim
from core.cql import run as cql_run


class CqlClaimStore(AttachmentClaimStore):
    """Claim rows keyed by media id; the insert is a raw-CQL LWT because
    cqlengine cannot surface IF NOT EXISTS results (same justification
    as the dm pair claim in repository.py)."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def claim_attachment(
        self, media_id: UUID, room_id: UUID, message_id: UUID, now: datetime
    ) -> bool:
        outcome = cql_run(
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
