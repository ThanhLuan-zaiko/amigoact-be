"""Room resolution + event helpers shared by chat services.

ChatService (reads/lifecycle) and ChatComposer (writes) need the same
access rule and the same room/inbox fan-out, so the logic lives here
once instead of on either class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from chat.helpers import bucket_of
from chat.channel_helpers import can_open_channel
from chat.channel_interfaces import ChannelStore
from chat.interfaces import ActivityLookup, ChatStore
from core.exceptions import ActivityDeletedError, ForbiddenError
from orgs.interfaces import MemberRepository, OrgRepository
from orgs.member_helpers import is_active_member, live_org

if TYPE_CHECKING:
    from chat.interfaces import ChatEvents
    from chat.model import OrgChatChannelById, OrgDmRoom
    from orgs.model import Organization
    from rbac.interfaces import AccessControl


@dataclass(frozen=True)
class RoomCtx:
    """One resolved room: its org, creation floor, and dm/channel rows."""

    org: "Organization"
    floor: str
    dm: "OrgDmRoom | None"
    channel: "OrgChatChannelById | None" = None
    # The room's linked event sits in the trash or was purged: history
    # stays readable, every write answers ACTIVITY_DELETED.
    activity_deleted: bool = False


def linked_activity_deleted(
    activities: ActivityLookup | None, activity_id: UUID | None
) -> bool:
    """True when a linked event is trashed or no longer exists."""
    if activity_id is None or activities is None:
        return False
    activity = activities.get(activity_id)
    return activity is None or getattr(activity, "deleted_at", None) is not None


def require_live_activity(ctx: RoomCtx) -> None:
    """Freeze writes in rooms whose linked event is deleted."""
    if ctx.activity_deleted:
        raise ActivityDeletedError("The linked event is deleted.")


def open_room(
    chat: ChatStore,
    orgs: OrgRepository,
    members: MemberRepository,
    access: "AccessControl",
    activities: ActivityLookup | None,
    room_id: UUID,
    user_id: UUID,
    action: str,
    channels: ChannelStore | None = None,
) -> RoomCtx:
    """Resolve a room id to its org after proving access.

    A dm room resolves only for its two participants, so
    non-participants get the generic org 404; dm_row is None for
    general and activity rooms. The floor stops history scans at the
    room's own creation month. Restricted channels additionally demand
    a roster seat (or org owner / chat:view-private); a sub-thread inherits
    its parent channel's gate.
    """
    dm = chat.get_dm_room(user_id, room_id)
    activity_deleted = False
    channel = (
        channels.get_channel(room_id) if channels is not None else None
    )
    if dm is not None:
        org = live_org(orgs, dm.org_id)
        floor = bucket_of(dm.created_at)
    elif channel is not None:
        org = live_org(orgs, channel.org_id)
        floor = bucket_of(channel.created_at)
        activity_deleted = linked_activity_deleted(
            activities, getattr(channel, "activity_id", None)
        )
    else:
        activity = (
            activities.get(room_id) if activities is not None else None
        )
        if activity is not None:
            org = live_org(orgs, activity.org_id)
            floor = bucket_of(activity.created_at)
            activity_deleted = (
                getattr(activity, "deleted_at", None) is not None
            )
        else:
            org = live_org(orgs, room_id)
            floor = bucket_of(org.created_at)
    if org.owner_id != user_id and not is_active_member(
        members, org.id, user_id
    ):
        access.record(org.id, user_id, action, "chat", None, "denied")
        raise ForbiddenError("Only org members can do this.")
    if (
        channel is not None
        and channels is not None
        and not can_open_channel(access, channels, org, channel, user_id)
    ):
        access.record(org.id, user_id, action, "chat", room_id, "denied")
        raise ForbiddenError("Only channel members can do this.")
    return RoomCtx(
        org=org, floor=floor, dm=dm, channel=channel,
        activity_deleted=activity_deleted,
    )


def emit(
    events: "ChatEvents",
    room_id: UUID,
    action: str,
    message_id: UUID,
    actor_id: UUID,
) -> None:
    """Best-effort room fan-out; never lets realtime fail a mutation."""
    try:
        events.message_changed(room_id, action, message_id, actor_id)
    except Exception:  # noqa: BLE001 - realtime is best-effort
        pass


def emit_inbox(
    events: "ChatEvents",
    action: str,
    room_id: UUID,
    org_id: UUID,
    peer_ids: tuple[UUID, ...] = (),
) -> None:
    """Best-effort inbox hint; dm rooms address both participants."""
    try:
        events.inbox_changed(action, room_id, org_id, peer_ids)
    except Exception:  # noqa: BLE001 - realtime is best-effort
        pass
