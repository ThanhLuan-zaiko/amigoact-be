"""Routes for the roles of an organization and the roles members hold."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from src.auth.deps import CurrentPrincipal, Db
from src.organizations import roles
from src.organizations.access import require_member, require_permission
from src.organizations.permissions import (
    ROLES_ASSIGN,
    ROLES_CREATE,
    ROLES_DELETE,
    ROLES_UPDATE,
)
from src.organizations.role_schemas import (
    MemberRoleBadge,
    MemberRolesRequest,
    RoleCreateRequest,
    RoleList,
    RoleOrderRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from src.organizations.service import load_organization
from src.validation import Uuid7

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]

router = APIRouter(prefix="/organizations", tags=["roles"])


@router.get("/{slug}/roles")
def list_roles(slug: Slug, principal: CurrentPrincipal, db: Db) -> RoleList:
    org = load_organization(db, slug)
    access = require_member(db, org, principal.user.id)
    return roles.list_roles(db, org, access)


@router.post("/{slug}/roles", status_code=status.HTTP_201_CREATED)
def create_role(
    slug: Slug, payload: RoleCreateRequest, principal: CurrentPrincipal, db: Db
) -> RoleResponse:
    org = load_organization(db, slug)
    access = require_permission(db, org, principal.user.id, ROLES_CREATE)
    return roles.create_role(db, org, access, payload)


@router.put("/{slug}/roles/order")
def reorder_roles(
    slug: Slug, payload: RoleOrderRequest, principal: CurrentPrincipal, db: Db
) -> RoleList:
    org = load_organization(db, slug)
    access = require_permission(db, org, principal.user.id, ROLES_UPDATE)
    return roles.reorder_roles(db, org, access, payload)


@router.patch("/{slug}/roles/{role_id}")
def update_role(
    slug: Slug,
    role_id: Uuid7,
    payload: RoleUpdateRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> RoleResponse:
    org = load_organization(db, slug)
    access = require_permission(db, org, principal.user.id, ROLES_UPDATE)
    return roles.update_role(db, org, access, role_id, payload)


@router.delete("/{slug}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    slug: Slug, role_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    org = load_organization(db, slug)
    access = require_permission(db, org, principal.user.id, ROLES_DELETE)
    roles.delete_role(db, org, access, role_id)


@router.put("/{slug}/members/{user_id}/roles")
def set_member_roles(
    slug: Slug,
    user_id: Uuid7,
    payload: MemberRolesRequest,
    principal: CurrentPrincipal,
    db: Db,
) -> list[MemberRoleBadge]:
    org = load_organization(db, slug)
    access = require_permission(db, org, principal.user.id, ROLES_ASSIGN)
    return roles.set_member_roles(
        db, org, access, principal.user.id, user_id, payload.role_ids
    )
