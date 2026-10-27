"""Board authorization guards shared by the post services (no FastAPI)."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import ForbiddenError
from orgs.interfaces import MemberRepository, OrgRepository
from orgs.member_helpers import is_active_member, live_org
from rbac.catalog import PERMISSIONS
from rbac.implied import holds
from rbac.interfaces import AccessControl


class BoardGuard:
    """Member gate plus manager (post:manage) and announcer checks."""

    def __init__(
        self,
        orgs: OrgRepository,
        members: MemberRepository,
        access: AccessControl,
    ) -> None:
        self._orgs = orgs
        self._members = members
        self._access = access

    def require_member(self, org_id: UUID, user_id: UUID, action: str):  # noqa: ANN201
        """Live org whose owner or active member is the caller."""
        org = live_org(self._orgs, org_id)
        if org.owner_id == user_id or is_active_member(
            self._members, org_id, user_id
        ):
            return org
        self._access.record(org_id, user_id, action, "post", None, "denied")
        raise ForbiddenError("Only org members can do this.")

    def holds(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, code: str
    ) -> bool:
        """Owner, or an active member holding `code` (umbrellas included)."""
        if org_owner == user_id:
            return True
        return is_active_member(self._members, org_id, user_id) and holds(
            self._access, org_id, user_id, code
        )

    def require(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, code: str,
        action: str, target_id: UUID | None = None,
    ) -> None:
        """Forbid unless the caller holds the permission `code`."""
        if self.holds(org_id, org_owner, user_id, code):
            return
        self._access.record(
            org_id, user_id, action, "post", target_id, "denied"
        )
        raise ForbiddenError("You do not have permission to do this.")

    def can_manage(self, org_id: UUID, org_owner: UUID, user_id: UUID) -> bool:
        return self.holds(org_id, org_owner, user_id, "post:manage")

    def require_manage(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, action: str,
        target_id: UUID | None = None,
    ) -> None:
        if self.can_manage(org_id, org_owner, user_id):
            return
        self._access.record(
            org_id, user_id, action, "post", target_id, "denied"
        )
        raise ForbiddenError("Only org managers can do this.")

    def require_author_or_any(
        self, org_id: UUID, org_owner: UUID, author_id: UUID, user_id: UUID,
        action: str, target_id: UUID, any_code: str,
    ) -> None:
        """Own posts need post:create; other people's need `any_code`."""
        code = "post:create" if author_id == user_id else any_code
        self.require(org_id, org_owner, user_id, code, action, target_id)

    def require_author(
        self, org_id: UUID, org_owner: UUID, author_id: UUID, user_id: UUID,
        action: str, target_id: UUID, code: str = "post:create",
    ) -> None:
        """Only the author, and only while they still hold `code`."""
        if author_id != user_id:
            self._access.record(
                org_id, user_id, action, "post", target_id, "denied"
            )
            raise ForbiddenError("Only the author can edit this post.")
        self.require(org_id, org_owner, user_id, code, action, target_id)

    def require_announce(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, action: str,
        target_id: UUID | None = None,
    ) -> None:
        if self.holds(org_id, org_owner, user_id, "post:announce"):
            return
        self._access.record(
            org_id, user_id, action, "post", target_id, "denied"
        )
        raise ForbiddenError("Only org managers can publish announcements.")

    def record(
        self, org_id: UUID, user_id: UUID, action: str, target_id: UUID | None,
    ) -> None:
        self._access.record(
            org_id, user_id, action, "post", target_id, "allowed"
        )

    def viewer(
        self, org_id: UUID, org_owner: UUID, viewer_id: UUID
    ) -> tuple[str, list[str]]:
        """(viewer_role, viewer_permissions) for page envelopes.

        The owner carries every catalog permission implicitly, like
        member_service.list_members - reporting an empty list would let
        the client lock the owner out of manager UI.
        """
        if org_owner == viewer_id:
            return "owner", sorted(PERMISSIONS)
        return "member", sorted(
            self._access.effective_permissions(org_id, viewer_id)
        )
