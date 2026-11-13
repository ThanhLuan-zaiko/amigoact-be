"""Who may do what in an organization.

The owner is organizations.owner_id and holds every permission. Everyone else gets
the permissions of the roles they hold in user_roles, like Discord. A role has a
position, and a person may only change roles and people below their own top role.
A member who holds no permission is a plain member. A member who holds at least
one is an "admin" for the coarse role the interface shows.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.organizations import (
    Organization,
    OrganizationMember,
    Role,
    RolePermission,
    UserRole,
)
from src.organizations.permissions import ADMINISTRATOR, ALL
from src.organizations.schemas import OrgRole

ADMIN_ROLE_CODE = "admin"
ACTIVE = "active"
# Above every role position, so the owner outranks everyone.
OWNER_POSITION = 10**9


@dataclass(frozen=True)
class Access:
    status: str | None
    role: OrgRole | None
    permissions: frozenset[str] = field(default_factory=frozenset)
    # Position of the highest role held. The owner outranks every role.
    top_position: int = 0

    def has(self, permission: str) -> bool:
        return ADMINISTRATOR in self.permissions or permission in self.permissions

    def has_any(self, module: str) -> bool:
        """Holds any permission of the module, such as every "activities.*" code."""
        prefix = f"{module}."
        return ADMINISTRATOR in self.permissions or any(
            code.startswith(prefix) for code in self.permissions
        )

    @property
    def can_manage(self) -> bool:
        """Holds at least one permission. Specific rules use has()."""
        return bool(self.permissions)


def resolve_role(
    *, is_owner: bool, is_admin: bool, status: str | None
) -> OrgRole | None:
    """Only an active member has a role, even if an old role row is still there."""
    if status != ACTIVE:
        return None
    if is_owner:
        return "owner"
    return "admin" if is_admin else "member"


def _live_grants(org_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        UserRole.org_id == org_id,
        or_(UserRole.expires_at.is_(None), UserRole.expires_at > datetime.now(UTC)),
    )


def _holdings(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> tuple[dict[uuid.UUID, set[str]], dict[uuid.UUID, int]]:
    """Permissions and top role position per user, from roles that have not expired."""
    query = (
        select(UserRole.user_id, Role.position, RolePermission.permission_code)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .where(*_live_grants(org_id))
    )
    if user_id is not None:
        query = query.where(UserRole.user_id == user_id)
    permissions: dict[uuid.UUID, set[str]] = defaultdict(set)
    top: dict[uuid.UUID, int] = {}
    for holder, position, code in db.execute(query):
        top[holder] = max(top.get(holder, 0), position)
        if code is not None:
            permissions[holder].add(code)
    return permissions, top


def permissions_by_user(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    """Every role holder of the organization. The owner is not in it."""
    return _holdings(db, org_id)[0]


def staff_user_ids(
    db: Session, org_id: uuid.UUID, permission: str | None = None
) -> set[uuid.UUID]:
    """Role holders with the permission, or with any permission when none is named.

    The owner holds every permission without a role, so callers add the owner.
    """
    found = permissions_by_user(db, org_id)
    return {
        user_id
        for user_id, held in found.items()
        if held and (permission is None or ADMINISTRATOR in held or permission in held)
    }


def staff_org_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Organizations where this user holds a role with at least one permission."""
    rows = db.execute(
        select(UserRole.org_id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .where(
            UserRole.user_id == user_id,
            or_(UserRole.expires_at.is_(None), UserRole.expires_at > datetime.now(UTC)),
        )
    )
    return {row[0] for row in rows}


def get_access(db: Session, org: Organization, user_id: uuid.UUID) -> Access:
    member = db.get(OrganizationMember, (org.id, user_id))
    member_status = member.status if member else None
    if member_status != ACTIVE:
        return Access(status=member_status, role=None)
    if org.owner_id == user_id:
        return Access(
            status=member_status,
            role="owner",
            permissions=ALL,
            top_position=OWNER_POSITION,
        )
    held, top = _holdings(db, org.id, user_id)
    permissions = frozenset(held.get(user_id, ()))
    return Access(
        status=member_status,
        role=resolve_role(
            is_owner=False, is_admin=bool(permissions), status=member_status
        ),
        permissions=permissions,
        top_position=top.get(user_id, 0),
    )


def require_member(db: Session, org: Organization, user_id: uuid.UUID) -> Access:
    access = get_access(db, org, user_id)
    if access.role is None:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    return access


def require_permission(
    db: Session, org: Organization, user_id: uuid.UUID, permission: str
) -> Access:
    access = get_access(db, org, user_id)
    if not access.has(permission):
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
    return access


def require_owner(org: Organization, user_id: uuid.UUID) -> None:
    if org.owner_id != user_id:
        raise api_error(status.HTTP_403_FORBIDDEN, "organization_forbidden")
