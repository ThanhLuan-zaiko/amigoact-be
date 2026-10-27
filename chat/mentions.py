"""@name mention matching with room-visibility gating (pure helpers)."""

from __future__ import annotations

import re
from uuid import UUID

from chat.channel_helpers import gate_row
from chat.channel_interfaces import ChannelStore
from chat.dtos import MentionBrief
from chat.permissions import MENTION_ALL, VIEW_PRIVATE, holds_chat_permission
from orgs.interfaces import MemberRepository, UserDirectory
from rbac.interfaces import AccessControl

MAX_MENTIONS = 10
# @all / @everyone is stored as one sentinel mention; recipients are
# expanded at notify time so a message never embeds the whole roster.
ALL_USER_ID = UUID(int=0)
MAX_ALL_RECIPIENTS = 200
_ALL_TOKEN = re.compile(r"(?<![\w@])@(all|everyone)(?!\w)", re.IGNORECASE)


def mentionable(
    members: MemberRepository,  # noqa: ARG001 - reserved for seat fallbacks
    access: AccessControl,
    channels: ChannelStore | None,
    ctx,  # noqa: ANN001 - RoomContext from rooms.py
    user_id: UUID,
) -> bool:
    """True when the named member may open this room.

    A mention notifies with a body preview, so a restricted channel
    (or a thread under a restricted parent) only ever names users who
    can actually read the room: roster seats plus managers.
    """
    channel = ctx.channel
    if channel is None or channels is None:
        return True
    gate = gate_row(channels, channel)
    if getattr(gate, "visibility", "org") != "restricted":
        return True
    return (
        ctx.org.owner_id == user_id
        or holds_chat_permission(access, ctx.org.id, user_id, VIEW_PRIVATE)
        or channels.get_channel_member(gate.channel_id, user_id)
        is not None
    )


def can_mention_all(
    access: AccessControl, ctx, actor_id: UUID  # noqa: ANN001
) -> bool:
    """Owner or chat:mention-all holder, in org rooms only (never dms)."""
    return ctx.dm is None and (
        ctx.org.owner_id == actor_id
        or holds_chat_permission(access, ctx.org.id, actor_id, MENTION_ALL)
    )


def all_recipients(
    members: MemberRepository,
    access: AccessControl,
    channels: ChannelStore | None,
    ctx,  # noqa: ANN001
    actor_id: UUID,
) -> list[UUID]:
    """Active members who may open the room, minus the sender, capped."""
    seen: dict[UUID, None] = {}
    candidates = [ctx.org.owner_id] + [
        row.user_id
        for row in members.list_by_org(ctx.org.id)
        if (row.status or "active") == "active"
    ]
    for user_id in candidates:
        if user_id == actor_id or user_id in seen:
            continue
        if mentionable(members, access, channels, ctx, user_id):
            seen[user_id] = None
        if len(seen) >= MAX_ALL_RECIPIENTS:
            break
    return list(seen)


def resolve_mentions(
    members: MemberRepository,
    users: UserDirectory,
    access: AccessControl,
    channels: ChannelStore | None,
    ctx,  # noqa: ANN001 - RoomContext from rooms.py
    actor_id: UUID,
    text: str,
) -> list[MentionBrief]:
    """@name matches room-visible members; dm rooms never mention."""
    if ctx.dm is not None or "@" not in text:
        return []
    folded = text.casefold()
    candidates = [ctx.org.owner_id] + [
        row.user_id for row in members.list_by_org(ctx.org.id)
    ]
    found: dict[UUID, MentionBrief] = {}
    for user_id in candidates:
        if user_id == actor_id or user_id in found:
            continue
        brief = users.get_brief(user_id)
        name = (brief.full_name if brief else "") or ""
        if name and f"@{name.casefold()}" in folded:
            if mentionable(members, access, channels, ctx, user_id):
                found[user_id] = MentionBrief(user_id=user_id, name=name)
        if len(found) >= MAX_MENTIONS:
            break
    token = _ALL_TOKEN.search(text)
    if token is not None and can_mention_all(access, ctx, actor_id):
        found[ALL_USER_ID] = MentionBrief(
            user_id=ALL_USER_ID, name=token.group(1).lower()
        )
    return list(found.values())
