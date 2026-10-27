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
from core.exceptions_roles import RoleHierarchyError
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
            detail: str | None = None,
        ) -> None: ...

    def _apply_roles(
        self,
        org: Organization,
        actor_id: UUID,
        user_id: UUID,
        roles: list[str],
    ) -> list[tuple[str, str | None]]:
        """Replace the target's role set; returns (event, detail) pairs.

        The system "admin" role stays owner-only. Non-owner assigners
        need member:role-assign, may only touch custom roles, and only
        roles whose permissions sit inside their own effective set.
        """
        self._require_manager(
            org, actor_id, "member:role-assign", "member.role", user_id
        )
        target = set(roles)
        resolved: dict[str, set[str]] = {}
        for name in target:
            perms = self._access.role_permissions_of(org.id, name)
            if perms is None:
                raise InvalidRoleError("Role is invalid.")
            resolved[name] = perms
        current = set(self._access.role_names_of(org.id, user_id))
        added = target - current
        removed = current - target
        if org.owner_id != actor_id:
            held = self._access.effective_permissions(org.id, actor_id)
            ceiling = self._access.role_ceiling(org.id, actor_id)
            for name in added | removed:
                if name == "admin" or not resolved.get(name, set()) <= held:
                    raise self._deny(
                        org.id, actor_id, "member.role", user_id
                    )
                rank = self._access.role_position_of(org.id, name)
                if ceiling is not None and rank is not None and rank >= ceiling:
                    self._deny(org.id, actor_id, "member.role", user_id)
                    raise RoleHierarchyError("Role ranks at or above your own.")
        for name in removed:
            self._access.revoke(org.id, user_id, name)
        for name in added:
            self._access.assign(org.id, actor_id, user_id, name)
        self._audit(org.id, actor_id, "member.role", user_id)
        events: list[tuple[str, str | None]] = []
        for name in removed:
            events.append(
                ("demoted", None) if name == "admin" else ("role_revoked", name)
            )
        for name in added:
            events.append(
                ("promoted", None) if name == "admin" else ("role_granted", name)
            )
        return events

    def update_member(
        self,
        org_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        *,
        role: str | None = None,
        roles: list[str] | None = None,
        status: str | None = None,
    ) -> MemberSnapshot:
        """Owner assigns roles; managers suspend/reactivate plain members."""
        org = live_org(self._orgs, org_id)
        if user_id == org.owner_id:
            raise OwnerImmutableError("The owner cannot be modified.")
        row = self._members.get(org_id, user_id)
        if row is None or row.status in ("left", "revoked"):
            raise MemberNotFoundError("Member not found.")
        events: list[tuple[str, str | None]] = []
        if roles is not None:
            events.extend(self._apply_roles(org, actor_id, user_id, roles))
        elif role is not None:
            if org.owner_id != actor_id:
                raise self._deny(org.id, actor_id, "member.role", user_id)
            if role == "admin":
                self._access.assign(org_id, actor_id, user_id, "admin")
                events.append(("promoted", None))
            elif role == "member":
                for name in self._access.role_names_of(org.id, user_id):
                    self._access.revoke(org.id, user_id, name)
                    events.append(
                        ("demoted", None)
                        if name == "admin"
                        else ("role_revoked", name)
                    )
            else:
                raise InvalidRoleError("Role is invalid.")
            self._audit(org.id, actor_id, "member.role", user_id)
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
            events.append(
                ("suspended" if status == "suspended" else "reactivated", None)
            )
        for event, detail in events:
            self._emit(
                org_id, event, user_id, actor_id,
                notify=user_id, detail=detail,
            )
        fresh = self._members.get(org_id, user_id)
        assert fresh is not None
        return member_snapshot(
            self._users,
            org,
            fresh,
            self._access.role_map(org_id),
            show_email=True,
            media=self._media,
        )
