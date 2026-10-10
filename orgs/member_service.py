"""Membership business rules: lifecycle, RBAC matrix, audit. No FastAPI."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    AlreadyInvitedError,
    AlreadyMemberError,
    ForbiddenError,
    InvalidMemberStateError,
    InvalidRoleError,
    InviteOnlyError,
    MemberNotFoundError,
    NotFoundError,
    OrgDeletedError,
    OwnerImmutableError,
    UserNotFoundError,
)
from core.security import utcnow
from orgs.interfaces import (
    MemberEvents,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
from orgs.member_helpers import (
    is_active_member,
    is_admin,
    live_org,
    member_snapshot,
    my_memberships,
    role_of,
)
from orgs.member_listing import (
    MemberPage,
    MemberSnapshot,
    MembershipSnapshot,
    paginate_members,
)
from rbac.interfaces import AccessControl

if TYPE_CHECKING:
    from orgs.model import Organization


class MemberService:
    """Invite/accept/decline/join/leave/suspend/remove/role for orgs."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        users: UserDirectory,
        access: AccessControl,
        events: MemberEvents,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._users = users
        self._access = access
        self._events = events

    def _emit(
        self,
        org_id: UUID,
        action: str,
        target_id: UUID,
        actor_id: UUID,
        *,
        notify: UUID | None = None,
    ) -> None:
        """Fan out after a committed change; publish failures never raise."""
        try:
            self._events.member_changed(org_id, action, target_id, actor_id)
            if notify is not None:
                self._events.inbox_changed(notify, action, org_id)
        except Exception:  # noqa: BLE001 - realtime is best-effort
            pass

    def _deny(
        self, org_id: UUID, actor_id: UUID, action: str, target_id: UUID | None
    ) -> ForbiddenError:
        self._access.record(
            org_id, actor_id, action, "member", target_id, "denied"
        )
        return ForbiddenError("Only org managers can do this.")

    def _require_manager(
        self,
        org: Organization,
        actor_id: UUID,
        permission: str,
        action: str,
        target_id: UUID | None = None,
    ) -> str:
        """Owner passes; others need membership AND the permission code."""
        if org.owner_id == actor_id:
            return "owner"
        if is_active_member(
            self._members, org.id, actor_id
        ) and self._access.has_permission(org.id, actor_id, permission):
            return "admin"
        raise self._deny(org.id, actor_id, action, target_id)

    def _audit(
        self, org_id: UUID, actor_id: UUID, action: str, target_id: UUID | None
    ) -> None:
        self._access.record(
            org_id, actor_id, action, "member", target_id, "allowed"
        )

    def list_members(
        self,
        org_id: UUID,
        viewer_id: UUID,
        *,
        q: str | None = None,
        status: str | None = None,
        sort: str = "newest",
        limit: int = 20,
        offset: int = 0,
    ) -> MemberPage:
        """Roster: managers see all states plus email; members see active."""
        org = live_org(self._orgs, org_id)
        viewer_role = role_of(self._access, org, viewer_id)
        if org.owner_id != viewer_id and not is_active_member(
            self._members, org_id, viewer_id
        ):
            raise self._deny(org_id, viewer_id, "member.list", None)
        manager = viewer_role != "member"
        role_map = self._access.role_map(org_id)
        rows = self._members.list_by_org(org_id)
        if not manager:
            rows = [row for row in rows if row.status == "active"]
        snapshots = [
            member_snapshot(self._users, org, row, role_map, show_email=manager)
            for row in rows
        ]
        result = paginate_members(
            snapshots, q=q, status=status, sort=sort, limit=limit, offset=offset
        )
        return MemberPage(
            items=result.items,
            total=result.total,
            counts=result.counts,
            viewer_role=viewer_role,
        )

    def list_my_memberships(
        self, user_id: UUID, *, status: str | None = None
    ) -> list[MembershipSnapshot]:
        """Caller's links across orgs (invitation inbox, mine view)."""
        return my_memberships(
            self._members, self._orgs, self._access, user_id, status
        )

    def invite_member(
        self, org_id: UUID, actor_id: UUID, email: str, role: str = "member"
    ) -> MemberSnapshot:
        """Manager invites an account; left rows are re-invited in place."""
        org = live_org(self._orgs, org_id)
        self._require_manager(org, actor_id, "member:invite", "member.invite")
        brief = self._users.find_by_email(email)
        if brief is None or brief.status != "active":
            raise UserNotFoundError("No account uses this email.")
        if brief.id == org.owner_id:
            raise AlreadyMemberError("The owner is already a member.")
        row = self._members.get(org_id, brief.id)
        if row is not None:
            state = getattr(row, "status", "active") or "active"
            if state == "invited":
                raise AlreadyInvitedError("This user was already invited.")
            if state in ("active", "suspended"):
                raise AlreadyMemberError("This user is already a member.")
        if role not in ("member", "admin"):
            raise InvalidRoleError("Role is invalid.")
        if role == "admin" and org.owner_id != actor_id:
            raise self._deny(org.id, actor_id, "member.invite", brief.id)
        now = utcnow()
        if row is None:
            self._members.put(org_id, brief.id, "invited", now)
        else:
            self._members.set_status(org_id, brief.id, "invited", now)
        if role == "admin":
            self._access.assign(org_id, actor_id, brief.id, "admin")
        self._audit(org_id, actor_id, "member.invite", brief.id)
        self._emit(org_id, "invited", brief.id, actor_id, notify=brief.id)
        fresh = self._members.get(org_id, brief.id)
        assert fresh is not None
        return member_snapshot(
            self._users, org, fresh, self._access.role_map(org_id), show_email=True
        )

    def _transition_invite(
        self,
        org_id: UUID,
        user_id: UUID,
        target: str,
        action: str,
        event: str,
    ) -> MemberSnapshot:
        org = live_org(self._orgs, org_id)
        row = self._members.get(org_id, user_id)
        if row is None or row.status != "invited":
            raise InvalidMemberStateError("No pending invitation found.")
        self._members.set_status(org_id, user_id, target, utcnow())
        self._audit(org_id, user_id, action, user_id)
        self._emit(org_id, event, user_id, user_id, notify=user_id)
        fresh = self._members.get(org_id, user_id)
        assert fresh is not None
        return member_snapshot(
            self._users, org, fresh, self._access.role_map(org_id), show_email=True
        )

    def accept_invitation(self, org_id: UUID, user_id: UUID) -> MemberSnapshot:
        """Invitee accepts: invited -> active."""
        return self._transition_invite(
            org_id, user_id, "active", "member.accept", "accepted"
        )

    def decline_invitation(self, org_id: UUID, user_id: UUID) -> MemberSnapshot:
        """Invitee declines: invited -> left (audit kept)."""
        return self._transition_invite(
            org_id, user_id, "left", "member.decline", "declined"
        )

    def join_org(self, org_id: UUID, user_id: UUID) -> MemberSnapshot:
        """Open orgs admit anyone instantly; invite orgs reject here."""
        org = live_org(self._orgs, org_id)
        policy = getattr(org, "join_policy", None) or "invite"
        if policy != "open":
            self._access.record(
                org_id, user_id, "member.join", "member", user_id, "denied"
            )
            raise InviteOnlyError("This org only admits invited members.")
        row = self._members.get(org_id, user_id)
        if row is not None:
            state = getattr(row, "status", "active") or "active"
            if state == "active":
                raise AlreadyMemberError("This user is already a member.")
            if state == "suspended":
                raise AlreadyMemberError("This user is already a member.")
        now = utcnow()
        if row is None:
            self._members.put(org_id, user_id, "active", now)
        else:
            self._members.set_status(org_id, user_id, "active", now)
        self._audit(org_id, user_id, "member.join", user_id)
        self._emit(org_id, "joined", user_id, user_id, notify=user_id)
        fresh = self._members.get(org_id, user_id)
        assert fresh is not None
        return member_snapshot(
            self._users, org, fresh, self._access.role_map(org_id), show_email=True
        )

    def remove_member(self, org_id: UUID, actor_id: UUID, user_id: UUID) -> None:
        """Self-leave or manager removal; every exit lands on `left`."""
        org = live_org(self._orgs, org_id)
        if user_id == org.owner_id:
            raise OwnerImmutableError("The owner cannot leave or be removed.")
        row = self._members.get(org_id, user_id)
        if row is None or row.status == "left":
            raise MemberNotFoundError("Member not found.")
        action = "member.leave" if actor_id == user_id else "member.remove"
        if actor_id != user_id:
            self._require_manager(
                org, actor_id, "member:remove", action, user_id
            )
            if is_admin(self._access, org_id, user_id) and org.owner_id != actor_id:
                raise self._deny(org.id, actor_id, action, user_id)
        self._members.set_status(org_id, user_id, "left", utcnow())
        self._access.revoke(org_id, user_id, "admin")
        self._audit(org_id, actor_id, action, user_id)
        event = "left" if actor_id == user_id else "removed"
        self._emit(org_id, event, user_id, actor_id, notify=user_id)

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
