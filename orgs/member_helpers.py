"""Shared member helpers: org guard, role resolution, snapshot mapping."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import NotFoundError, OrgDeletedError
from orgs.interfaces import MemberRepository, OrgRepository, UserDirectory
from orgs.member_listing import MemberSnapshot, MembershipSnapshot
from orgs.model import Organization, OrganizationMember
from rbac.interfaces import AccessControl


def live_org(orgs: OrgRepository, org_id: UUID) -> Organization:
    """Load a non-deleted org or raise 404/410."""
    org = orgs.get_by_id(org_id)
    if org is None:
        raise NotFoundError("Organization not found.")
    if getattr(org, "deleted_at", None) is not None:
        raise OrgDeletedError("Organization is soft-deleted.")
    return org


def is_admin(access: AccessControl, org_id: UUID, user_id: UUID) -> bool:
    """True when the user holds an org-scoped admin role row."""
    return "admin" in access.role_names_of(org_id, user_id)


def role_of(access: AccessControl, org: Organization, user_id: UUID) -> str:
    """Display role: owner first, then RBAC admin, else member."""
    if org.owner_id == user_id:
        return "owner"
    if is_admin(access, org.id, user_id):
        return "admin"
    return "member"


def is_active_member(
    members: MemberRepository, org_id: UUID, user_id: UUID
) -> bool:
    """True when the membership row exists and is active."""
    row = members.get(org_id, user_id)
    return row is not None and row.status == "active"


def member_snapshot(
    users: UserDirectory,
    org: Organization,
    row: OrganizationMember,
    role_map: dict[UUID, list[str]],
    *,
    show_email: bool,
) -> MemberSnapshot:
    """Project one membership row to a display snapshot with privacy."""
    brief = users.get_brief(row.user_id)
    role = (
        "owner"
        if row.user_id == org.owner_id
        else "admin" if "admin" in role_map.get(row.user_id, []) else "member"
    )
    return MemberSnapshot(
        org_id=org.id,
        user_id=row.user_id,
        full_name=brief.full_name if brief else "Unknown user",
        email=brief.email if (show_email and brief) else None,
        role=role,
        status=getattr(row, "status", "active") or "active",
        joined_at=row.joined_at,
    )


def my_memberships(
    members: MemberRepository,
    orgs: OrgRepository,
    access: AccessControl,
    user_id: UUID,
    status: str | None,
) -> list[MembershipSnapshot]:
    """Caller's links across orgs (invitation inbox, mine view)."""
    out: list[MembershipSnapshot] = []
    for link in members.list_links_by_user(user_id):
        if status is not None and link.status != status:
            continue
        org = orgs.get_by_id(link.org_id)
        if org is None or getattr(org, "deleted_at", None) is not None:
            continue
        out.append(
            MembershipSnapshot(
                org_id=org.id,
                org_name=org.name,
                org_slug=org.slug,
                role=role_of(access, org, user_id),
                status=link.status,
                joined_at=link.joined_at,
            )
        )
    out.sort(key=lambda item: item.joined_at, reverse=True)
    return out
