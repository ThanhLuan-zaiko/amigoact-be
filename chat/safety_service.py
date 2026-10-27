"""Org chat safety admin: attachment policy and member timeouts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from chat.permissions import CHANNEL, MODERATE, TIMEOUT, holds_chat_permission
from chat.safety import active_timeout
from chat.safety_interfaces import ChatSafetyStore, TimeoutRecord
from core.exceptions import (
    ForbiddenError,
    MemberNotFoundError,
    NotFoundError,
    OrgDeletedError,
)
from core.security import utc_aware
from orgs.interfaces import MemberEvents, MemberRepository, OrgRepository, UserDirectory
from orgs.member_helpers import is_active_member
from rbac.interfaces import AccessControl

MAX_MINUTES = 10_080  # seven days


@dataclass(frozen=True)
class TimeoutView:
    user_id: UUID
    user_name: str
    until: datetime
    set_by: UUID
    reason: str


@dataclass(frozen=True)
class SafetyOverview:
    attach_restricted: bool
    # The viewer's own timeout; lets the composer explain itself.
    my_timeout_until: datetime | None = None
    # Active timeouts, visible to people who can set them.
    timeouts: list[TimeoutView] = field(default_factory=list)


class ChatSafetyService:
    """Owner and chat:timeout / chat:channel holders manage chat safety."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        store: ChatSafetyStore,
        access: AccessControl,
        users: UserDirectory,
        events: MemberEvents | None = None,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._store = store
        self._access = access
        self._users = users
        self._events = events

    def _org(self, org_id: UUID):  # noqa: ANN202
        org = self._orgs.get_by_id(org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if getattr(org, "deleted_at", None) is not None:
            raise OrgDeletedError("Organization is soft-deleted.")
        return org

    def _require_member(self, org, user_id: UUID) -> None:  # noqa: ANN001
        if org.owner_id != user_id and not is_active_member(
            self._members, org.id, user_id
        ):
            raise ForbiddenError("Only org members can view this.")

    def _can(self, org, user_id: UUID, code: str) -> bool:  # noqa: ANN001
        return org.owner_id == user_id or (
            is_active_member(self._members, org.id, user_id)
            and holds_chat_permission(self._access, org.id, user_id, code)
        )

    def _deny(self, org, actor_id: UUID, action: str) -> ForbiddenError:  # noqa: ANN001
        self._access.record(org.id, actor_id, action, "chat", None, "denied")
        return ForbiddenError("You cannot do this in this org chat.")

    def _view(self, row: TimeoutRecord) -> TimeoutView:
        brief = self._users.get_brief(row.user_id)
        return TimeoutView(
            user_id=row.user_id,
            user_name=(brief.full_name if brief else "") or "",
            until=utc_aware(row.until),  # type: ignore[arg-type]
            set_by=row.set_by,
            reason=row.reason,
        )

    def _fan_out(
        self, org_id: UUID, action: str, target: UUID, actor: UUID,
        detail: str | None,
    ) -> None:
        if self._events is None:
            return
        try:
            self._events.member_changed(org_id, action, target, actor, detail=detail)
            self._events.inbox_changed(target, action, org_id, detail=detail)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def overview(self, org_id: UUID, viewer_id: UUID) -> SafetyOverview:
        org = self._org(org_id)
        self._require_member(org, viewer_id)
        mine = active_timeout(self._store, org_id, viewer_id)
        timeouts: list[TimeoutView] = []
        if self._can(org, viewer_id, TIMEOUT) or self._can(org, viewer_id, MODERATE):
            timeouts = [
                self._view(row)
                for row in self._store.list_timeouts(org_id)
                if active_timeout(self._store, org_id, row.user_id) is not None
            ]
        return SafetyOverview(
            attach_restricted=self._store.attach_restricted(org_id),
            my_timeout_until=utc_aware(mine.until) if mine else None,
            timeouts=timeouts,
        )

    def set_attach_restricted(
        self, org_id: UUID, actor_id: UUID, restricted: bool
    ) -> bool:
        org = self._org(org_id)
        if not self._can(org, actor_id, CHANNEL):
            raise self._deny(org, actor_id, "chat.attach_policy")
        self._store.set_attach_restricted(org_id, restricted)
        self._access.record(
            org_id, actor_id, "chat.attach_policy", "chat", None, "allowed"
        )
        return restricted

    def timeout(
        self, org_id: UUID, actor_id: UUID, user_id: UUID, minutes: int,
        reason: str = "",
    ) -> TimeoutView:
        org = self._org(org_id)
        if not self._can(org, actor_id, TIMEOUT):
            raise self._deny(org, actor_id, "chat.timeout")
        if user_id == actor_id or user_id == org.owner_id:
            raise self._deny(org, actor_id, "chat.timeout")
        if not is_active_member(self._members, org_id, user_id):
            raise MemberNotFoundError("Member not found.")
        if org.owner_id != actor_id:
            # Staff cannot mute each other: admins and anyone who can
            # moderate or mute are out of reach for non-owners.
            roles = self._access.role_names_of(org_id, user_id)
            if "admin" in roles or any(
                holds_chat_permission(self._access, org_id, user_id, code)
                for code in (TIMEOUT, MODERATE)
            ):
                raise self._deny(org, actor_id, "chat.timeout")
        until = datetime.now(timezone.utc) + timedelta(
            minutes=max(1, min(minutes, MAX_MINUTES))
        )
        record = TimeoutRecord(user_id, until, actor_id, reason.strip()[:200])
        self._store.put_timeout(
            org_id, record, int((until - datetime.now(timezone.utc)).total_seconds()) + 60
        )
        self._access.record(org_id, actor_id, "chat.timeout", "chat", None, "allowed")
        self._fan_out(org_id, "chat_timeout", user_id, actor_id, until.isoformat())
        return self._view(record)

    def lift(self, org_id: UUID, actor_id: UUID, user_id: UUID) -> None:
        org = self._org(org_id)
        if not self._can(org, actor_id, TIMEOUT):
            raise self._deny(org, actor_id, "chat.untimeout")
        self._store.delete_timeout(org_id, user_id)
        self._access.record(org_id, actor_id, "chat.untimeout", "chat", None, "allowed")
        self._fan_out(org_id, "chat_untimeout", user_id, actor_id, None)
