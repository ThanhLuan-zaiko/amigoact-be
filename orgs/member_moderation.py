"""Moderation rules extracted from MemberService: roles and suspensions."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    ForbiddenError,
    InvalidMemberStateError,
    InvalidRoleError,
    MemberNotFoundError,
    OwnerImmutableError,
)
from core.security import utcnow
from orgs.member_helpers import (
    is_admin,
    live_org,
    member_snapshot,
)
from orgs.member_listing import MemberSnapshot

if TYPE_CHECKING:
    from orgs.interfaces import (
        MemberRepository,
        OrgRepository,
        UserDirectory,
    )
    from orgs.model import Organization
    from rbac.interfaces import AccessControl


class MemberModerationMixin:
    """Role assignment and suspend/reactivate; mixed into MemberService."""

    if TYPE_CHECKING:  # attributes supplied by MemberService
        _orgs: OrgRepository
        _members: MemberRepository
        _users: UserDirectory
        _access: AccessControl

        def _deny(
            self, org_id: UUID, actor_id: UUID, action: str,
            target_id: UUID | None,
        ) -> ForbiddenError: ...
        def _require_manager(
            self, org: Organization, actor_id: UUID, permission: str,
            action: str, target_id: UUID | None = None,
        ) -> str: ...
        def _audit(
            self, org_id: UUID, actor_id: UUID, action: str,
            target_id: UUID | None,
        ) -> None: ...
        def _emit(
            self, org_id: UUID, action: str, target_id: UUID,
            actor_id: UUID, *, notify: UUID | None = None,
        ) -> None: ...

    def update_member(
        self,
        org_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        *,
        role: str | None = None,
        status: str | None = None,
    ) -> MemberSnapshot:
        """Owner assigns roles; managers suspend/reactivate plain members."""
        org = live_org(self._orgs, org_id)
        if user_id == org.owner_id:
            raise OwnerImmutableError("The owner cannot be modified.")
        row = self._members.get(org_id, user_id)
        if row is None or row.status == "left":
            raise MemberNotFoundError("Member not found.")
        if role is not None:
            if org.owner_id != actor_id:
                raise self._deny(org.id, actor_id, "member.role", user_id)
            if role == "admin":
                self._access.assign(org_id, actor_id, user_id, "admin")
            elif role == "member":
                self._access.revoke(org_id, user_id, "admin")
            else:
                raise InvalidRoleError("Role is invalid.")
            self._audit(org_id, actor_id, "member.role", user_id)
        if status is not None:
            if status not in ("suspended", "active"):
                raise InvalidMemberStateError("Status transition is invalid.")
            self._require_manager(
                org, actor_id, "member:suspend", "member.suspend", user_id
            )
            if is_admin(self._access, org_id, user_id) and org.owner_id != actor_id:
                raise self._deny(org.id, actor_id, "member.suspend", user_id)
            current = getattr(row, "status", "active") or "active"
            if status == "suspended" and current != "active":
                raise InvalidMemberStateError(
                    "Only active members can be suspended."
                )
            if status == "active" and current != "suspended":
                raise InvalidMemberStateError(
                    "Only suspended members can be reactivated."
                )
            self._members.set_status(org_id, user_id, status, utcnow())
            self._audit(org_id, actor_id, "member.suspend", user_id)
        events: list[str] = []
        if role is not None:
            events.append("promoted" if role == "admin" else "demoted")
        if status is not None:
            events.append(
                "suspended" if status == "suspended" else "reactivated"
            )
        for event in events:
            self._emit(org_id, event, user_id, actor_id, notify=user_id)
        fresh = self._members.get(org_id, user_id)
        assert fresh is not None
        return member_snapshot(
            self._users, org, fresh, self._access.role_map(org_id), show_email=True
        )
