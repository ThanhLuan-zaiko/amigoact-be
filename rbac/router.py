"""Org role endpoints: thin HTTP layer over OrgRoleService."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_role_service,
)
from rbac.catalog import ASSIGNABLE_PERMISSIONS
from rbac.roles_service import OrgRoleService, OrgRoleView
from rbac.schemas import (
    CreateRoleRequest,
    OrgRoleListResponse,
    OrgRoleResponse,
    UpdateRoleRequest,
)

router = APIRouter(tags=["rbac"])


def _to_role(row: OrgRoleView) -> OrgRoleResponse:
    return OrgRoleResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        permissions=row.permissions,
        member_count=row.member_count,
        is_system=row.is_system,
    )


@router.get(
    "/orgs/{org_id}/roles",
    response_model=OrgRoleListResponse,
    status_code=status.HTTP_200_OK,
)
def list_roles(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: OrgRoleService = Depends(get_role_service),
) -> OrgRoleListResponse:
    """List the org's roles (system admin plus customs); members only."""
    return OrgRoleListResponse(
        items=[
            _to_role(row)
            for row in service.list_roles(org_id, current_user.id)
        ],
        assignable_permissions=sorted(ASSIGNABLE_PERMISSIONS),
    )


@router.post(
    "/orgs/{org_id}/roles",
    response_model=OrgRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_role(
    org_id: UUID,
    body: CreateRoleRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: OrgRoleService = Depends(get_role_service),
) -> OrgRoleResponse:
    """Owner or member:role-assign holder creates a custom role."""
    return _to_role(
        service.create_role(
            org_id,
            current_user.id,
            body.name,
            body.description,
            body.permissions,
        )
    )


@router.patch(
    "/orgs/{org_id}/roles/{role_id}",
    response_model=OrgRoleResponse,
    status_code=status.HTTP_200_OK,
)
def update_role(
    org_id: UUID,
    role_id: UUID,
    body: UpdateRoleRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: OrgRoleService = Depends(get_role_service),
) -> OrgRoleResponse:
    """Rename, re-describe or re-permission a custom role."""
    return _to_role(
        service.update_role(
            org_id,
            current_user.id,
            role_id,
            name=body.name,
            description=body.description,
            permissions=body.permissions,
        )
    )


@router.delete(
    "/orgs/{org_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_role(
    org_id: UUID,
    role_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: OrgRoleService = Depends(get_role_service),
) -> Response:
    """Drop a custom role and revoke every assignment it had."""
    service.delete_role(org_id, current_user.id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
