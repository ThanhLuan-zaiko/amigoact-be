"""Who may do what in an organization.

The owner is organizations.owner_id. An admin holds the organization's admin role
in user_roles. Every other active member is a plain member.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.organizations import Organization, OrganizationMember, Role, UserRole
from src.organizations.schemas import OrgRole

ADMIN_ROLE_CODE = "admin"
ACTIVE = "active"


@dataclass(frozen=True)
class Access:
    status: str | None
    role: OrgRole | None

    @property
    def can_manage(self) -> bool:
        return self.role in ("owner", "admin")


def resolve_role(
    *, is_owner: bool, is_admin: bool, status: str | None
) -> OrgRole | None:
    """Only an active member has a role, even if an old role row is still there."""
    if status != ACTIVE:
        return None
    if is_owner:
        return "owner"
    return "admin" if is_admin else "member"


def admin_user_ids(db: Session, org_id: uuid.UUID) -> set[uuid.UUID]:
    rows = db.scalars(
        select(UserRole.user_id)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.org_id == org_id,
            Role.code == ADMIN_ROLE_CODE,
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > datetime.now(UTC)),
        )
    )
    return set(rows)


def get_access(db: Session, org: Organization, user_id: uuid.UUID) -> Access:
    member = db.get(OrganizationMember, (org.id, user_id))
    member_status = member.status if member else None
    return Access(
        status=member_status,
        role=resolve_role(
            is_owner=org.owner_id == user_id,
            is_admin=user_id in admin_user_ids(db, org.id),
            status=member_status,
        ),
    )


def require_member(db: Session, org: Organization, user_id: uuid.UUID) -> Access:
    access = get_access(db, org, user_id)
    if access.role is None:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    return access


def require_manager(db: Session, org: Organization, user_id: uuid.UUID) -> Access:
    access = get_access(db, org, user_id)
    if not access.can_manage:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    return access


def require_owner(org: Organization, user_id: uuid.UUID) -> None:
    if org.owner_id != user_id:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
