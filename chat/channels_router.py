"""HTTP layer for named org channels: thin routing over ChannelService.

Room I/O stays on /chat/rooms/{room_id} (channel_id doubles as the
room id); this router only owns channel metadata and restricted rosters.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from chat.channel_service import ChannelService
from chat.schemas import (
    ChannelCreateRequest,
    ChannelListResponse,
    ChannelMemberAddRequest,
    ChannelMemberListResponse,
    ChannelMemberResponse,
    ChannelResponse,
    ChannelUpdateRequest,
)
from core.dependencies import CurrentUser, get_current_user
from core.dependencies_chat import get_channel_service

router = APIRouter(tags=["chat"])


def _to_channel(snapshot) -> ChannelResponse:  # noqa: ANN001
    return ChannelResponse(
        channel_id=snapshot.channel_id,
        org_id=snapshot.org_id,
        name=snapshot.name,
        topic=snapshot.topic,
        kind=snapshot.kind,
        post_policy=snapshot.post_policy,
        visibility=snapshot.visibility,
        created_by=snapshot.created_by,
        created_at=snapshot.created_at,
        archived_at=snapshot.archived_at,
    )


def _to_member(snapshot) -> ChannelMemberResponse:  # noqa: ANN001
    return ChannelMemberResponse(
        user_id=snapshot.user_id,
        full_name=snapshot.full_name,
        avatar_url=snapshot.avatar_url,
        added_at=snapshot.added_at,
    )


@router.get(
    "/orgs/{org_id}/chat/channels", response_model=ChannelListResponse
)
def list_channels(
    org_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> ChannelListResponse:
    """Channels the caller may see: org-wide plus their restricted seats."""
    return ChannelListResponse(
        items=[
            _to_channel(row)
            for row in service.list_channels(org_id, current_user.id)
        ]
    )


@router.post(
    "/orgs/{org_id}/chat/channels",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    org_id: UUID,
    body: ChannelCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> ChannelResponse:
    """Managers create a named channel (optionally restricted)."""
    return _to_channel(
        service.create_channel(
            org_id,
            current_user.id,
            body.name,
            body.topic,
            body.kind,
            body.post_policy,
            body.visibility,
            body.member_ids,
        )
    )


@router.patch(
    "/orgs/{org_id}/chat/channels/{channel_id}",
    response_model=ChannelResponse,
)
def update_channel(
    org_id: UUID,
    channel_id: UUID,
    body: ChannelUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> ChannelResponse:
    """Managers rename, retarget, or (un)archive a channel."""
    return _to_channel(
        service.update_channel(
            org_id,
            channel_id,
            current_user.id,
            name=body.name,
            topic=body.topic,
            kind=body.kind,
            post_policy=body.post_policy,
            visibility=body.visibility,
            archived=body.archived,
        )
    )


@router.get(
    "/orgs/{org_id}/chat/channels/{channel_id}/members",
    response_model=ChannelMemberListResponse,
)
def list_channel_members(
    org_id: UUID,
    channel_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> ChannelMemberListResponse:
    """Roster of one restricted channel."""
    return ChannelMemberListResponse(
        items=[
            _to_member(row)
            for row in service.list_channel_members(
                org_id, channel_id, current_user.id
            )
        ]
    )


@router.post(
    "/orgs/{org_id}/chat/channels/{channel_id}/members",
    response_model=ChannelMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_channel_member(
    org_id: UUID,
    channel_id: UUID,
    body: ChannelMemberAddRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> ChannelMemberResponse:
    """Managers seat one org member on a restricted channel."""
    return _to_member(
        service.add_channel_member(
            org_id, channel_id, current_user.id, body.user_id
        )
    )


@router.delete(
    "/orgs/{org_id}/chat/channels/{channel_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_channel_member(
    org_id: UUID,
    channel_id: UUID,
    user_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    service: ChannelService = Depends(get_channel_service),
) -> Response:
    """Managers revoke one restricted-channel seat."""
    service.remove_channel_member(
        org_id, channel_id, current_user.id, user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
