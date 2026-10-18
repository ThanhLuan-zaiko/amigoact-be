"""@name mention matching with room-visibility gating (pure helpers)."""

from __future__ import annotations

from uuid import UUID

from chat.channel_helpers import gate_row
from chat.channel_interfaces import ChannelStore
from chat.dtos import MentionBrief
from orgs.interfaces import MemberRepository, UserDirectory
from rbac.interfaces import AccessControl

MAX_MENTIONS = 10


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
        or access.has_permission(ctx.org.id, user_id, "chat:manage")
        or channels.get_channel_member(gate.channel_id, user_id)
        is not None
    )


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
    return list(found.values())
