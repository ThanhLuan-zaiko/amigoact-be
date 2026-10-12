"""Channel ACL adapters: production implementations of the read ports."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from activities.interfaces import ActivityStore
from orgs.interfaces import MemberRepository, OrgRepository
from rbac.interfaces import AccessControl
from realtime.interfaces import (
    AttendanceAccess,
    OrgMembership,
    PresenceDirectory,
)


def _is_active(row: Any) -> bool:
    """A missing status reads as active, matching OrgRepository.is_member."""
    return (getattr(row, "status", None) or "active") == "active"


class OrgChannelMembership(OrgMembership):
    """Channel membership check against the org membership feed."""

    def __init__(self, orgs: OrgRepository) -> None:
        self._orgs = orgs

    def is_member(self, org_id: UUID, user_id: UUID) -> bool:
        return self._orgs.is_member(org_id, user_id)


class MemberPresenceDirectory(PresenceDirectory):
    """Presence reads over the org member tables.

    Presence mirrors the visible roster: only members whose link is
    "active" publish or appear in online snapshots, so suspended and
    invited rows never leak a socket state.
    """

    def __init__(self, members: MemberRepository) -> None:
        self._members = members

    def orgs_of(self, user_id: UUID) -> list[UUID]:
        return [
            link.org_id
            for link in self._members.list_links_by_user(user_id)
            if _is_active(link)
        ]

    def member_ids_of(self, org_id: UUID) -> list[UUID]:
        return [
            member.user_id
            for member in self._members.list_by_org(org_id)
            if _is_active(member)
        ]


class OrgAttendanceAccess(AttendanceAccess):
    """Live check-in feed mirrors list_attendance: org managers only.

    Viewers are the org owner or members holding the activity:manage
    permission, exactly like the REST attendance list and mutations.
    """

    def __init__(
        self,
        activities: ActivityStore,
        orgs: OrgRepository,
        access: AccessControl,
    ) -> None:
        self._activities = activities
        self._orgs = orgs
        self._access = access

    def can_view(self, activity_id: UUID, user_id: UUID) -> bool:
        activity = self._activities.get(activity_id)
        if activity is None:
            return False
        org = self._orgs.get_by_id(activity.org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            return False
        if getattr(org, "owner_id", None) == user_id:
            return True
        return bool(
            self._access.has_permission(
                activity.org_id, user_id, "activity:manage"
            )
        )
