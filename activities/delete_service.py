"""Trash lifecycle for activities: soft delete, restore, hard purge."""

from __future__ import annotations

from uuid import UUID

from activities.interfaces import (
    ActivityChatLink,
    ActivityEvents,
    ActivityStore,
)
from activities.model import Activity
from activities.tag_claim import PersonalTagBook
from core.exceptions import (
    ActivityDeletedError,
    ForbiddenError,
    InvalidOrgStateError,
    NotFoundError,
)
from core.media import MediaStore
from core.security import utcnow
from orgs.interfaces import OrgRepository
from rbac.implied import holds
from rbac.interfaces import AccessControl


class ActivityDeleteService:
    """Owner/manager trash operations; mirrors the org delete contract."""

    def __init__(
        self,
        activities: ActivityStore,
        orgs: OrgRepository,
        access: AccessControl,
        events: ActivityEvents | None = None,
        store: MediaStore | None = None,
        user_tags: PersonalTagBook | None = None,
        chat: ActivityChatLink | None = None,
    ) -> None:
        self._activities = activities
        self._orgs = orgs
        self._access = access
        self._events = events
        self._store = store
        self._user_tags = user_tags
        self._chat = chat

    def _emit(
        self,
        org_id: UUID,
        action: str,
        activity_id: UUID,
        actor_id: UUID,
        status: str,
    ) -> None:
        """Best-effort fan-out; a dead bus never blocks a mutation."""
        if self._events is None:
            return
        try:
            self._events.activity_changed(
                org_id, action, activity_id, actor_id, status
            )
        except Exception:  # noqa: BLE001 - live fan-out is advisory
            pass

    def _hint_chat(self, org_id: UUID, activity_id: UUID) -> None:
        """Chat freezes at read time; this only refreshes inboxes."""
        if self._chat is None:
            return
        try:
            self._chat.activity_changed(org_id, activity_id)
        except Exception:  # noqa: BLE001 - live fan-out is advisory
            pass

    def _activity(self, org_id: UUID, activity_id: UUID) -> Activity:
        row = self._activities.get(activity_id)
        if row is None or row.org_id != org_id:
            raise NotFoundError("Activity not found.")
        return row

    def _manager(self, org_id: UUID, actor_id: UUID) -> None:
        org = self._orgs.get_by_id(org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "owner_id", None) != actor_id and not holds(
            self._access, org_id, actor_id, "activity:delete"
        ):
            raise ForbiddenError("Only org managers can do this.")

    def soft_delete(
        self, org_id: UUID, activity_id: UUID, actor_id: UUID
    ) -> Activity:
        """Reversible trash; feeds and the slug claim stay in place."""
        self._manager(org_id, actor_id)
        row = self._activity(org_id, activity_id)
        if row.deleted_at is not None:
            raise ActivityDeletedError("Activity is already deleted.")
        updated = self._activities.mark_deleted(activity_id, utcnow())
        assert updated is not None
        self._emit(
            org_id, "deleted", activity_id, actor_id, updated.status
        )
        self._hint_chat(org_id, activity_id)
        return updated

    def restore(
        self, org_id: UUID, activity_id: UUID, actor_id: UUID
    ) -> Activity:
        """Bring a trashed activity back with the same slug."""
        self._manager(org_id, actor_id)
        row = self._activity(org_id, activity_id)
        if row.deleted_at is None:
            raise InvalidOrgStateError("Activity is not deleted.")
        updated = self._activities.mark_restored(activity_id, utcnow())
        assert updated is not None
        self._emit(
            org_id, "restored", activity_id, actor_id, updated.status
        )
        self._hint_chat(org_id, activity_id)
        return updated

    def hard_delete(
        self, org_id: UUID, activity_id: UUID, actor_id: UUID
    ) -> None:
        """Permanent purge: rows, feeds, edges, media rows and bytes."""
        self._manager(org_id, actor_id)
        row = self._activity(org_id, activity_id)
        owner = getattr(row, "created_by", None)
        if self._user_tags is not None and owner is not None:
            self._user_tags.bind_activity(owner, org_id, activity_id, None)
        if self._chat is not None:
            # Before the row purge: a chat failure leaves the event in
            # place so the manager can retry instead of orphaning rows.
            self._chat.activity_purged(
                org_id, activity_id, getattr(row, "created_at", None),
                actor_id,
            )
        paths = self._activities.delete_everything(activity_id)
        self._emit(org_id, "deleted", activity_id, actor_id, row.status)
        if self._store is not None:
            for path in paths:
                self._store.delete_file(path)
