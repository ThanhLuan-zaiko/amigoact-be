"""Routes for an organization's channels, direct messages, and unread counts."""

from typing import Annotated

from fastapi import APIRouter, Path, status

from src.auth.deps import CurrentPrincipal, Db
from src.chat import channels, dms, room_state
from src.chat.hub import revoke
from src.chat.rooms import load_room
from src.chat.schemas import (
    ChannelCreate,
    ChannelList,
    ChannelResponse,
    DmList,
    DmOpen,
    DmResponse,
    MembersAdd,
    UnreadList,
)
from src.models.chat import OrgChatChannel
from src.organizations.access import require_member
from src.organizations.service import load_organization
from src.posts.visibility import load_live_org
from src.validation import Uuid7

router = APIRouter(tags=["chat"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,80}$")]


def _channel(channel: OrgChatChannel) -> ChannelResponse:
    return ChannelResponse(
        id=channel.channel_id,
        name=channel.name,
        topic=channel.topic,
        visibility=channel.visibility,
        archived=channel.archived_at is not None,
        created_at=channel.created_at,
    )


@router.get("/organizations/{slug}/chat/channels")
def list_channels(slug: Slug, principal: CurrentPrincipal, db: Db) -> ChannelList:
    org = load_organization(db, slug)
    require_member(db, org, principal.user.id)
    rows = channels.visible_channels(db, org, principal.user.id)
    return ChannelList(items=[_channel(row) for row in rows])


@router.post(
    "/organizations/{slug}/chat/channels",
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    slug: Slug, payload: ChannelCreate, principal: CurrentPrincipal, db: Db
) -> ChannelResponse:
    org = load_organization(db, slug)
    channel = channels.create_channel(db, org, principal.user.id, payload)
    return _channel(channel)


@router.post(
    "/chat/channels/{channel_id}/archive", status_code=status.HTTP_204_NO_CONTENT
)
def archive_channel(channel_id: Uuid7, principal: CurrentPrincipal, db: Db) -> None:
    room = load_room(db, channel_id, principal.user.id)
    channels.archive_channel(db, room, principal.user.id)


@router.post(
    "/chat/channels/{channel_id}/members", status_code=status.HTTP_204_NO_CONTENT
)
def add_members(
    channel_id: Uuid7, payload: MembersAdd, principal: CurrentPrincipal, db: Db
) -> None:
    room = load_room(db, channel_id, principal.user.id)
    org = load_live_org(db, room.org_id)
    channels.add_members(db, room, org, payload.user_ids, principal.user.id)


@router.delete(
    "/chat/channels/{channel_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    channel_id: Uuid7, user_id: Uuid7, principal: CurrentPrincipal, db: Db
) -> None:
    room = load_room(db, channel_id, principal.user.id)
    channels.remove_member(db, room, user_id)
    # The removed person stops hearing the channel at once, not at their next reconnect.
    revoke(channel_id, user_id)


@router.get("/organizations/{slug}/chat/dms")
def list_dms(slug: Slug, principal: CurrentPrincipal, db: Db) -> DmList:
    org = load_organization(db, slug)
    require_member(db, org, principal.user.id)
    return DmList(items=dms.list_dms(db, org, principal.user.id))


@router.post("/organizations/{slug}/chat/dms", status_code=status.HTTP_201_CREATED)
def open_dm(
    slug: Slug, payload: DmOpen, principal: CurrentPrincipal, db: Db
) -> DmResponse:
    org = load_organization(db, slug)
    pair = dms.open_dm(db, org, principal.user.id, payload.user_id)
    return dms.dm_response(db, pair, principal.user.id)


@router.get("/organizations/{slug}/chat/unread")
def unread(slug: Slug, principal: CurrentPrincipal, db: Db) -> UnreadList:
    org = load_organization(db, slug)
    require_member(db, org, principal.user.id)
    return UnreadList(items=room_state.unread_counts(db, org, principal.user.id))
