"""Channel gates shared by the channel, thread and roster services.

Like rooms.py for room services: the owner/chat:manage rule, the
channel-row 404 and the restricted-seat check repeat across services,
so they live here once. Rows are duck-typed (SimpleNamespace in tests,
cqlengine models in production).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from core.exceptions import ChannelNotFoundError, ForbiddenError
from orgs.interfaces import MemberRepository
from orgs.member_helpers import is_active_member

if TYPE_CHECKING:
    from chat.channel_interfaces import ChannelStore
    from orgs.model import Organization
    from rbac.interfaces import AccessControl


def channel_manager(
    access: "AccessControl", org: "Organization", actor_id: UUID
) -> bool:
    """True for org owner or a chat:manage holder."""
    return org.owner_id == actor_id or access.has_permission(
        org.id, actor_id, "chat:manage"
    )


def require_channel_manager(
    access: "AccessControl", org: "Organization", actor_id: UUID
) -> None:
    if not channel_manager(access, org, actor_id):
        access.record(
            org.id, actor_id, "channel.manage", "chat", None, "denied"
        )
        raise ForbiddenError("Only chat managers can do this.")


def event_creator(
    access: "AccessControl", org: "Organization", actor_id: UUID
) -> bool:
    """True for org owner or an activity:create holder (same rule as drafts)."""
    return org.owner_id == actor_id or access.has_permission(
        org.id, actor_id, "activity:create"
    )


def require_event_creator(
    access: "AccessControl", org: "Organization", actor_id: UUID
) -> None:
    """Gate for chat threads that link an activity."""
    if not event_creator(access, org, actor_id):
        access.record(
            org.id, actor_id, "thread.event", "chat", None, "denied"
        )
        raise ForbiddenError("Only event creators can open an event thread.")


def require_org_member(
    members: MemberRepository, org: "Organization", user_id: UUID
) -> None:
    """Active-membership gate every chat surface applies first."""
    if org.owner_id != user_id and not is_active_member(
        members, org.id, user_id
    ):
        raise ForbiddenError("Only org members can do this.")


def channel_row_or_404(
    channels: "ChannelStore", org_id: UUID, channel_id: UUID
):
    """One channel row scoped to the org, or ChannelNotFoundError."""  # noqa: ANN202
    row = channels.get_channel_in_org(org_id, channel_id)
    if row is None:
        raise ChannelNotFoundError("Channel not found.")
    return row


def gate_row(channels: "ChannelStore", row):  # noqa: ANN001, ANN202
    """The row whose audience gates this room.

    A sub-thread inherits its parent channel's gate (seats live on the
    parent), so restricted checks always resolve through the parent
    chain; anything else gates on its own row.
    """
    parent_room_id = getattr(row, "parent_room_id", None)
    if parent_room_id is None:
        return row
    parent = channels.get_channel(parent_room_id)
    return parent if parent is not None else row


def can_open_channel(
    access: "AccessControl",
    channels: "ChannelStore",
    org: "Organization",
    row,  # noqa: ANN001
    user_id: UUID,
) -> bool:
    """True when the user may open this channel room.

    Org-wide rows open to every member; restricted gates (own row or
    inherited parent gate for threads) need a roster seat or a manager
    role.
    """
    gate = gate_row(channels, row)
    if gate.visibility != "restricted":
        return True
    return (
        org.owner_id == user_id
        or access.has_permission(org.id, user_id, "chat:manage")
        or channels.get_channel_member(gate.channel_id, user_id)
        is not None
    )
