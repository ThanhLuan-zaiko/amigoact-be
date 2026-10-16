"""HTTP layer for platform admin: parsing and status codes only."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from admin.schemas import (
    ModerationItemResponse,
    ModerationReviewRequest,
    AdminOrgItem,
    AdminOrgPage,
    AdminStatusResponse,
    AdminUserItem,
    GrantAdminRequest,
    RejectOrgRequest,
)
from core.dependencies import (
    CurrentUser,
    get_current_user,
)
from core.dependencies_features import get_admin_service

if TYPE_CHECKING:
    from admin.service import AdminService, AdminOrgSnapshot, AdminUserSnapshot

router = APIRouter(prefix="/admin", tags=["admin"])


def _org_item(snapshot: AdminOrgSnapshot) -> AdminOrgItem:
    return AdminOrgItem(
        id=snapshot.id,
        name=snapshot.name,
        slug=snapshot.slug,
        kind=snapshot.kind,
        status=snapshot.status,
        legal_status=snapshot.legal_status,
        tax_code=snapshot.tax_code,
        legal_rep_name=snapshot.legal_rep_name,
        owner_id=snapshot.owner_id,
        owner_name=snapshot.owner_name,
        owner_email=snapshot.owner_email,
        verified_at=snapshot.verified_at,
        created_at=snapshot.created_at,
    )


def _user_item(snapshot: AdminUserSnapshot) -> AdminUserItem:
    return AdminUserItem(
        user_id=snapshot.user_id,
        full_name=snapshot.full_name,
        email=snapshot.email,
    )


@router.get("/me", response_model=AdminStatusResponse)
def admin_status(
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> AdminStatusResponse:
    """Frontend gate: does the caller see admin surfaces?"""
    return AdminStatusResponse(
        is_admin=service.is_admin(current.id, current.email)
    )


@router.get("/orgs", response_model=AdminOrgPage)
def list_orgs_by_status(
    status: str = Query(default="pending", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> AdminOrgPage:
    """Verification queue bucket (default: pending dossiers)."""
    items = service.list_orgs(
        current.id, current.email, status=status, limit=limit
    )
    return AdminOrgPage(items=[_org_item(item) for item in items], total=len(items))


@router.post("/orgs/{org_id}/verify", response_model=AdminOrgItem)
def verify_org(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> AdminOrgItem:
    """Approve one pending business org."""
    return _org_item(service.verify_org(current.id, current.email, org_id))


@router.post("/orgs/{org_id}/reject", response_model=AdminOrgItem)
def reject_org(
    org_id: UUID,
    body: RejectOrgRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> AdminOrgItem:
    """Reject one pending business org with an optional reason."""
    return _org_item(
        service.reject_org(current.id, current.email, org_id, body.reason)
    )


@router.get("/admins", response_model=list[AdminUserItem])
def list_admins(
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> list[AdminUserItem]:
    """Granted platform administrators (bootstrap emails excluded)."""
    return [
        _user_item(item)
        for item in service.list_admins(current.id, current.email)
    ]


@router.post("/admins", status_code=204)
def grant_admin(
    body: GrantAdminRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    """Promote an account to platform administrator by email."""
    service.grant_admin_by_email(current.id, current.email, body.email)
    return Response(status_code=204)


@router.delete("/admins/{user_id}", status_code=204)
def revoke_admin(
    user_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    """Demote a platform administrator."""
    service.revoke_admin(current.id, current.email, user_id)
    return Response(status_code=204)


@router.get("/moderation", response_model=list[ModerationItemResponse])
def list_moderation(
    status: str = "pending",
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> list[ModerationItemResponse]:
    """List media moderation rows of one status bucket."""
    items = service.list_moderation(current.id, current.email, status)
    return [ModerationItemResponse(**vars(item)) for item in items]


@router.post("/moderation/{moderation_id}/review", status_code=204)
def review_moderation(
    moderation_id: UUID,
    body: ModerationReviewRequest,
    current: CurrentUser = Depends(get_current_user),
    service: AdminService = Depends(get_admin_service),
) -> Response:
    """Approve or reject one queued media asset."""
    service.review_moderation(
        current.id, current.email, body.from_status, body.created_at,
        moderation_id, body.approve, body.note,
    )
    return Response(status_code=204)
