"""Custom roles of an organization and who holds them, in the style of Discord.

A role is a named bundle of permissions with a position. Whoever holds manage_roles
may create, change, delete, and hand out roles that sit below their own top role,
and only permissions they hold themselves. The owner is above every role.
"""

import uuid
from collections import defaultdict

from fastapi import status
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.models.organizations import (
    Organization,
    OrganizationMember,
    Role,
    RolePermission,
    UserRole,
)
from src.organizations import signals
from src.organizations.access import ACTIVE, Access, get_access, staff_user_ids
from src.organizations.role_schemas import (
    MAX_ROLES,
    MemberRoleBadge,
    RoleCreateRequest,
    RoleList,
    RoleOrderRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from src.validation import validation_failure


def _outranks(access: Access, position: int) -> bool:
    return access.top_position > position


def _require_below(access: Access, role: Role) -> None:
    if not _outranks(access, role.position):
        raise api_error(status.HTTP_403_FORBIDDEN, "role_hierarchy")


def _require_holdable(access: Access, codes: set[str]) -> None:
    """Nobody hands out a permission they do not hold."""
    if any(not access.has(code) for code in codes):
        raise api_error(status.HTTP_403_FORBIDDEN, "permission_not_held")


def _org_roles(db: Session, org_id: uuid.UUID) -> list[Role]:
    return list(
        db.scalars(
            select(Role)
            .where(Role.org_id == org_id)
            .order_by(Role.position.desc(), Role.id)
        )
    )


def _load_role(db: Session, org_id: uuid.UUID, role_id: uuid.UUID) -> Role:
    role = db.get(Role, role_id, with_for_update=True)
    if role is None or role.org_id != org_id:
        raise api_error(status.HTTP_404_NOT_FOUND, "role_not_found")
    return role


def _permission_map(
    db: Session, role_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    found: dict[uuid.UUID, list[str]] = defaultdict(list)
    rows = db.execute(
        select(RolePermission.role_id, RolePermission.permission_code)
        .where(RolePermission.role_id.in_(role_ids))
        .order_by(RolePermission.permission_code)
    )
    for role_id, code in rows:
        found[role_id].append(code)
    return found


def _holder_counts(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = db.execute(
        select(UserRole.role_id, func.count())
        .join(
            OrganizationMember,
            (OrganizationMember.org_id == UserRole.org_id)
            & (OrganizationMember.user_id == UserRole.user_id),
        )
        .where(UserRole.org_id == org_id, OrganizationMember.status == ACTIVE)
        .group_by(UserRole.role_id)
    )
    return {role_id: count for role_id, count in rows}


def _response(
    role: Role, codes: list[str], members: int, access: Access
) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        name=role.name,
        color=role.color,
        position=role.position,
        permissions=codes,
        member_count=members,
        below_you=_outranks(access, role.position),
    )


def list_roles(db: Session, org: Organization, access: Access) -> RoleList:
    roles = _org_roles(db, org.id)
    codes = _permission_map(db, [role.id for role in roles])
    counts = _holder_counts(db, org.id)
    return RoleList(
        items=[
            _response(role, codes.get(role.id, []), counts.get(role.id, 0), access)
            for role in roles
        ]
    )


def _require_free_name(
    db: Session, org_id: uuid.UUID, name: str, ignore: uuid.UUID | None = None
) -> None:
    query = select(Role.id).where(
        Role.org_id == org_id, func.lower(Role.name) == name.lower()
    )
    if ignore is not None:
        query = query.where(Role.id != ignore)
    if db.scalar(query) is not None:
        raise api_error(status.HTTP_409_CONFLICT, "role_name_taken")


def _lock_organization(db: Session, org: Organization) -> None:
    """Serialize role changes of one organization, so positions and limits hold."""
    db.execute(
        select(Organization.id).where(Organization.id == org.id).with_for_update()
    )


def create_role(
    db: Session, org: Organization, access: Access, payload: RoleCreateRequest
) -> RoleResponse:
    codes: set[str] = set(payload.permissions)
    _require_holdable(access, codes)
    _lock_organization(db, org)
    if len(_org_roles(db, org.id)) >= MAX_ROLES:
        raise api_error(status.HTTP_409_CONFLICT, "role_limit_reached")
    _require_free_name(db, org.id, payload.name)
    # The new role goes to the bottom: every other role moves up by one.
    db.execute(
        update(Role).where(Role.org_id == org.id).values(position=Role.position + 1)
    )
    role = Role(
        id=uuid.uuid7(),
        org_id=org.id,
        code=f"role-{uuid.uuid7().hex[-12:]}",
        name=payload.name,
        color=payload.color,
        is_system=False,
        position=1,
    )
    db.add(role)
    db.flush()
    db.add_all(
        RolePermission(role_id=role.id, permission_code=c) for c in sorted(codes)
    )
    signals.roles_changed(db, org.id)
    db.commit()
    return _response(role, sorted(codes), 0, access)


def _refresh_holders(db: Session, org: Organization, user_ids: set[uuid.UUID]) -> None:
    """Holders reload their view, and those who are no longer staff lose manager topics."""
    staff = staff_user_ids(db, org.id)
    for user_id in sorted(user_ids):
        signals.membership_changed(db, org.id, user_id)
        if user_id not in staff and user_id != org.owner_id:
            signals.lose_manager_role(db, org.id, user_id)
    signals.members_changed(db, org.id)
    signals.roles_changed(db, org.id)


def _holders(db: Session, role_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(select(UserRole.user_id).where(UserRole.role_id == role_id)))


def update_role(
    db: Session,
    org: Organization,
    access: Access,
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
) -> RoleResponse:
    role = _load_role(db, org.id, role_id)
    _require_below(access, role)
    current = set(_permission_map(db, [role.id]).get(role.id, []))
    if payload.permissions is not None:
        wanted: set[str] = set(payload.permissions)
        _require_holdable(access, wanted ^ current)
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(
            RolePermission(role_id=role.id, permission_code=c) for c in sorted(wanted)
        )
        current = wanted
    if payload.name is not None and payload.name != role.name:
        _require_free_name(db, org.id, payload.name, ignore=role.id)
        role.name = payload.name
    if payload.color is not None:
        role.color = payload.color
    db.flush()
    holders = _holders(db, role.id)
    _refresh_holders(db, org, holders)
    db.commit()
    return _response(role, sorted(current), len(holders), access)


def delete_role(
    db: Session, org: Organization, access: Access, role_id: uuid.UUID
) -> None:
    role = _load_role(db, org.id, role_id)
    _require_below(access, role)
    holders = _holders(db, role.id)
    db.delete(role)
    db.flush()
    _refresh_holders(db, org, holders)
    db.commit()


def reorder_roles(
    db: Session, org: Organization, access: Access, payload: RoleOrderRequest
) -> RoleList:
    """Reassign the positions of the roles the caller may move, in the order given."""
    _lock_organization(db, org)
    roles = {role.id: role for role in _org_roles(db, org.id)}
    movable = [role for role in roles.values() if _outranks(access, role.position)]
    if set(payload.role_ids) != {role.id for role in movable}:
        raise validation_failure({"role_ids": "role_order_invalid"})
    slots = sorted((role.position for role in movable), reverse=True)
    for role_id, position in zip(payload.role_ids, slots, strict=True):
        roles[role_id].position = position
    signals.roles_changed(db, org.id)
    db.commit()
    return list_roles(db, org, access)


def member_role_badges(
    db: Session, org_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MemberRoleBadge]]:
    """The roles shown beside each member, highest first."""
    found: dict[uuid.UUID, list[MemberRoleBadge]] = defaultdict(list)
    if not user_ids:
        return found
    rows = db.execute(
        select(UserRole.user_id, Role.id, Role.name, Role.color)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.org_id == org_id, UserRole.user_id.in_(user_ids))
        .order_by(Role.position.desc(), Role.id)
    )
    for user_id, role_id, name, color in rows:
        found[user_id].append(MemberRoleBadge(id=role_id, name=name, color=color))
    return found


