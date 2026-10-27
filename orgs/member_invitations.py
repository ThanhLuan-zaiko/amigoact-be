"""Invitation lifecycle extracted from MemberService: invite/answer/revoke."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import (
    AlreadyInvitedError,
    AlreadyMemberError,
    ForbiddenError,
    InvalidMemberStateError,
    InvalidRoleError,
    UserNotFoundError,
)
from core.exceptions_roles import RoleHierarchyError
from core.security import utcnow
from orgs.member_helpers import (
    is_active_member,
    is_admin,
    live_org,
    member_snapshot,
)
from orgs.member_listing import MemberSnapshot

if TYPE_CHECKING:
    from notifications.interfaces import NotificationPort
    from orgs.interfaces import (
        MemberEvents,
        MemberRepository,
        OrgRepository,
        UserDirectory,
    )
    from orgs.model import Organization
    from rbac.interfaces import AccessControl


class MemberInvitationsMixin:
    """Invite send/answer/revoke transitions; mixed into MemberService."""

    if TYPE_CHECKING:  # attributes supplied by MemberService
        _orgs: OrgRepository
        _members: MemberRepository
        _users: UserDirectory
        _access: AccessControl
        _notifications: NotificationPort | None

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
        if role != "member":
            if self._access.role_permissions_of(org_id, role) is None:
                raise InvalidRoleError("Role is invalid.")
            if role == "admin" and org.owner_id != actor_id:
                raise self._deny(org.id, actor_id, "member.invite", brief.id)
            if role != "admin" and org.owner_id != actor_id:
                # Inviting straight into a custom role is a role-assign
                # act: needs member:role-assign plus the subset rule.
                assignable = (
                    is_active_member(self._members, org_id, actor_id)
                    and self._access.has_permission(
                        org_id, actor_id, "member:role-assign"
                    )
                    and self._access.role_permissions_of(
                        org_id, role
                    )
                    <= self._access.effective_permissions(org_id, actor_id)
                )
                if not assignable:
                    raise self._deny(
                        org.id, actor_id, "member.invite", brief.id
                    )
                ceiling = self._access.role_ceiling(org_id, actor_id)
                rank = self._access.role_position_of(org_id, role)
                if ceiling is not None and rank is not None and rank >= ceiling:
                    self._deny(org.id, actor_id, "member.invite", brief.id)
                    raise RoleHierarchyError("Role ranks at or above your own.")
        now = utcnow()
        if row is None:
            self._members.put(
                org_id, brief.id, "invited", now, invited_by=actor_id
            )
        else:
            self._members.set_status(
                org_id, brief.id, "invited", now, invited_by=actor_id
            )
        if role != "member":
            self._access.assign(org_id, actor_id, brief.id, role)
        self._audit(org_id, actor_id, "member.invite", brief.id)
        self._emit(org_id, "invited", brief.id, actor_id, notify=brief.id)
        if self._notifications is not None:
            try:
                self._notifications.notify(
                    brief.id,
                    "membership",
                    f"L\u1eddi m\u1eddi v\u00e0o {org.name}",
                    "B\u1ea1n \u0111\u01b0\u1ee3c m\u1eddi tham gia t\u1ed5 ch\u1ee9c. V\u00e0o H\u1ed9p th\u01b0 l\u1eddi m\u1eddi \u0111\u1ec3 ph\u1ea3n h\u1ed3i.",
                    f'{{"org_id": "{org_id}", "org_slug": "{org.slug}"}}',
                )
            except Exception:  # noqa: BLE001 - notifications are best-effort
                pass
        fresh = self._members.get(org_id, brief.id)
        assert fresh is not None
        return member_snapshot(
            self._users,
            org,
            fresh,
            self._access.role_map(org_id),
            show_email=True,
            media=self._media,
        )

    def revoke_invitation(
        self, org_id: UUID, actor_id: UUID, user_id: UUID
    ) -> MemberSnapshot:
        """Manager withdraws a pending invite: invited -> revoked.

        Revoked is its own terminal-ish state (not `left`) so the audit
        trail keeps "the org withdrew the invite" apart from "the user
        left/declined". The invitee can be re-invited or join an open
        org later; revocation is not a ban.
        """
        org = live_org(self._orgs, org_id)
        row = self._members.get(org_id, user_id)
        if row is None or getattr(row, "status", "active") != "invited":
            raise InvalidMemberStateError("No pending invitation found.")
        # Invites live under the inviter permission; the admin-target
        # guard mirrors remove_member so admins cannot undo an
        # owner-granted admin invite.
        self._require_manager(
            org, actor_id, "member:invite", "member.revoke", user_id
        )
        if is_admin(self._access, org_id, user_id) and org.owner_id != actor_id:
            raise self._deny(org.id, actor_id, "member.revoke", user_id)
        self._members.set_status(org_id, user_id, "revoked", utcnow())
        for name in self._access.role_names_of(org_id, user_id):
            self._access.revoke(org_id, user_id, name)
        self._audit(org_id, actor_id, "member.revoke", user_id)
        self._emit(org_id, "revoked", user_id, actor_id, notify=user_id)
        if self._notifications is not None:
            try:
                self._notifications.notify(
                    user_id,
                    "membership",
                    f"L\u1eddi m\u1eddi v\u00e0o {org.name} \u0111\u00e3 b\u1ecb thu h\u1ed3i",
                    "T\u1ed5 ch\u1ee9c \u0111\u00e3 thu h\u1ed3i l\u1eddi m\u1eddi tr\u01b0\u1edbc khi b\u1ea1n ph\u1ea3n h\u1ed3i.",
                    f'{{"org_id": "{org_id}", "org_slug": "{org.slug}"}}',
                )
            except Exception:  # noqa: BLE001 - notifications are best-effort
                pass
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
            self._users,
            org,
            fresh,
            self._access.role_map(org_id),
            show_email=True,
            media=self._media,
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
