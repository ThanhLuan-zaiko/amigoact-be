"""HTTP layer for per-schedule capacity slots."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, status

from activities.schemas import SlotBody, SlotItem
from core.dependencies import (
    CurrentUser,
    get_current_user,
    get_optional_user,
)
from core.dependencies_workspace import get_slot_service

if TYPE_CHECKING:
    from activities.slot_service import SlotService

router = APIRouter(tags=["activities"])


def _slot_response(rows) -> list[SlotItem]:  # noqa: ANN001, ANN202
    return [
        SlotItem(
            slot_id=s.slot_id,
            schedule_id=s.schedule_id,
            title=s.title,
            capacity=s.capacity,
            registered=getattr(s, "registered", 0) or 0,
            start_at=s.start_at,
            end_at=s.end_at,
        )
        for s in rows
    ]


@router.get(
    "/orgs/{org_id}/activities/{activity_id}/slots",
    response_model=list[SlotItem],
)
def list_slots(
    org_id: UUID,
    activity_id: UUID,
    viewer: CurrentUser | None = Depends(get_optional_user),
    service: SlotService = Depends(get_slot_service),
) -> list[SlotItem]:
    """Slots with live counts; public while registration is open."""
    return _slot_response(
        service.list_for_activity(
            org_id, activity_id, viewer.id if viewer else None
        )
    )


@router.post(
    "/orgs/{org_id}/activities/{activity_id}/schedules/{schedule_id}/slots",
    response_model=SlotItem,
    status_code=status.HTTP_201_CREATED,
)
def create_slot(
    org_id: UUID,
    activity_id: UUID,
    schedule_id: UUID,
    body: SlotBody,
    current: CurrentUser = Depends(get_current_user),
    service: SlotService = Depends(get_slot_service),
) -> SlotItem:
    """Managers add one capacity-bounded slot to a schedule."""
    row = service.create_slot(
        org_id, activity_id, schedule_id, current.id,
        body.title, body.capacity, body.start_at, body.end_at,
    )
    return _slot_response([row])[0]


@router.delete(
    "/orgs/{org_id}/activities/{activity_id}/schedules/{schedule_id}/slots/{slot_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_slot(
    org_id: UUID,
    activity_id: UUID,
    schedule_id: UUID,
    slot_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: SlotService = Depends(get_slot_service),
) -> None:
    """Managers remove a slot once no live registration points at it."""
    service.delete_slot(
        org_id, activity_id, schedule_id, slot_id, current.id
    )