def set_member_roles(
    db: Session,
    org: Organization,
    access: Access,
    actor_id: uuid.UUID,
    user_id: uuid.UUID,
    role_ids: list[uuid.UUID],
) -> list[MemberRoleBadge]:
    """Replace the roles of a member. Only roles below the caller's own can change."""
    if org.owner_id == user_id:
        raise api_error(status.HTTP_409_CONFLICT, "owner_role_locked")
    member = db.get(OrganizationMember, (org.id, user_id), with_for_update=True)
    if member is None or member.status != ACTIVE:
        raise api_error(status.HTTP_404_NOT_FOUND, "member_not_found")
    if not _outranks(access, get_access(db, org, user_id).top_position):
        raise api_error(status.HTTP_403_FORBIDDEN, "role_hierarchy")
    roles = {role.id: role for role in _org_roles(db, org.id)}
    if any(role_id not in roles for role_id in role_ids):
        raise api_error(status.HTTP_404_NOT_FOUND, "role_not_found")
    held = set(
        db.scalars(
            select(UserRole.role_id).where(
                UserRole.org_id == org.id, UserRole.user_id == user_id
            )
        )
    )
    wanted = set(role_ids)
    for role_id in wanted ^ held:
        # A role of the target that was deleted a moment ago has nothing to check.
        if role_id in roles:
            _require_below(access, roles[role_id])
    if held - wanted:
        db.execute(
            delete(UserRole).where(
                UserRole.org_id == org.id,
                UserRole.user_id == user_id,
                UserRole.role_id.in_(held - wanted),
            )
        )
    if wanted - held:
        db.execute(
            insert(UserRole)
            .values(
                [
                    {
                        "org_id": org.id,
                        "user_id": user_id,
                        "role_id": role_id,
                        "granted_by": actor_id,
                    }
                    for role_id in sorted(wanted - held)
                ]
            )
            .on_conflict_do_nothing()
        )
    db.flush()
    _refresh_holders(db, org, {user_id})
    badges = member_role_badges(db, org.id, [user_id])[user_id]
    db.commit()
    return badges
