"""HTTP surface for the org audit feed (thin router)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from audit.schemas import AuditEntryResponse, AuditFeedResponse
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_features import get_audit_service

if TYPE_CHECKING:
    from audit.service import AuditService

router = APIRouter(tags=["audit"])


@router.get("/orgs/{org_id}/audit", response_model=AuditFeedResponse)
def org_audit(
    org_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    service: AuditService = Depends(get_audit_service),
) -> AuditFeedResponse:
    """Manager-only newest-first authorization trail for one org."""
    entries = service.feed(org_id, current.id, limit)
    return AuditFeedResponse(
        items=[
            AuditEntryResponse(
                log_id=entry.log_id,
                occurred_at=entry.occurred_at,
                actor_id=entry.actor_id,
                actor_name=entry.actor_name,
                action=entry.action,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
                result=entry.result,
                detail=entry.detail,
            )
            for entry in entries
        ]
    )
