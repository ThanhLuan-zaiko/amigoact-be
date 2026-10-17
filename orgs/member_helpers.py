"""Shared member helpers: org guard, role resolution, snapshot mapping."""

from __future__ import annotations

from uuid import UUID

from core.exceptions import NotFoundError, OrgDeletedError
from orgs.interfaces import (
    MediaRepository,
    MemberRepository,
    OrgRepository,
    UserDirectory,
)
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
    """Primary display role: owner, then admin, then first custom name."""
    if org.owner_id == user_id:
        return "owner"
    names = access.role_names_of(org.id, user_id)
    if "admin" in names:
        return "admin"
    if names:
        return sorted(names)[0]
    return "member"


def roles_of(
    org: Organization, user_id: UUID, role_map: dict[UUID, list[str]]
) -> list[str]:
    """Badge roles for one member: owner pseudo-role, admin, customs."""
    if user_id == org.owner_id:
        return ["owner"]
    names = role_map.get(user_id, [])
    head = ["admin"] if "admin" in names else []
    return head + sorted(name for name in names if name != "admin")


def is_active_member(
    members: MemberRepository, org_id: UUID, user_id: UUID
) -> bool:
    """True when the membership row exists and is active."""
    row = members.get(org_id, user_id)
    return row is not None and row.status == "active"


def _avatar_url(media: MediaRepository | None, brief) -> str | None:  # noqa: ANN001
    """Resolve a user avatar asset to its /media/ URL (as public_service)."""
    if media is None or brief is None:
        return None
    asset_id = getattr(brief, "avatar_media_id", None)
    if asset_id is None:
        return None
    asset = media.get_asset(asset_id)
    return f"/media/{asset.file_url}" if asset is not None else None


def member_snapshot(
    users: UserDirectory,
    org: Organization,
    row: OrganizationMember,
    role_map: dict[UUID, list[str]],
    *,
    show_email: bool,
    media: MediaRepository | None = None,
) -> MemberSnapshot:
    """Project one membership row to a display snapshot with privacy."""
    brief = users.get_brief(row.user_id)
    inviter_id = getattr(row, "invited_by", None)
    inviter = users.get_brief(inviter_id) if inviter_id is not None else None
    return MemberSnapshot(
        org_id=org.id,
        user_id=row.user_id,
        full_name=brief.full_name if brief else "Unknown user",
        avatar_url=_avatar_url(media, brief),
        email=brief.email if (show_email and brief) else None,
        roles=roles_of(org, row.user_id, role_map),
        status=getattr(row, "status", "active") or "active",
        invited_by=inviter_id,
        invited_by_name=inviter.full_name if inviter else None,
        joined_at=row.joined_at,
    )


def my_memberships(
    members: MemberRepository,
    orgs: OrgRepository,
    access: AccessControl,
    users: UserDirectory,
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
        inviter_id = getattr(link, "invited_by", None)
        inviter = (
            users.get_brief(inviter_id) if inviter_id is not None else None
        )
        out.append(
            MembershipSnapshot(
                org_id=org.id,
                org_name=org.name,
                org_slug=org.slug,
                roles=roles_of(org, user_id, access.role_map(org.id)),
                status=link.status,
                invited_by_name=inviter.full_name if inviter else None,
                joined_at=link.joined_at,
            )
        )
    out.sort(key=lambda item: item.joined_at, reverse=True)
    return out
