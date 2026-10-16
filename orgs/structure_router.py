"""HTTP layer for the org campus/department structure."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, status

from core.dependencies import CurrentUser, get_current_user
from core.dependencies_workspace import get_structure_service
from orgs.structure_schemas import (
    CampusBody,
    CampusPatchBody,
    CampusResponse,
    DepartmentBody,
    DepartmentPatchBody,
    DepartmentResponse,
    OrgTypeResponse,
    StudentLookupResponse,
)

if TYPE_CHECKING:
    from orgs.structure_service import StructureService

router = APIRouter(tags=["orgs"])


def _campus(row) -> CampusResponse:
    return CampusResponse(
        id=row.id if hasattr(row, "id") else row.campus_id,
        org_id=row.org_id,
        name=row.name,
        address=getattr(row, "address", None),
        status=getattr(row, "status", "active") or "active",
    )


def _department(row) -> DepartmentResponse:
    return DepartmentResponse(
        id=row.id if hasattr(row, "id") else row.department_id,
        org_id=row.org_id,
        campus_id=row.campus_id,
        name=row.name,
        code=row.code,
        status=getattr(row, "status", "active") or "active",
    )


@router.get(
    "/orgs/{org_id}/campuses", response_model=list[CampusResponse]
)
def list_campuses(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> list[CampusResponse]:
    """Members list the org's campuses."""
    return [_campus(r) for r in service.list_campuses(org_id, current.id)]


@router.post(
    "/orgs/{org_id}/campuses",
    response_model=CampusResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_campus(
    org_id: UUID,
    body: CampusBody,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> CampusResponse:
    """Manager creates a campus."""
    return _campus(
        service.create_campus(
            org_id, current.id, body.name, body.address
        )
    )


@router.patch(
    "/orgs/{org_id}/campuses/{campus_id}",
    response_model=CampusResponse,
)
def update_campus(
    org_id: UUID,
    campus_id: UUID,
    body: CampusPatchBody,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> CampusResponse:
    """Manager renames/readdresses/archives a campus."""
    return _campus(
        service.update_campus(
            org_id, campus_id, current.id,
            body.name, body.address, body.status,
        )
    )


@router.get(
    "/orgs/{org_id}/departments",
    response_model=list[DepartmentResponse],
)
def list_departments(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> list[DepartmentResponse]:
    """Members list the org's departments across campuses."""
    return [
        _department(r)
        for r in service.list_departments(org_id, current.id)
    ]


@router.post(
    "/orgs/{org_id}/departments",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    org_id: UUID,
    body: DepartmentBody,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> DepartmentResponse:
    """Manager creates a department under an optional campus."""
    return _department(
        service.create_department(
            org_id, current.id, body.name, body.code, body.campus_id
        )
    )


@router.patch(
    "/orgs/{org_id}/departments/{department_id}",
    response_model=DepartmentResponse,
)
def update_department(
    org_id: UUID,
    department_id: UUID,
    body: DepartmentPatchBody,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> DepartmentResponse:
    """Manager edits or moves a department between campuses."""
    return _department(
        service.update_department(
            org_id, department_id, current.id,
            body.name, body.code, body.campus_id, body.status,
        )
    )


@router.get(
    "/orgs/{org_id}/students/by-code",
    response_model=StudentLookupResponse,
)
def lookup_student(
    org_id: UUID,
    code: str,
    campus_id: UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    service: StructureService = Depends(get_structure_service),
) -> StudentLookupResponse:
    """Manager resolves a student code to a user id."""
    return StudentLookupResponse(
        user_id=service.lookup_student(
            org_id, current.id, code, campus_id
        ),
        student_code=code,
    )


@router.get("/org-types", response_model=list[OrgTypeResponse])
def list_org_types(
    service: StructureService = Depends(get_structure_service),
) -> list[OrgTypeResponse]:
    """Public kind catalog for the directory filter and create form."""
    return [
        OrgTypeResponse(
            code=r.code, name=r.name, sort_order=r.sort_order or 0
        )
        for r in service.list_types()
    ]
