"""Board authorization guards shared by the post services (no FastAPI)."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import ForbiddenError
from orgs.interfaces import MemberRepository, OrgRepository
from orgs.member_helpers import is_active_member, live_org
from rbac.catalog import PERMISSIONS
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

    def can_manage(self, org_id: UUID, org_owner: UUID, user_id: UUID) -> bool:
        if org_owner == user_id:
            return True
        return is_active_member(
            self._members, org_id, user_id
        ) and self._access.has_permission(org_id, user_id, "post:manage")

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

    def require_author_or_manage(
        self, org_id: UUID, org_owner: UUID, author_id: UUID, user_id: UUID,
        action: str, target_id: UUID,
    ) -> None:
        if author_id != user_id:
            self.require_manage(org_id, org_owner, user_id, action, target_id)

    def require_author(
        self, org_id: UUID, author_id: UUID, user_id: UUID, action: str,
        target_id: UUID,
    ) -> None:
        if author_id == user_id:
            return
        self._access.record(
            org_id, user_id, action, "post", target_id, "denied"
        )
        raise ForbiddenError("Only the author can edit this post.")

    def require_announce(
        self, org_id: UUID, org_owner: UUID, user_id: UUID, action: str,
        target_id: UUID | None = None,
    ) -> None:
        if org_owner == user_id or (
            is_active_member(self._members, org_id, user_id)
            and self._access.has_permission(org_id, user_id, "post:announce")
        ):
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
        member_service.list_members — reporting an empty list would let
        the client lock the owner out of manager UI.
        """
        if org_owner == viewer_id:
            return "owner", sorted(PERMISSIONS)
        return "member", sorted(
            self._access.effective_permissions(org_id, viewer_id)
        )
