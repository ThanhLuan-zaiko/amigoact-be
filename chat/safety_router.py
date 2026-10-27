"""HTTP layer for chat safety: attachment policy and member timeouts."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from chat.safety_schemas import (
    AttachPolicyRequest,
    AttachPolicyResponse,
    SafetyResponse,
    TimeoutRequest,
    TimeoutResponse,
)
from chat.safety_service import ChatSafetyService, TimeoutView
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_chat import get_chat_safety_service

router = APIRouter(tags=["chat"])


def _to_timeout(view: TimeoutView) -> TimeoutResponse:
    return TimeoutResponse(
        user_id=view.user_id,
        user_name=view.user_name,
        until=view.until,
        set_by=view.set_by,
        reason=view.reason,
    )


@router.get("/orgs/{org_id}/chat/safety", response_model=SafetyResponse)
def get_safety(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatSafetyService = Depends(get_chat_safety_service),
) -> SafetyResponse:
    """Attachment policy, the caller's own timeout, and (for staff) the list."""
    view = service.overview(org_id, current_user.id)
    return SafetyResponse(
        attach_restricted=view.attach_restricted,
        my_timeout_until=view.my_timeout_until,
        timeouts=[_to_timeout(item) for item in view.timeouts],
    )


@router.put(
    "/orgs/{org_id}/chat/safety/attachments",
    response_model=AttachPolicyResponse,
)
def set_attach_policy(
    org_id: UUID,
    body: AttachPolicyRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatSafetyService = Depends(get_chat_safety_service),
) -> AttachPolicyResponse:
    """Owner or chat:channel holder limits attachments to chat:attach."""
    return AttachPolicyResponse(
        attach_restricted=service.set_attach_restricted(
            org_id, current_user.id, body.restricted
        )
    )


@router.put(
    "/orgs/{org_id}/chat/safety/timeouts/{user_id}",
    response_model=TimeoutResponse,
)
def timeout_member(
    org_id: UUID,
    user_id: UUID,
    body: TimeoutRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatSafetyService = Depends(get_chat_safety_service),
) -> TimeoutResponse:
    """Mute one member in the org chat for a bounded time."""
    return _to_timeout(
        service.timeout(org_id, current_user.id, user_id, body.minutes, body.reason)
    )


@router.delete(
    "/orgs/{org_id}/chat/safety/timeouts/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def lift_timeout(
    org_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChatSafetyService = Depends(get_chat_safety_service),
) -> Response:
    """Lift a member's chat timeout early."""
    service.lift(org_id, current_user.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
