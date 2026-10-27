"""ScyllaDB implementation of the chat safety store."""

from __future__ import annotations

from uuid import UUID

from chat.safety_interfaces import ChatSafetyStore, TimeoutRecord
from chat.safety_model import OrgChatSettings, OrgChatTimeout


def _record(row: OrgChatTimeout) -> TimeoutRecord:
    return TimeoutRecord(
        user_id=row.user_id,
        until=row.until,
        set_by=row.set_by,
        reason=row.reason or "",
    )


class CqlChatSafetyStore(ChatSafetyStore):
    def attach_restricted(self, org_id: UUID) -> bool:
        row = OrgChatSettings.objects(org_id=org_id).first()
        return bool(row is not None and row.attach_restricted)

    def set_attach_restricted(self, org_id: UUID, restricted: bool) -> None:
        OrgChatSettings.create(org_id=org_id, attach_restricted=restricted)

    def get_timeout(self, org_id: UUID, user_id: UUID) -> TimeoutRecord | None:
        row = OrgChatTimeout.objects(org_id=org_id, user_id=user_id).first()
        return _record(row) if row is not None else None

    def put_timeout(
        self, org_id: UUID, record: TimeoutRecord, ttl_seconds: int
    ) -> None:
        OrgChatTimeout.objects.ttl(max(1, ttl_seconds)).create(
            org_id=org_id,
            user_id=record.user_id,
            until=record.until,
            set_by=record.set_by,
            reason=record.reason,
        )

    def delete_timeout(self, org_id: UUID, user_id: UUID) -> None:
        OrgChatTimeout.objects(org_id=org_id, user_id=user_id).delete()

    def list_timeouts(self, org_id: UUID) -> list[TimeoutRecord]:
        return [_record(row) for row in OrgChatTimeout.objects(org_id=org_id).all()]
